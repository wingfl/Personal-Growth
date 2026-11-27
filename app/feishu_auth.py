# -*- coding: utf-8 -*-
"""飞书用户身份授权（OAuth）：拿 user_access_token，直接读「我的空间」的云文档。

为什么需要它：应用身份（tenant_access_token）只能读「被显式分享给应用」的文档；
用户身份则代表你本人，能看到你自己在云盘与知识库里的全部内容。

流程（飞书新版 OAuth）：
  1. 打开授权链接：https://accounts.feishu.cn/open-apis/authen/v1/authorize
     ?client_id=<app_id>&redirect_uri=<uri>&scope=<scope>&state=<state>
  2. 你同意后浏览器跳回 redirect_uri，URL 上带一次性 code；
  3. 用 code 调 /open-apis/authen/v2/oauth/token 换 access_token + refresh_token；
  4. access_token 有效期约 2 小时，过期用 refresh_token 自动续（scope 里必须含 offline_access）。

令牌保存在 ~/.dsh/.credentials.yaml 的 refs 段（与 FEISHU_APP_ID 同一处），
写入前先备份；命令行与日志只打印掩码，不打印令牌本身。
"""
import io
import json
import os
import shutil
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from .feishu import FeishuError, FeishuConfig, dsh_home, resolve_feishu_config

AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
TOKEN_PATH = "/open-apis/authen/v2/oauth/token"
USER_INFO_PATH = "/open-apis/authen/v1/user_info"

DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"
DEFAULT_PORT = 8765
DEFAULT_SCOPES = (
    "drive:drive:readonly",
    "wiki:wiki:readonly",
    "docx:document:readonly",
    "sheets:spreadsheet:readonly",
    "offline_access",
)

ACCESS_TOKEN_KEY = "FEISHU_USER_ACCESS_TOKEN"
REFRESH_TOKEN_KEY = "FEISHU_USER_REFRESH_TOKEN"
EXPIRES_AT_KEY = "FEISHU_USER_EXPIRES_AT"
SCOPE_KEY = "FEISHU_USER_SCOPE"
REFRESH_EXPIRES_AT_KEY = "FEISHU_USER_REFRESH_EXPIRES_AT"

ISO = "%Y-%m-%dT%H:%M:%SZ"


class FeishuAuthError(Exception):
    pass


# --------------------------------------------------------------------------
# 凭据文件读写（refs 段）
# --------------------------------------------------------------------------
def credentials_path(home=None):
    return os.path.join(home or dsh_home(), ".credentials.yaml")


def _read_lines(path):
    with io.open(path, encoding="utf-8") as fp:
        return fp.read().splitlines()


