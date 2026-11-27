# -*- coding: utf-8 -*-
"""飞书用户身份 OAuth 的离线用例：不联网，全部靠注入的假 transport 与临时凭据文件。"""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.feishu import FeishuConfig
from app.feishu_auth import (ACCESS_TOKEN_KEY, DEFAULT_REDIRECT_URI, DEFAULT_SCOPES,
                             EXPIRES_AT_KEY, REFRESH_TOKEN_KEY, SCOPE_KEY, CodeReceiver,
                             FeishuAuthError, UserAuth, authorize_url, clear_user_tokens,
                             exchange_code, load_user_tokens, refresh_user_token,
                             save_refs, store_tokens, user_info)
from app.feishu_import import FeishuSync, FeishuSyncError

CREDENTIALS = """version: 1
records:
  - kind: client-connection
    id: abc
refs:
  NEORIGIN_API_KEY: sk-existing-key
"""


class FakeTransport(object):
    """记录调用并按序返回响应；transport(method, url, headers, payload, timeout)。"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, payload, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "payload": payload})
        if not self.responses:
            raise AssertionError("FakeTransport 收到了多余的调用：%s %s" % (method, url))
        reply = self.responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def token_payload(access="u-token-1", refresh="r-token-1", expires_in=7200, scope="drive:drive:readonly"):
    return {"code": 0, "msg": "success",
            "data": {"access_token": access, "refresh_token": refresh,
                     "expires_in": expires_in, "scope": scope, "token_type": "Bearer"}}


def make_config():
    return FeishuConfig("cli_aa5da4127eb81cf1", "secret", "https://open.feishu.cn", 5, "test")


class TempHomeCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="growth-auth-")
        with io.open(os.path.join(self.home, ".credentials.yaml"), "w",
                     encoding="utf-8", newline="\n") as fp:
            fp.write(CREDENTIALS)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def credentials_text(self):
        with io.open(os.path.join(self.home, ".credentials.yaml"), encoding="utf-8") as fp:
            return fp.read()


class AuthorizeUrlTest(TempHomeCase):
    def test_authorize_url_carries_client_redirect_scope_state(self):
        url = authorize_url(make_config(), redirect_uri=DEFAULT_REDIRECT_URI,
                            scope=None, state="st-1")
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "accounts.feishu.cn")
        self.assertEqual(query["client_id"], ["cli_aa5da4127eb81cf1"])
        self.assertEqual(query["redirect_uri"], [DEFAULT_REDIRECT_URI])
        self.assertEqual(query["state"], ["st-1"])
        self.assertEqual(query["scope"], [" ".join(DEFAULT_SCOPES)])
        self.assertIn("offline_access", query["scope"][0])

    def test_authorize_url_without_credentials_is_rejected(self):
        with self.assertRaises(FeishuAuthError):
            authorize_url(FeishuConfig("", "", "https://open.feishu.cn", 5, ""))

    def test_authorize_url_accepts_custom_scope_list(self):
        url = authorize_url(make_config(), scope=["drive:drive:readonly"], state="s")
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["scope"],
                         ["drive:drive:readonly"])


class TokenExchangeTest(TempHomeCase):
    def test_exchange_code_sends_app_credentials_and_parses_tokens(self):
        transport = FakeTransport(token_payload())
        tokens = exchange_code(make_config(), "code-1", transport=transport)
        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/open-apis/authen/v2/oauth/token"))
        self.assertEqual(call["payload"]["grant_type"], "authorization_code")
        self.assertEqual(call["payload"]["client_secret"], "secret")
        self.assertEqual(call["payload"]["redirect_uri"], DEFAULT_REDIRECT_URI)
        self.assertEqual(tokens["access_token"], "u-token-1")
        self.assertEqual(tokens["refresh_token"], "r-token-1")
        self.assertEqual(tokens["expires_in"], 7200)

    def test_exchange_code_surfaces_provider_error(self):
        transport = FakeTransport({"error": "invalid_grant",
                                   "error_description": "code 已失效"})
        with self.assertRaises(FeishuAuthError) as ctx:
            exchange_code(make_config(), "bad", transport=transport)
        self.assertIn("code 已失效", str(ctx.exception))

    def test_refresh_uses_refresh_token_grant(self):
        transport = FakeTransport(token_payload(access="u-token-2", refresh="r-token-2"))
        tokens = refresh_user_token(make_config(), "r-token-1", transport=transport)
        self.assertEqual(transport.calls[0]["payload"]["grant_type"], "refresh_token")
        self.assertEqual(transport.calls[0]["payload"]["refresh_token"], "r-token-1")
        self.assertEqual(tokens["access_token"], "u-token-2")


class CredentialsFileTest(TempHomeCase):
    def test_store_tokens_writes_keys_and_keeps_existing_refs(self):
        backup = store_tokens({"access_token": "u-1", "refresh_token": "r-1",
                               "expires_in": 7200, "scope": "drive:drive:readonly"},
                              home=self.home)
        self.assertTrue(os.path.isfile(backup))
        text = self.credentials_text()
        self.assertIn("sk-existing-key", text)
        self.assertIn(ACCESS_TOKEN_KEY, text)
        self.assertIn(REFRESH_TOKEN_KEY, text)
        self.assertIn("drive:drive:readonly", text)
        tokens = load_user_tokens(home=self.home)
        self.assertEqual(tokens["access_token"], "u-1")
        self.assertEqual(tokens["refresh_token"], "r-1")
        self.assertEqual(tokens["scope"], "drive:drive:readonly")
        self.assertEqual(tokens["expires_at"][-1], "Z")
        self.assertTrue(tokens["has_refresh"])

    def test_save_refs_updates_key_in_place(self):
        save_refs({ACCESS_TOKEN_KEY: "first"}, home=self.home)
        save_refs({ACCESS_TOKEN_KEY: "second"}, home=self.home)
        lines = [line for line in self.credentials_text().splitlines()
                 if line.strip().startswith(ACCESS_TOKEN_KEY)]
        self.assertEqual(len(lines), 1)
        self.assertEqual(load_user_tokens(home=self.home)["access_token"], "second")

    def test_save_refs_appends_refs_section_when_missing(self):
        path = os.path.join(self.home, ".credentials.yaml")
        with io.open(path, "w", encoding="utf-8", newline="\n") as fp:
            fp.write("version: 1\n")
        save_refs({SCOPE_KEY: "drive:drive:readonly"}, home=self.home)
        self.assertIn("refs:", self.credentials_text())
        self.assertEqual(load_user_tokens(home=self.home)["scope"], "drive:drive:readonly")

    def test_save_refs_on_missing_file_is_rejected(self):
        with self.assertRaises(FeishuAuthError):
            save_refs({ACCESS_TOKEN_KEY: "x"}, home=os.path.join(self.home, "nope"))

    def test_clear_user_tokens_empties_values(self):
        store_tokens({"access_token": "u-1", "refresh_token": "r-1", "expires_in": 7200},
                     home=self.home)
        clear_user_tokens(home=self.home)
        tokens = load_user_tokens(home=self.home)
        self.assertFalse(tokens["access_token"])
        self.assertFalse(tokens["has_refresh"])


class UserAuthTest(TempHomeCase):
    def test_reuses_valid_token_without_calling_transport(self):
        store_tokens({"access_token": "u-valid", "refresh_token": "r-1",
                      "expires_in": 7200}, home=self.home)
        transport = FakeTransport()
        auth = UserAuth(config=make_config(), transport=transport, home=self.home)
        self.assertTrue(auth.has_token)
        self.assertEqual(auth.token(), "u-valid")
        self.assertEqual(transport.calls, [])
        self.assertIn("已授权", auth.describe())

    def test_expired_token_is_refreshed_and_persisted(self):
        save_refs({ACCESS_TOKEN_KEY: "u-old", REFRESH_TOKEN_KEY: "r-old",
                   EXPIRES_AT_KEY: "2000-01-01T00:00:00Z",
                   SCOPE_KEY: "drive:drive:readonly"}, home=self.home)
        transport = FakeTransport(token_payload(access="u-new", refresh="r-new"))
        auth = UserAuth(config=make_config(), transport=transport, home=self.home)
        self.assertEqual(auth.token(), "u-new")
        self.assertEqual(transport.calls[0]["payload"]["grant_type"], "refresh_token")
        self.assertEqual(load_user_tokens(home=self.home)["access_token"], "u-new")

    def test_expired_token_without_refresh_token_asks_to_reauthorize(self):
        save_refs({ACCESS_TOKEN_KEY: "u-old", REFRESH_TOKEN_KEY: "",
                   EXPIRES_AT_KEY: "2000-01-01T00:00:00Z"}, home=self.home)
        auth = UserAuth(config=make_config(), transport=FakeTransport(), home=self.home)
        with self.assertRaises(FeishuAuthError) as ctx:
            auth.token()
        self.assertIn("重新跑", str(ctx.exception))

    def test_without_any_token_raises_with_hint(self):
        auth = UserAuth(config=make_config(), transport=FakeTransport(), home=self.home)
        self.assertFalse(auth.has_token)
        self.assertIn("未授权", auth.describe())
        with self.assertRaises(FeishuAuthError) as ctx:
            auth.token()
        self.assertIn("feishu auth", str(ctx.exception))

    def test_unparsable_expires_at_is_treated_as_expired(self):
        save_refs({ACCESS_TOKEN_KEY: "u-old", REFRESH_TOKEN_KEY: "r-old",
                   EXPIRES_AT_KEY: "不是时间"}, home=self.home)
        transport = FakeTransport(token_payload(access="u-new"))
        auth = UserAuth(config=make_config(), transport=transport, home=self.home)
        self.assertEqual(auth.token(), "u-new")


class UserInfoTest(TempHomeCase):
    def test_user_info_parses_name_and_open_id(self):
        transport = FakeTransport({"code": 0, "data": {"name": "张三", "open_id": "ou_1",
                                                       "enterprise_email": "z@example.com"}})
        info = user_info(make_config(), "u-1", transport=transport)
        self.assertEqual(info["name"], "张三")
        self.assertEqual(info["open_id"], "ou_1")
        self.assertEqual(info["email"], "z@example.com")
        self.assertIn("Bearer u-1", transport.calls[0]["headers"]["Authorization"])

    def test_user_info_reports_provider_error(self):
        transport = FakeTransport({"code": 99991663, "msg": "token 无效"})
        with self.assertRaises(FeishuAuthError):
            user_info(make_config(), "bad", transport=transport)


class CodeReceiverTest(TempHomeCase):
    def _run_receiver(self, expected_state, query):
        receiver = CodeReceiver(port=0, path="/callback", expected_state=expected_state)
        outcome = {}

        def run():
            try:
                outcome["code"] = receiver.wait(timeout=10)
            except Exception as exc:  # noqa: BLE001 - 测试要断言异常类型
                outcome["error"] = exc

        thread = threading.Thread(target=run)
        thread.start()
        port = None
        deadline = time.time() + 5
        while time.time() < deadline:
            if receiver._server is not None:
                port = receiver._server.server_address[1]
                break
            time.sleep(0.02)
        self.assertTrue(port, "回调服务没有起来")
        url = "http://127.0.0.1:%d/callback?%s" % (port, query)
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8")
        thread.join(timeout=10)
        return outcome, body

    def test_receives_code_and_returns_success_page(self):
        outcome, body = self._run_receiver("st-1", "code=code-abc&state=st-1")
        self.assertEqual(outcome.get("code"), "code-abc")
        self.assertIn("授权成功", body)

    def test_state_mismatch_is_rejected(self):
        outcome, body = self._run_receiver("st-9", "code=code-abc&state=other")
        self.assertIsInstance(outcome.get("error"), FeishuAuthError)
        self.assertIn("state", str(outcome["error"]))
        self.assertIn("授权失败", body)

    def test_missing_code_reports_error(self):
        outcome, _ = self._run_receiver("st-1", "state=st-1")
        self.assertIsInstance(outcome.get("error"), FeishuAuthError)
        self.assertIn("code", str(outcome["error"]))


class SyncAuthModeTest(TempHomeCase):
    def test_user_mode_without_token_is_rejected(self):
        sync_store = _FakeStore()
        with self.assertRaises(FeishuSyncError) as ctx:
            FeishuSync(sync_store, config=make_config(), auth="user", home=self.home)
        self.assertIn("feishu auth", str(ctx.exception))

    def test_auto_mode_falls_back_to_tenant_without_user_token(self):
        sync = FeishuSync(_FakeStore(), config=make_config(), auth="auto", home=self.home)
        self.assertEqual(sync.auth_mode, "tenant")
        self.assertFalse(sync.client.as_user)

    def test_auto_mode_prefers_user_token_when_present(self):
        store_tokens({"access_token": "u-1", "refresh_token": "r-1", "expires_in": 7200},
                     home=self.home)
        sync = FeishuSync(_FakeStore(), config=make_config(), auth="auto", home=self.home)
        self.assertEqual(sync.auth_mode, "user")
        self.assertTrue(sync.client.as_user)
        self.assertEqual(sync.client._auth_header(), "Bearer u-1")

    def test_tenant_mode_ignores_user_token(self):
        store_tokens({"access_token": "u-1", "refresh_token": "r-1", "expires_in": 7200},
                     home=self.home)
        sync = FeishuSync(_FakeStore(), config=make_config(), auth="tenant", home=self.home)
        self.assertEqual(sync.auth_mode, "tenant")


class _FakeStore(object):
    """FeishuSync 构造只需要一个可传入的 store 对象。"""

    db_path = os.path.join(tempfile.gettempdir(), "growth-auth-fake.db")

    def list(self, entity, **kwargs):  # pragma: no cover - 用例不触发
        return []


if __name__ == "__main__":
    unittest.main(verbosity=2)
