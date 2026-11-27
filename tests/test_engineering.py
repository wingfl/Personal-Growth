# -*- coding: utf-8 -*-
"""工程规则用例：只追加表的写保护、事务边界、配置不被意外重置、中断作业清理。

这些对应架构审计（docs/架构设计.md §9）里发现的问题，属于回归防线。

运行：python -m unittest discover -s tests -v
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.extract import Extraction
from app.importers import import_file
from app.llm import LLMConfig, LLMClient, LLMReply
from app.model_meta import ModelError
from app.pathing import attachments_dir, is_inside, resolve_storage_ref, storage_ref
from app.store import Store

WEEKLY = """# 2024年第12周 工作周报

- 完成客户数据平台指标口径梳理，覆盖 12 个核心指标
"""


def fake_client(model="fake-model-1", base_url="http://fake.local/v1", api_key="test-key"):
    def transport(url, headers, payload, timeout):
        return {"model": model, "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
    config = LLMConfig(base_url=base_url, model=model, api_key=api_key, provider="fake",
                       key_source="explicit")
    return LLMClient(config=config, transport=transport)


class AppendOnlyCase(unittest.TestCase):
    """audit_log 只增不改不删：应用层与数据库层都要拦住。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-eng-")
        self.db = os.path.join(self.tmp, "growth.db")
        Store.init(self.db)
        self.store = Store(self.db)
        self.source = os.path.join(self.tmp, "weekly.md")
        with open(self.source, "w", encoding="utf-8") as fp:
            fp.write(WEEKLY)
        import_file(self.store, self.source)
        self.store.commit()
        self.audit_id = self.store.list("audit_log", limit=1)[0]["id"]

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_update_on_append_only_raises_domain_error(self):
        with self.assertRaises(ModelError) as ctx:
            self.store.update("audit_log", self.audit_id, {"remark": "改一下"})
        self.assertIn("只追加", str(ctx.exception))

    def test_soft_delete_on_append_only_raises_domain_error(self):
        with self.assertRaises(ModelError):
            self.store.soft_delete("audit_log", self.audit_id)

    def test_triggers_exist_in_fresh_database(self):
        conn = sqlite3.connect(self.db)
        try:
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'")}
        finally:
            conn.close()
        self.assertIn("trg_audit_log_no_update", names)
        self.assertIn("trg_audit_log_no_delete", names)

    def test_database_level_write_protection(self):
        conn = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE audit_log SET action='create' WHERE id=?", (self.audit_id,))
            conn.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM audit_log WHERE id=?", (self.audit_id,))
            conn.rollback()
        finally:
            conn.close()

    def test_normal_entities_are_still_mutable(self):
        doc = self.store.list("source_document", limit=1)[0]
        revision = self.store.update("source_document", doc["id"], {"summary": "一句话摘要"})
        self.assertGreater(revision, doc["revision"])

    def test_immutable_field_filled_once_then_locked(self):
        doc = self.store.list("source_document", limit=1)[0]
        self.store.update("source_document", doc["id"], {"summary": "第一次"})
        self.store.update("source_document", doc["id"], {"summary": "第二次"})   # summary 不是 imm
        raw = self.store.get("source_document", doc["id"])["raw_text"]
        with self.assertRaises(ModelError):
            self.store.update("source_document", doc["id"], {"raw_text": raw + "追加"})


