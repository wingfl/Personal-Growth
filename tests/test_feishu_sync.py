# -*- coding: utf-8 -*-
"""飞书资料同步的自检用例（离线，注入假 transport，不联网）。

运行：python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.feishu import FeishuClient, FeishuConfig, FeishuError
from app.feishu_import import FeishuSync, FeishuSyncError, normalize_wiki_node
from app.importers import import_text
from app.store import Store

WEEKLY_TITLE = "2024年第12周周报"
WEEKLY_TEXT = """# 本周工作

完成客户数据平台指标口径梳理，覆盖 12 个核心指标。

## 下周计划

- 推进口径评审
"""

MONTHLY_TITLE = "2024-03工作月报"

SPACE = {"space_id": "sp-1", "name": "我的文档库"}
NODES = [
    {"node_token": "n1", "obj_token": "doc-1", "obj_type": "docx", "title": WEEKLY_TITLE,
     "obj_edit_time": "1711000000", "has_child": False, "_space_name": "我的文档库"},
    {"node_token": "n2", "obj_token": "doc-2", "obj_type": "docx", "title": "架构设计说明",
     "obj_edit_time": "1711000000", "has_child": False, "_space_name": "我的文档库"},
    {"node_token": "n3", "obj_token": "bit-1", "obj_type": "bitable", "title": "周报看板",
     "obj_edit_time": "1711000000", "has_child": False, "_space_name": "我的文档库"},
]
TEXTS = {"doc-1": WEEKLY_TEXT, "doc-2": "系统分层说明。"}


class FakeFeishu(object):
    """按 URL 分派的假传输层，返回飞书风格的响应信封。"""

    def __init__(self, drive_error=None):
        self.calls = []
        self.drive_error = drive_error

    def __call__(self, method, url, headers, body, timeout):
        parsed = urllib.parse.urlparse(url)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        self.calls.append((method, path))
        if path.endswith("/tenant_access_token/internal"):
            return {"code": 0, "tenant_access_token": "t-1", "expire": 7200}
        if path == "/open-apis/wiki/v2/spaces":
            return {"code": 0, "data": {"items": [SPACE], "has_more": False}}
        if path.endswith("/nodes"):
            parent = (query.get("parent_node_token") or [None])[0]
            items = [] if parent else [dict(n) for n in NODES]
            return {"code": 0, "data": {"items": items, "has_more": False}}
        if path == "/open-apis/drive/v1/files":
            if self.drive_error:
                raise FeishuError(self.drive_error, code=99991672, status=400, path=path)
            return {"code": 0, "data": {"files": [], "has_more": False}}
        if "/raw_content" in path:
            token = path.split("/documents/")[1].split("/")[0]
            return {"code": 0, "data": {"content": TEXTS.get(token, "")}}
        raise AssertionError("未预期的请求：%s" % url)


def fake_client(drive_error=None):
    config = FeishuConfig(app_id="cli_test", app_secret="secret", key_source="test")
    return FeishuClient(config, transport=FakeFeishu(drive_error))


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-feishu-")
        self.db = os.path.join(self.tmp, "growth.db")
        Store.init(self.db)
        self.store = Store(self.db)
        self.client = fake_client()
        self.config = FeishuConfig(app_id="cli_test", app_secret="secret", key_source="test")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sync(self, **kwargs):
        kwargs.setdefault("config", self.config)
        kwargs.setdefault("client", self.client)
        return FeishuSync(self.store, **kwargs)


class ConfigCase(BaseCase):
    def test_missing_credentials_raises(self):
        empty = FeishuConfig()
        with self.assertRaises(FeishuSyncError):
            FeishuSync(self.store, config=empty, client=self.client)

    def test_check_reports_drive_permission_problem(self):
        sync = FeishuSync(self.store, config=self.config, client=fake_client(
            drive_error="Access denied. One of the following scopes is required: [drive:drive]"))
        report = sync.check()
        self.assertTrue(report["token_ok"])
        self.assertEqual(report["spaces"], 1)
        self.assertFalse(report["drive_ok"])
        self.assertTrue(any("云盘" in p for p in report["problems"]))

    def test_check_healthy(self):
        report = self.sync().check()
        self.assertTrue(report["token_ok"])
        self.assertTrue(report["drive_ok"])
        self.assertEqual(report["problems"], [])


class ScanCase(BaseCase):
    def test_scan_filters_by_keyword_and_flags_unsupported(self):
        nodes = self.sync().scan()
        titles = [n["title"] for n in nodes]
        self.assertEqual(titles, [WEEKLY_TITLE, "周报看板"])
        unsupported = [n for n in nodes if n["title"] == "周报看板"][0]
        self.assertIn("暂不支持", unsupported["note"])
        self.assertEqual(unsupported["obj_type"], "bitable")

    def test_scan_matches_custom_keywords(self):
        nodes = self.sync(keywords=("月报",)).scan()
        self.assertEqual(nodes, [])

    def test_normalize_wiki_node_builds_url(self):
        item = normalize_wiki_node(NODES[0])
        self.assertEqual(item["url"], "https://feishu.cn/wiki/n1")
        self.assertEqual(item["token"], "doc-1")
        self.assertTrue(item["updated_at"].endswith("Z"))


class PullCase(BaseCase):
    def test_pull_imports_document_with_external_fields(self):
        sync = self.sync()
        nodes = sync.scan()
        result = sync.pull(nodes)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["skipped"], 1)  # bitable 跳过
        self.assertEqual(result["failed"], 0)

        doc = self.store.find_one("source_document", external_id="doc-1")
        self.assertIsNotNone(doc)
        self.assertEqual(doc["source_channel"], "feishu")
        self.assertEqual(doc["doc_type"], "weekly_report")
        self.assertEqual(doc["external_url"], "https://feishu.cn/wiki/n1")
        self.assertTrue(doc["external_updated_at"].endswith("Z"))
        self.assertEqual(doc["period_start"], "2024-03-18")
        self.assertEqual(doc["period_end"], "2024-03-24")
        self.assertEqual(doc["origin"], "import")
        self.assertIn("本周工作", doc["raw_text"])

        fragments = self.store.list("source_fragment", {"document_id": doc["id"]})
        self.assertGreaterEqual(len(fragments), 3)
        for fragment in fragments:
            self.assertEqual(
                doc["raw_text"][fragment["char_start"]:fragment["char_end"]], fragment["text"])

        batch = self.store.get("import_batch", result["batch_id"])
        self.assertEqual(batch["source_channel"], "feishu")
        self.assertEqual(batch["success_count"], 1)
        self.assertEqual(batch["duplicate_count"], 0)
        self.assertEqual(batch["status"], "succeeded")

    def test_pull_twice_dedups_by_external_id(self):
        sync = self.sync()
        nodes = sync.scan()
        sync.pull(nodes)
        before = self.store.count("source_document")
        again = sync.pull(nodes)
        self.assertEqual(again["imported"], 0)
        self.assertEqual(again["duplicate"], 1)
        self.assertEqual(self.store.count("source_document"), before)
        batch = self.store.get("import_batch", again["batch_id"])
        self.assertEqual(batch["duplicate_count"], 1)

    def test_pull_new_version_keeps_previous_pointer(self):
        sync = self.sync()
        nodes = [n for n in sync.scan() if n["title"] == WEEKLY_TITLE]
        first = sync.pull(nodes)
        second = sync.pull(nodes, duplicate_handling="new_version")
        self.assertEqual(second["imported"], 1)
        docs = self.store.list("source_document", order_by="version_no")
        newest = [d for d in docs if d["external_id"] == "doc-1"][-1]
        self.assertEqual(newest["version_no"], 2)
        self.assertEqual(newest["duplicate_of_id"], first["results"][0]["document_id"])

    def test_pull_dry_run_writes_nothing(self):
        sync = self.sync()
        result = sync.pull(sync.scan(), dry_run=True)
        self.assertIsNone(result["batch_id"])
        self.assertEqual(self.store.count("source_document"), 0)
        self.assertEqual(result["results"][0]["status"], "dry_run")

    def test_pull_empty_nodes_reports_hint(self):
        with self.assertRaises(FeishuSyncError):
            self.sync().pull([])


class ImportTextCase(BaseCase):
    def test_import_text_infers_type_and_period_from_title(self):
        result = import_text(self.store, MONTHLY_TITLE, WEEKLY_TEXT,
                             source_channel="feishu", external_id="doc-9",
                             external_url="https://feishu.cn/docx/doc-9")
        self.store.commit()
        self.assertEqual(result["status"], "imported")
        self.assertEqual(result["doc_type"], "monthly_report")
        self.assertEqual(result["period_start"], "2024-03-01")
        self.assertEqual(result["period_end"], "2024-03-31")
        doc = self.store.get("source_document", result["document_id"])
        self.assertEqual(doc["external_id"], "doc-9")
        self.assertEqual(doc["word_count"], result["word_count"])

    def test_import_text_rejects_empty_body(self):
        with self.assertRaises(ValueError):
            import_text(self.store, "空文档", "   \n  ")


if __name__ == "__main__":
    unittest.main()
