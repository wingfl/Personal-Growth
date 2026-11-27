# -*- coding: utf-8 -*-
"""一次性补丁：飞书用户身份（OAuth）接线。

- app/feishu.py：FeishuClient 支持用户令牌（as_user / user_auth）；
- app/feishu_import.py：FeishuSync 增加 auth 模式（auto 优先用户身份）并在 check 里报告；
- app/cli.py：新增 feishu auth / whoami / logout，其余子命令加 --auth。
每处替换断言恰好命中一次。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEISHU = os.path.join(ROOT, "app", "feishu.py")
SYNC = os.path.join(ROOT, "app", "feishu_import.py")
CLI = os.path.join(ROOT, "app", "cli.py")


def patch(path, replacements, label):
    text = io.open(path, encoding="utf-8").read()
    for index, (old, new) in enumerate(replacements, 1):
        count = text.count(old)
        if count != 1:
            sys.stderr.write("%s 第 %d 处补丁命中 %d 次（应为 1），已中止\n"
                             % (label, index, count))
            return False
        text = text.replace(old, new, 1)
        print("✓ %s 第 %d 处补丁已应用" % (label, index))
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)
    return True


# ---------------------------------------------------------------- feishu.py
FEISHU_PATCHES = [
    (
        '''    def __init__(self, config=None, transport=None):
        self.config = config or resolve_feishu_config()
        self.transport = transport or self._http
        self._token = None
        self._token_expire_at = 0.0''',
        '''    def __init__(self, config=None, transport=None, as_user=False, user_auth=None):
        self.config = config or resolve_feishu_config()
        self.transport = transport or self._http
        self.user_auth = user_auth
        self.as_user = bool(as_user or user_auth is not None)
        self._token = None
        self._token_expire_at = 0.0''',
    ),
    (
        '''    def request(self, method, path, params=None, data=None, raw=False):''',
        '''    def utoken(self):
        """用户身份令牌（OAuth 授权得到，过期会自动续期）。"""
        if self.user_auth is None:
            raise FeishuError("这个客户端没有配置用户授权，请先跑：python -m app.cli feishu auth")
        return self.user_auth.token()

    def _auth_header(self):
        return "Bearer %s" % (self.utoken() if self.as_user else self.token())

    def request(self, method, path, params=None, data=None, raw=False):''',
    ),
    (
        '''        headers = {"Authorization": "Bearer %s" % self.token()}''',
        '''        headers = {"Authorization": self._auth_header()}''',
    ),
]

# ---------------------------------------------------------- feishu_import.py
SYNC_PATCHES = [
    (
        '''from .feishu import FeishuClient, FeishuError, resolve_feishu_config''',
        '''from .feishu import FeishuClient, FeishuError, resolve_feishu_config
from .feishu_auth import FeishuAuthError, UserAuth''',
    ),
    (
        '''    def __init__(self, store, client=None, config=None, keywords=None):
        self.store = store
        self.config = config or resolve_feishu_config(root=ROOT)
        self.client = client if client is not None else FeishuClient(self.config)
        self.keywords = tuple(keywords) if keywords else DEFAULT_KEYWORDS''',
        '''    def __init__(self, store, client=None, config=None, keywords=None, auth="auto"):
        """auth：user 只用用户身份、tenant 只用应用身份、auto 优先用户身份。"""
        self.store = store
        self.config = config or resolve_feishu_config(root=ROOT)
        self.keywords = tuple(keywords) if keywords else DEFAULT_KEYWORDS
        self.auth = auth
        if client is not None:
            self.client = client
            self.auth_mode = "user" if client.as_user else "tenant"
        else:
            self.client, self.auth_mode = self._build_client(auth)''',
    ),
    (
        '''    # ---- 权限与连通性 --------------------------------------------------''',
        '''    def _build_client(self, auth):
        user_auth = None
        if auth in ("auto", "user"):
            try:
                candidate = UserAuth(self.config)
            except FeishuAuthError:
                candidate = None
            if candidate is not None and candidate.has_token:
                user_auth = candidate
        if auth == "user" and user_auth is None:
            raise FeishuSyncError(
                "还没有飞书用户授权。请先跑：python -m app.cli feishu auth")
        if user_auth is not None:
            return FeishuClient(self.config, as_user=True, user_auth=user_auth), "user"
        return FeishuClient(self.config), "tenant"

    # ---- 权限与连通性 --------------------------------------------------''',
    ),
    (
        '''        report = {
            "app_id": self.config.masked_app_id(),
            "key_source": self.config.key_source,
            "base_url": self.config.base_url,
            "token_ok": False,''',
        '''        report = {
            "app_id": self.config.masked_app_id(),
            "key_source": self.config.key_source,
            "base_url": self.config.base_url,
            "auth_mode": self.auth_mode,
            "user_auth": (self.client.user_auth.describe()
                          if self.client.user_auth is not None else "未使用用户身份"),
            "token_ok": False,''',
    ),
    (
        '''        try:
            self.client.token()
            report["token_ok"] = True
        except FeishuError as exc:''',
        '''        try:
            if self.client.as_user:
                self.client.utoken()
            else:
                self.client.token()
            report["token_ok"] = True
        except (FeishuError, FeishuAuthError) as exc:''',
    ),
]

# -------------------------------------------------------------------- cli.py
AUTH_HANDLERS = '''def _feishu_auth(args):
    cfg = resolve_feishu_config()
    redirect = args.redirect_uri or DEFAULT_REDIRECT_URI
    scope = args.scope or list(DEFAULT_SCOPES)
    if args.code:
        tokens = exchange_code(cfg, args.code, redirect_uri=redirect)
        backup = store_tokens(tokens, scope=" ".join(scope))
        print("✓ 授权成功，令牌已保存到凭据文件（备份：%s）" % backup)
        _print_whoami(cfg, tokens["access_token"])
        return
    url = authorize_url(cfg, redirect_uri=redirect, scope=scope, state=args.state)
    print("应用：%s（凭据来源：%s）" % (cfg.masked_app_id(), cfg.key_source or "-"))
    print("重定向地址：%s" % redirect)
    print("请求的权限：%s" % " ".join(scope))
    print("\\n在浏览器打开下面的链接并同意授权：\\n%s\\n" % url)
    if args.no_wait:
        print("同意后浏览器会跳到重定向地址，把地址栏里的 code 参数复制回来执行：")
        print("  python -m app.cli feishu auth --code <code>")
        return
    port = args.port or DEFAULT_PORT
    path = urllib.parse.urlparse(redirect).path or "/callback"
    print("等待授权回调（%s:%d%s，最多 %d 秒）…" % ("127.0.0.1", port, path, args.timeout))
    receiver = CodeReceiver(port=port, path=path, expected_state=args.state)
    code = receiver.wait(timeout=args.timeout)
    tokens = exchange_code(cfg, code, redirect_uri=redirect)
    backup = store_tokens(tokens, scope=" ".join(scope))
    print("✓ 授权成功，令牌已保存到凭据文件（备份：%s）" % backup)
    _print_whoami(cfg, tokens["access_token"])


def _print_whoami(cfg, access_token):
    try:
        info = user_info(cfg, access_token)
    except FeishuAuthError as exc:
        print("  （读取当前身份失败：%s）" % exc)
        return
    print("  当前身份：%s（open_id %s）" % (info.get("name"), info.get("open_id")))
    if info.get("email"):
        print("  邮箱：%s" % info["email"])


def _feishu_whoami(args):
    cfg = resolve_feishu_config()
    auth = UserAuth(cfg)
    print("用户授权：%s" % auth.describe())
    if not auth.has_token:
        return
    _print_whoami(cfg, auth.token())


def _feishu_logout(args):
    backup = clear_user_tokens()
    print("已清除本机保存的飞书用户令牌（备份：%s）" % backup)
    print("应用凭据（FEISHU_APP_ID / FEISHU_APP_SECRET）未改动。")


'''

AUTH_PARSERS = '''    q = fs.add_parser("auth", help="用飞书账号授权，换取用户身份令牌（读「我的空间」）")
    q.add_argument("--redirect-uri", dest="redirect_uri",
                   help="重定向地址（默认 %s，需与开放平台配置一致）" % DEFAULT_REDIRECT_URI)
    q.add_argument("--scope", action="append",
                   help="权限点，可重复；默认 drive/wiki/docx/sheets 只读 + offline_access")
    q.add_argument("--state", default="growth-archive", help="防重放校验串")
    q.add_argument("--port", type=int, help="本地回调端口（默认 8765）")
    q.add_argument("--timeout", type=int, default=300, help="等待回调的秒数（默认 300）")
    q.add_argument("--no-wait", action="store_true", dest="no_wait",
                   help="只打印授权链接，稍后用 --code 手动换取令牌")
    q.add_argument("--code", help="已拿到的授权码（与 --no-wait 配合）")
    q.set_defaults(func=_feishu_auth)

    q = fs.add_parser("whoami", help="查看当前用户授权身份与有效期")
    q.set_defaults(func=_feishu_whoami)

    q = fs.add_parser("logout", help="清除本机保存的飞书用户令牌")
    q.set_defaults(func=_feishu_logout)

    return parser'''

CLI_PATCHES = [
    (
        '''from .feishu import FeishuError, resolve_feishu_config
from .feishu_import import FeishuSync, FeishuSyncError
''',
        '''from .feishu import FeishuError, resolve_feishu_config
from .feishu_auth import (DEFAULT_PORT, DEFAULT_REDIRECT_URI, DEFAULT_SCOPES,
                          CodeReceiver, FeishuAuthError, UserAuth, authorize_url,
                          clear_user_tokens, exchange_code, store_tokens, user_info)
from .feishu_import import FeishuSync, FeishuSyncError
''',
    ),
    (
        '''        sync = FeishuSync(store, keywords=_split_keywords(args.match))
        report = sync.check()''',
        '''        sync = FeishuSync(store, keywords=_split_keywords(args.match), auth=args.auth)
        report = sync.check()''',
    ),
    (
        '''        print("应用令牌：%s" % ("正常" if report["token_ok"] else "失败"))''',
        '''        print("身份：%s（用户授权：%s）" % (report["auth_mode"], report["user_auth"]))
        print("令牌：%s" % ("正常" if report["token_ok"] else "失败"))''',
    ),
    (
        '''        sync = FeishuSync(store)
        spaces = sync.client.wiki_spaces()''',
        '''        sync = FeishuSync(store, auth=args.auth)
        spaces = sync.client.wiki_spaces()''',
    ),
    (
        '''        sync = FeishuSync(store, keywords=_split_keywords(args.match))
        nodes = _feishu_nodes(sync, args)
        if not nodes:''',
        '''        sync = FeishuSync(store, keywords=_split_keywords(args.match), auth=args.auth)
        nodes = _feishu_nodes(sync, args)
        if not nodes:''',
    ),
    (
        '''        sync = FeishuSync(store, keywords=_split_keywords(args.match))
        nodes = _feishu_nodes(sync, args)
        result = sync.pull(''',
        '''        sync = FeishuSync(store, keywords=_split_keywords(args.match), auth=args.auth)
        nodes = _feishu_nodes(sync, args)
        result = sync.pull(''',
    ),
    (
        '''def build_parser():''',
        AUTH_HANDLERS + '''def build_parser():''',
    ),
    (
        '''    q = fs.add_parser("check", help="检查应用凭据、权限与可见范围")
    q.add_argument("--match", help="只看名称含这些关键词的资料（逗号分隔，默认 周报,月报）")
    q.set_defaults(func=_feishu_check)''',
        '''    q = fs.add_parser("check", help="检查凭据、权限与可见范围")
    q.add_argument("--match", help="只看名称含这些关键词的资料（逗号分隔，默认 周报,月报）")
    q.add_argument("--auth", default="auto", choices=["auto", "user", "tenant"],
                   help="用哪种身份调用飞书（默认 auto：有用户授权就用用户身份）")
    q.set_defaults(func=_feishu_check)''',
    ),
    (
        '''    q = fs.add_parser("spaces", help="列出应用可见的知识库")
    q.set_defaults(func=_feishu_spaces)''',
        '''    q = fs.add_parser("spaces", help="列出当前身份可见的知识库")
    q.add_argument("--auth", default="auto", choices=["auto", "user", "tenant"])
    q.set_defaults(func=_feishu_spaces)''',
    ),
    (
        '''    q.add_argument("--limit", type=int, default=500, help="最多扫描多少条")
    q.set_defaults(func=_feishu_scan)''',
        '''    q.add_argument("--limit", type=int, default=500, help="最多扫描多少条")
    q.add_argument("--auth", default="auto", choices=["auto", "user", "tenant"])
    q.set_defaults(func=_feishu_scan)''',
    ),
    (
        '''    q.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="只读正文，不写库")
    q.set_defaults(func=_feishu_pull)''',
        '''    q.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="只读正文，不写库")
    q.add_argument("--auth", default="auto", choices=["auto", "user", "tenant"])
    q.set_defaults(func=_feishu_pull)''',
    ),
    (
        '''    q.add_argument("--auth", default="auto", choices=["auto", "user", "tenant"])
    q.set_defaults(func=_feishu_pull)

    return parser''',
        '''    q.add_argument("--auth", default="auto", choices=["auto", "user", "tenant"])
    q.set_defaults(func=_feishu_pull)

''' + AUTH_PARSERS,
    ),
    (
        '''    except (ArchiveError, ExtractError, LLMError, ModelError, ValidationError, Conflict,
            FeishuError, FeishuSyncError,
''',
        '''    except (ArchiveError, ExtractError, LLMError, ModelError, ValidationError, Conflict,
            FeishuError, FeishuSyncError, FeishuAuthError,
''',
    ),
]


def main():
    if not patch(FEISHU, FEISHU_PATCHES, "feishu.py"):
        return 1
    if not patch(SYNC, SYNC_PATCHES, "feishu_import.py"):
        return 1
    if not patch(CLI, CLI_PATCHES, "cli.py"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