class ConfigCase(unittest.TestCase):
    """run(model=...) 只换模型名，不重置 base_url 与凭据来源。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-eng-cfg-")
        self.db = os.path.join(self.tmp, "growth.db")
        Store.init(self.db)
        self.store = Store(self.db)
        self.source = os.path.join(self.tmp, "weekly.md")
        with open(self.source, "w", encoding="utf-8") as fp:
            fp.write(WEEKLY)
        self.doc_id = import_file(self.store, self.source)["document_id"]
        self.store.commit()
        self.client = fake_client()
        self.extraction = Extraction(self.store, llm=self.client)
        self.extraction.seed_config()

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dry_run_keeps_credentials_when_switching_model(self):
        result = self.extraction.run(self.doc_id, model="another-model", dry_run=True)
        self.assertTrue(result["dry_run"])
        config = self.extraction.llm.config
        self.assertEqual(config.model, "another-model")
        self.assertEqual(config.base_url, "http://fake.local/v1")
        self.assertEqual(config.api_key, "test-key")
        self.assertEqual(config.key_source, "explicit")

    def test_cleanup_marks_interrupted_jobs_failed(self):
        job_id = self.store.insert("ai_job", {
            "job_type": "document_extract", "trigger_type": "manual",
            "input_scope": '{"document_id": "%s"}' % self.doc_id, "status": "running",
        })
        self.store.commit()
        fixed = self.extraction.cleanup_stale_jobs(note="测试清理")
        self.assertIn(job_id, fixed)
        row = self.store.get("ai_job", job_id)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_code"], "unknown")
        self.assertEqual(row["error_message"], "测试清理")
        self.assertEqual(self.extraction.cleanup_stale_jobs(), [])   # 幂等

    def test_cleanup_leaves_finished_jobs_alone(self):
        job_id = self.store.insert("ai_job", {
            "job_type": "document_extract", "trigger_type": "manual",
            "input_scope": "{}", "status": "succeeded",
        })
        self.store.commit()
        self.extraction.cleanup_stale_jobs()
        self.assertEqual(self.store.get("ai_job", job_id)["status"], "succeeded")


class PathingCase(unittest.TestCase):
    """附件路径口径统一（架构审计第 6 条）：入库相对数据库目录，读取兼容历史写法。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-eng-path-")
        self.db = os.path.join(self.tmp, "sub", "growth.db")
        os.makedirs(os.path.dirname(self.db))
        self.att = attachments_dir(self.db)
        os.makedirs(self.att)
        self.file = os.path.join(self.att, "abc123_周报.md")
        with open(self.file, "w", encoding="utf-8") as fp:
            fp.write("正文")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_storage_ref_is_relative_to_database(self):
        ref = storage_ref(self.db, self.file)
        self.assertEqual(ref, "attachments/abc123_周报.md")
        self.assertFalse(os.path.isabs(ref))

    def test_resolve_round_trip(self):
        ref = storage_ref(self.db, self.file)
        self.assertEqual(os.path.abspath(resolve_storage_ref(self.db, ref)),
                         os.path.abspath(self.file))

    def test_resolve_accepts_absolute_and_legacy_workspace_relative(self):
        absolute = self.file.replace("\\", "/")
        self.assertEqual(os.path.abspath(resolve_storage_ref(self.db, absolute)),
                         os.path.abspath(self.file))
        legacy = os.path.join("data", "attachments", "abc123_周报.md")   # 历史写法
        resolved = resolve_storage_ref(self.db, legacy)
        self.assertTrue(resolved.endswith(os.path.join("data", "attachments", "abc123_周报.md")))

    def test_attachments_dir_follows_database(self):
        self.assertEqual(os.path.abspath(attachments_dir(self.db)),
                         os.path.abspath(os.path.join(self.tmp, "sub", "attachments")))
        self.assertTrue(is_inside(self.file, attachments_dir(self.db)))


class TransactionCase(unittest.TestCase):
    """confirm 与同批次外键回填必须在一个事务里提交。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-eng-tx-")
        self.db = os.path.join(self.tmp, "growth.db")
        Store.init(self.db)
        self.store = Store(self.db)
        self.source = os.path.join(self.tmp, "weekly.md")
        with open(self.source, "w", encoding="utf-8") as fp:
            fp.write(WEEKLY)
        self.doc_id = import_file(self.store, self.source)["document_id"]
        self.store.commit()
        self.client = fake_client()
        self.extraction = Extraction(self.store, llm=self.client)
        self.extraction.seed_config()
        from app.extract import Review
        self.review = Review(self.store, extraction=self.extraction)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_confirm_commits_once(self):
        reply = {
            "new_projects": [{"name": "客户数据平台建设",
                              "reason": "周报里出现，本批次新建"}],
            "items": [{"title": "指标口径梳理", "item_type": "requirement_analysis",
                       "content": "梳理指标口径", "project": "客户数据平台建设",
                       "evidence": [{"fragment_id": None, "quote": "完成客户数据平台指标口径梳理"}]}],
        }
        fragments = self.store.list("source_fragment", {"document_id": self.doc_id}, limit=10)
        reply["items"][0]["evidence"][0]["fragment_id"] = fragments[0]["id"]

        def transport(url, headers, payload, timeout):
            import json as _json
            return {"model": "fake", "choices": [{"message": {"content": _json.dumps(reply)},
                                                  "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        self.extraction.llm.transport = transport
        job = self.extraction.run(self.doc_id, max_fragments=3)
        pending = self.review.list(status="pending")
        self.assertGreaterEqual(len(pending), 2)

        project_proposal = next(p for p in pending if p["target_entity_type"] == "project")
        calls = {"n": 0}
        original = self.store.commit

        def counting_commit():
            calls["n"] += 1
            return original()

        self.store.commit = counting_commit
        try:
            result = self.review.confirm(project_proposal["id"])
        finally:
            self.store.commit = original
        self.assertEqual(calls["n"], 1, "confirm 应当只提交一次事务")
        self.assertTrue(result["applied_entity_id"])
        self.assertEqual(len(result["relinked"]), 1, "同批次事项建议应回填外键")
        self.assertLessEqual(job.get("proposal_count", 0), len(pending) + 1)


if __name__ == "__main__":
    unittest.main()
