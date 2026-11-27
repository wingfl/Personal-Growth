# -*- coding: utf-8 -*-
"""第 1-2 步（建库 + 原始资料导入）的自检用例。

运行：python -m unittest discover -s tests -v
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.importers import import_file, import_path, infer_doc_type, infer_period, parse_file
from app.model_meta import Model, ModelError
from app.pathing import resolve_storage_ref, storage_ref
from app.store import Conflict, Store

SAMPLE_MD = """# 2024年3月 工作月报

## 一、项目进展

参与客户数据平台建设，负责指标口径梳理。

- 完成 12 个指标口径梳理
- 输出口径说明文档 1 份

## 二、下月计划

推进数据质量校验规则落地。

> 说明：本月数据以系统导出的口径清单为准。
"""


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-test-")
        self.db = os.path.join(self.tmp, "growth.db")
        Store.init(self.db)
        self.store = Store(self.db)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(text)
        return path


class TestSchema(BaseCase):
    def test_tables_created(self):
        names = {r["name"] for r in self.store.query(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(len(self.store.model.entities), 44)
        self.assertTrue(set(self.store.model.entities) <= names)

    def test_required_not_null_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute("INSERT INTO source_document (id) VALUES ('x')")

    def test_entity_type_check_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.conn.execute(
                "INSERT INTO audit_log (id, entity_type, entity_id, action, actor_type, occurred_at, created_at)"
                " VALUES ('a', 'not_an_entity', 'b', 'create', 'user', '2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')")


class TestValidation(BaseCase):
    def test_unknown_field_rejected(self):
        with self.assertRaises(ModelError):
            self.store.insert("source_document", {"title": "x", "doc_type": "other",
                                                  "source_channel": "manual_input",
                                                  "raw_text": "x", "origin": "user",
                                                  "no_such_field": 1})

    def test_enum_and_required_checked(self):
        with self.assertRaises(ModelError):
            self.store.insert("source_document", {"title": "x", "doc_type": "不存在",
                                                  "source_channel": "manual_input",
                                                  "raw_text": "x", "origin": "user"})
        with self.assertRaises(ModelError):
            self.store.insert("source_document", {"doc_type": "other",
                                                  "source_channel": "manual_input",
                                                  "raw_text": "x", "origin": "user"})

    def test_immutable_field_rejected_on_update(self):
        doc_id = self.store.insert("source_document", {
            "title": "t", "doc_type": "work_log", "source_channel": "manual_input",
            "raw_text": "原文", "origin": "user"})
        with self.assertRaises(ModelError):
            self.store.update("source_document", doc_id, {"raw_text": "改一下"})

    def test_optimistic_lock(self):
        doc_id = self.store.insert("source_document", {
            "title": "t", "doc_type": "work_log", "source_channel": "manual_input",
            "raw_text": "原文", "origin": "user"})
        revision = self.store.get("source_document", doc_id)["revision"]
        self.store.update("source_document", doc_id, {"summary": "摘要"},
                          expected_revision=revision)
        with self.assertRaises(Conflict):
            self.store.update("source_document", doc_id, {"summary": "再改"},
                              expected_revision=revision)


class TestParsing(BaseCase):
    def test_markdown_blocks_and_offsets(self):
        path = self.write("2024-03月报.md", SAMPLE_MD)
        text, blocks, meta = parse_file(path)
        types = [b["fragment_type"] for b in blocks]
        self.assertEqual(types[0], "heading")
        self.assertIn("list_item", types)
        self.assertIn("quote", types)
        for block in blocks:
            self.assertEqual(text[block["char_start"]:block["char_end"]], block["text"])
        self.assertGreater(meta["word_count"], 20)
        self.assertEqual(meta["language"], "zh-CN")
        self.assertEqual(blocks[2]["heading_path"], "2024年3月 工作月报 / 一、项目进展")

    def test_docx_blocks(self):
        from docx import Document
        doc = Document()
        doc.add_heading("项目复盘", level=1)
        doc.add_paragraph("背景：客户数据平台指标口径不统一。")
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "指标"
        table.cell(0, 1).text = "口径"
        table.cell(1, 0).text = "活跃用户"
        table.cell(1, 1).text = "30 天内有登录"
        path = os.path.join(self.tmp, "复盘.docx")
        doc.save(path)

        text, blocks, _meta = parse_file(path)
        types = [b["fragment_type"] for b in blocks]
        self.assertEqual(types[0], "heading")
        self.assertIn("table_row", types)
        for block in blocks:
            self.assertEqual(text[block["char_start"]:block["char_end"]], block["text"])


class TestImport(BaseCase):
    def test_import_md(self):
        path = self.write("2024-03月报.md", SAMPLE_MD)
        result = import_file(self.store, path)
        self.store.commit()
        self.assertEqual(result["status"], "imported")
        self.assertEqual(result["doc_type"], "monthly_report")
        self.assertEqual(result["period_start"], "2024-03-01")
        self.assertEqual(result["period_end"], "2024-03-31")

        doc = self.store.get("source_document", result["document_id"])
        self.assertEqual(doc["origin"], "import")
        self.assertEqual(doc["processing_status"], "extracted")
        self.assertIsNotNone(doc["attachment_id"])
        self.assertEqual(self.store.count("attachment"), 1)
        self.assertEqual(self.store.count("source_fragment",
                                          {"document_id": doc["id"]}), result["fragment_count"])

        attachment = self.store.get("attachment", doc["attachment_id"])
        self.assertEqual(attachment["owner_type"], "source_document")
        stored = resolve_storage_ref(self.store.db_path, attachment["storage_path"])
        self.assertTrue(os.path.exists(stored), "附件副本应已落盘：%s" % stored)
        self.assertEqual(attachment["content_hash"], doc["content_hash"])

    def test_duplicate_skip_and_new_version(self):
        path = self.write("周报.md", SAMPLE_MD)
        first = import_file(self.store, path)
        second = import_file(self.store, path)
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(second["document_id"], first["document_id"])

        third = import_file(self.store, path, duplicate_handling="new_version")
        self.assertEqual(third["status"], "imported")
        self.assertEqual(third["version_no"], 2)
        doc = self.store.get("source_document", third["document_id"])
        self.assertEqual(doc["duplicate_of_id"], first["document_id"])
        self.assertEqual(doc["duplicate_handling"], "new_version")

    def test_import_directory_creates_batch(self):
        self.write("2024-01月报.md", SAMPLE_MD)
        self.write("2024-02月报.md", SAMPLE_MD.replace("3月", "2月"))
        self.write("ignore.pdf", "%PDF-1.4")
        result = import_path(self.store, self.tmp)
        self.store.commit()
        self.assertEqual(result["file_count"], 2)
        self.assertEqual(result["imported"], 2)
        batch = self.store.get("import_batch", result["batch_id"])
        self.assertEqual(batch["status"], "succeeded")
        self.assertEqual(batch["file_count"], 2)

    def test_audit_trail_written(self):
        path = self.write("2024-03月报.md", SAMPLE_MD)
        result = import_file(self.store, path)
        self.store.commit()
        rows = self.store.history("source_document", result["document_id"])
        actions = sorted(r["action"] for r in rows)
        self.assertIn("create", actions)
        self.assertIn("update", actions)
        self.assertTrue(all(r["actor_type"] == "user" for r in rows))

    def test_fragments_point_back_to_raw_text(self):
        path = self.write("2024-03月报.md", SAMPLE_MD)
        result = import_file(self.store, path)
        self.store.commit()
        doc = self.store.get("source_document", result["document_id"])
        rows = self.store.list("source_fragment", {"document_id": doc["id"]},
                              limit=1000, order_by="order_index ASC")
        self.assertGreater(len(rows), 3)
        for row in rows:
            self.assertEqual(doc["raw_text"][row["char_start"]:row["char_end"]], row["text"])


class TestInference(unittest.TestCase):
    def test_infer_doc_type(self):
        self.assertEqual(infer_doc_type("2024-03工作月报.md"), "monthly_report")
        self.assertEqual(infer_doc_type("第12周周报.docx"), "weekly_report")
        self.assertEqual(infer_doc_type("需求说明书.md"), "requirement_doc")
        self.assertEqual(infer_doc_type("随手记.md"), "personal_note")
        self.assertEqual(infer_doc_type("未命名文档.md"), "other")

    def test_infer_period(self):
        self.assertEqual(infer_period("2024-03月报.md")[:2], ("2024-03-01", "2024-03-31"))
        self.assertEqual(infer_period("2024Q2总结.md")[:2], ("2024-04-01", "2024-06-30"))
        self.assertEqual(infer_period("2023年度总结.md")[:2], ("2023-01-01", "2023-12-31"))
        self.assertEqual(infer_period("无日期.md")[:2], (None, None))
        start, end, precision = infer_period("2024年第5周周报.md")
        self.assertEqual(precision, "week")
        self.assertEqual(start, "2024-01-29")
        self.assertEqual(end, "2024-02-04")


if __name__ == "__main__":
    unittest.main(verbosity=2)
