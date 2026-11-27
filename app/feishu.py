# -*- coding: utf-8 -*-
"""飞书开放平台接入：把「文档库（知识库）」与「云盘」里的原始资料读进来。

只用标准库（urllib）。设计原则与其它接入层一致：

* 只读：本模块只做查询与下载，不改动用户在飞书里的任何内容；
* 凭据不落代码：app_id / app_secret 从环境变量或 `~/.dsh/.credentials.yaml` 的 refs 段读取；
* 每个失败都带飞书的 code / msg，权限不足时能直接看出该开哪一项权限。
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://open.feishu.cn"
DEFAULT_TIMEOUT = 30
TOKEN_SAFETY_SECONDS = 60          # token 提前 60 秒视为过期


class FeishuError(Exception):
    """飞书接口调用失败（含 code / msg，便于定位权限问题）。"""

    def __init__(self, message, code=None, status=None, path=None):
        self.code = code
        self.status = status
        self.path = path
        parts = [message]
        if code is not None:
            parts.append("code=%s" % code)
        if status is not None:
            parts.append("HTTP %s" % status)
        if path:
            parts.append(path)
        super(FeishuError, self).__init__("（".join([parts[0], "；".join(parts[1:])]) if len(parts) > 1
                                          else parts[0])


class FeishuConfig(object):
    def __init__(self, app_id=None, app_secret=None, base_url=BASE_URL, timeout=DEFAULT_TIMEOUT,
                 key_source=""):
        self.app_id = app_id or ""
        self.app_secret = app_secret or ""
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.timeout = timeout or DEFAULT_TIMEOUT
        self.key_source = key_source

    @property
    def has_key(self):
        return bool(self.app_id and self.app_secret)

    def masked_app_id(self):
        if not self.app_id:
            return "(未配置)"
        return self.app_id[:8] + "…" + self.app_id[-4:]

    def describe(self):
        return {"app_id": self.masked_app_id(), "base_url": self.base_url,
                "key_source": self.key_source}


def dsh_home():
    return os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")


def dsh_credential_refs(home=None):
    """读 `~/.dsh/.credentials.yaml` 末尾 `refs:` 段里的键值（与 llm.py 同一套约定）。"""
    path = os.path.join(home or dsh_home(), ".credentials.yaml")
    if not os.path.exists(path):
        return {}
    refs = {}
    try:
        with open(path, "r", encoding="utf-8") as fp:
            text = fp.read()
    except OSError:
        return {}
    if "refs:" not in text:
        return {}
    block = text.split("refs:", 1)[1]
    # 只在本行内取值：`\s*` 会跨行，导致“空值 + 下一行的键”被当成这个键的值。
    for m in re.finditer(r"^[ \t]+([A-Za-z0-9_]+)[ \t]*:[ \t]*[\"']?([^\s\"']+)", block, re.M):
        refs[m.group(1)] = m.group(2)
    return refs


def workspace_secret_file(root=None):
    return os.path.join(root or os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "feishu.json")


def resolve_feishu_config(app_id=None, app_secret=None, base_url=None, timeout=None, root=None,
                          home=None):
    """凭据顺序：显式参数 → FEISHU_APP_ID/SECRET 环境变量 → .credentials.yaml 的 refs → config/feishu.json。

    home 用于指定凭据文件所在目录（默认 ~/.dsh），便于测试与多 profile。
    """
    if app_id and app_secret:
        return FeishuConfig(app_id, app_secret, base_url or BASE_URL, timeout, "命令行参数")
    env_id = os.environ.get("FEISHU_APP_ID")
    env_secret = os.environ.get("FEISHU_APP_SECRET")
    if env_id and env_secret:
        return FeishuConfig(env_id, env_secret, base_url or BASE_URL, timeout, "环境变量")
    refs = dsh_credential_refs(home)
    if refs.get("FEISHU_APP_ID") and refs.get("FEISHU_APP_SECRET"):
        return FeishuConfig(refs["FEISHU_APP_ID"], refs["FEISHU_APP_SECRET"],
                            base_url or BASE_URL, timeout, ".credentials.yaml 的 refs 段")
    path = workspace_secret_file(root)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, ValueError):
            data = {}
        if data.get("app_id") and data.get("app_secret"):
            return FeishuConfig(data["app_id"], data["app_secret"],
                                base_url or data.get("base_url") or BASE_URL, timeout, path)
    return FeishuConfig(app_id, app_secret, base_url or BASE_URL, timeout, "")


class FeishuClient(object):
    """薄封装：token 缓存 + 统一的错误信息。transport 可注入，便于离线测试。"""

    def __init__(self, config=None, transport=None, as_user=False, user_auth=None):
        self.config = config or resolve_feishu_config()
        self.transport = transport or self._http
        self.user_auth = user_auth
        self.as_user = bool(as_user or user_auth is not None)
        self._token = None
        self._token_expire_at = 0.0

    # ---- 传输 -------------------------------------------------------
    def _http(self, method, url, headers, body, timeout):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=dict(headers, **{"Content-Type": "application/json; charset=utf-8"}))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"msg": raw[:400]}
            raise FeishuError(payload.get("msg") or "HTTP 错误", code=payload.get("code"),
                              status=exc.code, path=url)
        except urllib.error.URLError as exc:
            raise FeishuError("网络错误：%s" % exc.reason, path=url)
        except ValueError as exc:
            raise FeishuError("返回值不是合法 JSON：%s" % exc, path=url)

    # ---- 基础调用 ---------------------------------------------------
    def token(self):
        if self._token and time.time() < self._token_expire_at:
            return self._token
        if not self.config.has_key:
            raise FeishuError("没有配置飞书应用凭据（app_id/app_secret）")
        payload = self.transport("POST", self.config.base_url + "/open-apis/auth/v3/tenant_access_token/internal",
                                 {}, {"app_id": self.config.app_id,
                                      "app_secret": self.config.app_secret}, self.config.timeout)
        if payload.get("code") not in (0, None):
            raise FeishuError(payload.get("msg") or "获取 tenant_access_token 失败",
                              code=payload.get("code"),
                              path="/open-apis/auth/v3/tenant_access_token/internal")
        token = payload.get("tenant_access_token")
        if not token:
            raise FeishuError("返回里没有 tenant_access_token")
        self._token = token
        self._token_expire_at = time.time() + max(60, int(payload.get("expire") or 7200) - TOKEN_SAFETY_SECONDS)
        return token

    def utoken(self):
        """用户身份令牌（OAuth 授权得到，过期会自动续期）。"""
        if self.user_auth is None:
            raise FeishuError("这个客户端没有配置用户授权，请先跑：python -m app.cli feishu auth")
        return self.user_auth.token()

    def _auth_header(self):
        return "Bearer %s" % (self.utoken() if self.as_user else self.token())

    def request(self, method, path, params=None, data=None, raw=False):
        url = self.config.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {"Authorization": self._auth_header()}
        payload = self.transport(method, url, headers, data, self.config.timeout)
        if raw:
            return payload
        code = payload.get("code")
        if code not in (0, None):
            raise FeishuError(payload.get("msg") or "接口返回失败", code=code, path=path)
        return payload.get("data", payload)

    def paged(self, path, key, params=None, limit=200):
        """按 page_token 翻页，返回 key 对应的列表。"""
        out = []
        page_token = None
        params = dict(params or {})
        while True:
            if page_token:
                params["page_token"] = page_token
            data = self.request("GET", path, params=params)
            out.extend(data.get(key) or [])
            if not data.get("has_more") or len(out) >= limit:
                break
            page_token = data.get("page_token")
            if not page_token:
                break
        return out[:limit]

    # ---- 知识库（文档库） -------------------------------------------
    def wiki_spaces(self, limit=50):
        return self.paged("/open-apis/wiki/v2/spaces", "items", {"page_size": 50}, limit)

    def wiki_nodes(self, space_id, parent_node_token=None, limit=1000):
        return self.paged("/open-apis/wiki/v2/spaces/%s/nodes" % space_id, "items",
                          {"page_size": 50, "parent_node_token": parent_node_token}, limit)

    def walk_wiki(self, spaces=None, limit=1000):
        """递归列出知识库节点，附上 space 名称。"""
        out = []
        spaces = spaces if spaces is not None else self.wiki_spaces()
        for space in spaces:
            queue = list(self.wiki_nodes(space["space_id"]))
            while queue and len(out) < limit:
                node = queue.pop(0)
                node["_space_id"] = space["space_id"]
                node["_space_name"] = space.get("name")
                out.append(node)
                if node.get("has_child"):
                    queue.extend(self.wiki_nodes(space["space_id"], node["node_token"]))
        return out[:limit]

    # ---- 云盘 -------------------------------------------------------
    def drive_files(self, folder_token=None, limit=200):
        return self.paged("/open-apis/drive/v1/files", "files",
                          {"page_size": 200, "folder_token": folder_token,
                           "order_by": "EditedTime", "direction": "DESC"}, limit)

    def walk_drive(self, folder_token=None, depth=3, limit=1000, _level=0):
        out = []
        for item in self.drive_files(folder_token):
            out.append(item)
            if len(out) >= limit:
                break
            if item.get("type") == "folder" and _level < depth:
                out.extend(self.walk_drive(item["token"], depth, limit - len(out), _level + 1))
        return out[:limit]

    # ---- 内容读取 ---------------------------------------------------
    def docx_raw_text(self, document_id):
        data = self.request("GET", "/open-apis/docx/v1/documents/%s/raw_content" % document_id,
                            params={"lang": 0})
        return data.get("content") or ""

    def doc_raw_text(self, doc_token):
        data = self.request("GET", "/open-apis/doc/v2/%s/raw_content" % doc_token)
        return data.get("content") or ""

    def sheet_text(self, spreadsheet_token, max_sheets=20):
        """把电子表格读成 markdown 表格文本（用于资料导入）。"""
        meta = self.request("GET", "/open-apis/sheets/v3/spreadsheets/%s/sheets/query" % spreadsheet_token)
        parts = []
        for sheet in (meta.get("sheets") or [])[:max_sheets]:
            title = sheet.get("title") or sheet.get("sheet_id")
            rng = "%s!A1:Z200" % sheet.get("sheet_id")
            data = self.request("GET",
                                "/open-apis/sheets/v2/spreadsheets/%s/values/%s"
                                % (spreadsheet_token, urllib.parse.quote(rng)))
            values = ((data.get("valueRange") or {}).get("values")) or []
            rows = []
            for row in values:
                cells = []
                for cell in row or []:
                    if isinstance(cell, dict):
                        cell = cell.get("text") or cell.get("link") or ""
                    elif isinstance(cell, list):
                        cell = "".join(str(c.get("text", c)) if isinstance(c, dict) else str(c)
                                       for c in cell)
                    cells.append(str(cell).replace("|", "\\|").replace("\n", " "))
                if any(c.strip() for c in cells):
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                parts.append("## %s\n\n%s" % (title, "\n".join(rows)))
        return "\n\n".join(parts)

    def node_text(self, obj_type, obj_token, title=""):
        """按对象类型取纯文本；不支持的类型返回 (None, 原因)。"""
        if obj_type in ("docx",):
            return self.docx_raw_text(obj_token), None
        if obj_type in ("doc",):
            return self.doc_raw_text(obj_token), None
        if obj_type in ("sheet",):
            return self.sheet_text(obj_token), None
        if obj_type in ("file", "slides", "bitable", "mindnote", "shortcut"):
            return None, "暂不支持的类型：%s（请在飞书里导出为 docx/md 后再导入）" % obj_type
        return None, "未知类型：%s" % obj_type