def save_refs(pairs, home=None):
    """把键值写进 .credentials.yaml 的 refs 段（存在则更新），写入前备份。"""
    path = credentials_path(home)
    if not os.path.isfile(path):
        raise FeishuAuthError("找不到凭据文件：%s" % path)
    lines = _read_lines(path)
    backup = "%s.bak-%s" % (path, datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, backup)

    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "refs:")
    except StopIteration:
        lines.append("refs:")
        start = len(lines) - 1

    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.strip() and not line[:1].isspace():
            end = i
            break

    block = lines[start + 1:end]
    remaining = dict(pairs)
    for index, line in enumerate(block):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip()
        if key in remaining:
            block[index] = "  %s: %s" % (key, remaining.pop(key))
    for key, value in remaining.items():
        block.append("  %s: %s" % (key, value))

    lines[start + 1:end] = block
    with io.open(path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write("\n".join(lines) + "\n")
    return backup


def load_user_tokens(home=None):
    """从凭据文件读回用户令牌（不打印内容）。"""
    from .feishu import dsh_credential_refs

    refs = dsh_credential_refs(home)
    return {
        "access_token": refs.get(ACCESS_TOKEN_KEY),
        "refresh_token": refs.get(REFRESH_TOKEN_KEY),
        "expires_at": refs.get(EXPIRES_AT_KEY),
        "scope": refs.get(SCOPE_KEY),
        "refresh_expires_at": refs.get(REFRESH_EXPIRES_AT_KEY),
        "has_refresh": bool(refs.get(REFRESH_TOKEN_KEY)),
    }


def clear_user_tokens(home=None):
    return save_refs({ACCESS_TOKEN_KEY: "", REFRESH_TOKEN_KEY: "",
                      EXPIRES_AT_KEY: "", REFRESH_EXPIRES_AT_KEY: "", SCOPE_KEY: ""},
                     home=home)


# --------------------------------------------------------------------------
# OAuth 流程
# --------------------------------------------------------------------------
def authorize_url(config, redirect_uri=DEFAULT_REDIRECT_URI, scope=None, state=None):
    if not config.has_key:
        raise FeishuAuthError("缺少飞书应用凭据（app_id/app_secret），无法发起授权。")
    scopes = " ".join(scope) if isinstance(scope, (list, tuple)) else (scope or " ".join(DEFAULT_SCOPES))
    params = {
        "client_id": config.app_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state or "growth-archive",
    }
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def _post_token(config, payload, transport=None):
    url = config.base_url + TOKEN_PATH
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if transport is not None:
        return transport("POST", url, {"Content-Type": "application/json"}, payload, config.timeout)
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=config.timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except ValueError:
            raise FeishuAuthError("换取令牌失败：HTTP %s %s" % (exc.code, raw[:300]))
    except urllib.error.URLError as exc:
        raise FeishuAuthError("网络错误：%s" % exc.reason)


def _tokens_from_payload(payload, what="换取"):
    if not isinstance(payload, dict):
        raise FeishuAuthError("%s令牌失败：返回不是 JSON 对象" % what)
    error = payload.get("error") or (payload.get("code") not in (0, None) and payload.get("msg"))
    access = payload.get("access_token") or (payload.get("data") or {}).get("access_token")
    if error or not access:
        detail = payload.get("error_description") or payload.get("msg") or json.dumps(
            payload, ensure_ascii=False)[:300]
        raise FeishuAuthError("%s令牌失败：%s" % (what, detail))
    data = payload.get("data") or payload
    return {
        "access_token": access,
        "refresh_token": data.get("refresh_token"),
        "expires_in": int(data.get("expires_in") or 7200),
        "refresh_expires_in": data.get("refresh_token_expires_in") or data.get("refresh_expires_in"),
        "scope": data.get("scope"),
        "token_type": data.get("token_type") or "Bearer",
    }


def exchange_code(config, code, redirect_uri=DEFAULT_REDIRECT_URI, transport=None):
    payload = _post_token(config, {
        "grant_type": "authorization_code",
        "client_id": config.app_id,
        "client_secret": config.app_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }, transport=transport)
    return _tokens_from_payload(payload, what="换取")


def refresh_user_token(config, refresh_token, transport=None):
    payload = _post_token(config, {
        "grant_type": "refresh_token",
        "client_id": config.app_id,
        "client_secret": config.app_secret,
        "refresh_token": refresh_token,
    }, transport=transport)
    return _tokens_from_payload(payload, what="刷新")


def store_tokens(tokens, home=None, scope=None):
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=max(60, tokens["expires_in"] - 120))
    pairs = {
        ACCESS_TOKEN_KEY: tokens["access_token"],
        REFRESH_TOKEN_KEY: tokens.get("refresh_token") or "",
        EXPIRES_AT_KEY: expires_at.strftime(ISO),
    }
    if tokens.get("refresh_expires_in"):
        pairs[REFRESH_EXPIRES_AT_KEY] = (
            now + timedelta(seconds=int(tokens["refresh_expires_in"]))).strftime(ISO)
    if tokens.get("scope") or scope:
        pairs[SCOPE_KEY] = tokens.get("scope") or scope
    return save_refs(pairs, home=home)


# --------------------------------------------------------------------------
# 本地回调服务器
# --------------------------------------------------------------------------
class CodeReceiver(object):
    """起一个只接收一次回调的临时 HTTP 服务。"""

    def __init__(self, port=DEFAULT_PORT, path="/callback", expected_state=None):
        self.port = port
        self.path = path
        self.expected_state = expected_state
        self.code = None
        self.error = None
        self._event = threading.Event()
        self._server = None

    def _handler_class(self):
        receiver = self

        from http.server import BaseHTTPRequestHandler

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # 静音
                pass

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                code = (query.get("code") or [None])[0]
                state = (query.get("state") or [None])[0]
                error = (query.get("error") or [None])[0]
                if parsed.path != receiver.path:
                    self.send_response(404)
                    self.end_headers()
                    return
                if error:
                    receiver.error = error
                elif not code:
                    receiver.error = "回调里没有 code 参数"
                elif receiver.expected_state and state and state != receiver.expected_state:
                    receiver.error = "state 不匹配，已拒绝这次回调"
                else:
                    receiver.code = code
                body = ("<html><meta charset='utf-8'><body>"
                        "<h3>%s</h3><p>可以关闭这个页面，回到终端继续。</p></body></html>"
                        % ("授权成功" if receiver.code else "授权失败：%s" % receiver.error))
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                receiver._event.set()

        return Handler

    def wait(self, timeout=300):
        from http.server import HTTPServer

        self._server = HTTPServer(("127.0.0.1", self.port), self._handler_class())
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        try:
            self._event.wait(timeout)
        finally:
            self._server.shutdown()
            self._server.server_close()
        if self.error:
            raise FeishuAuthError(self.error)
        if not self.code:
            raise FeishuAuthError("等待授权回调超时（%d 秒）；可用 --no-wait 打印链接后手动粘贴 code。" % timeout)
        return self.code


# --------------------------------------------------------------------------
# 运行时：带自动续期的用户令牌
# --------------------------------------------------------------------------
class UserAuth(object):
    """给 FeishuClient 用的用户令牌供应器：过期自动用 refresh_token 续。"""

    def __init__(self, config=None, tokens=None, transport=None, home=None):
        self.config = config or resolve_feishu_config(home=home)
        self.home = home
        self.transport = transport
        self.tokens = tokens if tokens is not None else load_user_tokens(home=home)

    @property
    def has_token(self):
        return bool(self.tokens.get("access_token") or self.tokens.get("refresh_token"))

    def describe(self):
        if not self.has_token:
            return "未授权（先跑 python -m app.cli feishu auth）"
        expires = self.tokens.get("expires_at") or "-"
        return "已授权，令牌有效至 %s（scope：%s）" % (expires, self.tokens.get("scope") or "-")

    def _expired(self):
        expires_at = self.tokens.get("expires_at")
        if not expires_at:
            return True
        try:
            deadline = datetime.strptime(expires_at, ISO).replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        return datetime.now(timezone.utc) >= deadline

    def token(self):
        if not self.has_token:
            raise FeishuAuthError(
                "还没有飞书用户授权。先跑：python -m app.cli feishu auth")
        if self.tokens.get("access_token") and not self._expired():
            return self.tokens["access_token"]
        refresh = self.tokens.get("refresh_token")
        if not refresh:
            raise FeishuAuthError("用户令牌已过期且没有 refresh_token，请重新跑 feishu auth。")
        fresh = refresh_user_token(self.config, refresh, transport=self.transport)
        store_tokens(fresh, home=self.home, scope=self.tokens.get("scope"))
        self.tokens = load_user_tokens(home=self.home)
        return self.tokens["access_token"]


def user_info(config, access_token, transport=None):
    """读取当前授权用户（用于 whoami）。"""
    url = config.base_url + USER_INFO_PATH + "?user_id_type=open_id"
    if transport is not None:
        payload = transport("GET", url, {"Authorization": "Bearer %s" % access_token}, None,
                            config.timeout)
    else:
        import urllib.request

        req = urllib.request.Request(url, headers={"Authorization": "Bearer %s" % access_token})
        try:
            with urllib.request.urlopen(req, timeout=config.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # 网络或权限问题都不该阻断主流程
            raise FeishuAuthError("读取用户信息失败：%s" % exc)
    if payload.get("code") not in (0, None):
        raise FeishuAuthError("读取用户信息失败：%s" % payload.get("msg"))
    data = payload.get("data") or payload
    return {"name": data.get("name"), "open_id": data.get("open_id"),
            "email": data.get("email") or data.get("enterprise_email"),
            "avatar_url": data.get("avatar_url")}
