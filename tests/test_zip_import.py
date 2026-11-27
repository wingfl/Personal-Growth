# -*- coding: utf-8 -*-
"""导入 .zip 压缩包的用例（飞书批量下载出来的就是 zip）。"""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.importers import extract_archive, import_path
from app.store import Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(ROOT, "schema", "schema.sql")

WEEKLY = """# 2024年第12周周报

## 本周完成
- 完成客户数据平台指标口径梳理，覆盖 12 个核心指标
"""

MONTHLY = """# 2024-03 工作月报

## 主要工作
负责指标口径模块，主导口径梳理与校验规则设计。
"""


def make_store(tmp):
    db_path = Store.init(os.path.join(tmp, "growth.db"), SCHEMA)
    return Store(db_path)


def write_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries:
            zf.writestr(name, content)


class ZipImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-zip-")
        self.store = make_store(self.tmp)

    def tearDown(self):
        try:
            self.store.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_import_zip_imports_supported_files_and_skips_noise(self):
        archive = os.path.join(self.tmp, "飞书导出.zip")
        write_zip(archive, [
            ("周报/2024年第12周周报.md", WEEKLY),
            ("月报/2024-03工作月报.md", MONTHLY),
            ("说明.pdf", "不支持的类型"),
            ("__MACOSX/._周报.md", "垃圾"),
            (".hidden.md", "隐藏文件"),
        ])
        result = import_path(self.store, archive, batch_label="飞书导出")
        self.assertEqual(result["status"], "batch")
        self.assertEqual(result["file_count"], 2)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["archive"], "飞书导出.zip")
        docs = self.store.list("source_document", order_by="title")
        titles = sorted(d["title"] for d in docs)
        self.assertEqual(titles, ["2024-03工作月报", "2024年第12周周报"])
        weekly = [d for d in docs if "周报" in d["title"]][0]
        self.assertEqual(weekly["doc_type"], "weekly_report")
        self.assertEqual(weekly["period_start"], "2024-03-18")
        self.assertEqual(weekly["period_end"], "2024-03-24")
        fragments = self.store.list("source_fragment", where={"document_id": weekly["id"]})
        self.assertTrue(fragments)
        # 片段偏移仍能在正文里原样取回
        for frag in fragments:
            self.assertEqual(weekly["raw_text"][frag["char_start"]:frag["char_end"]], frag["text"])
        batch = self.store.get("import_batch", result["batch_id"])
        self.assertEqual((batch["success_count"], batch["failed_count"]), (2, 0))

    def test_reimporting_same_zip_is_detected_as_duplicate(self):
        archive = os.path.join(self.tmp, "一次.zip")
        write_zip(archive, [("2024年第12周周报.md", WEEKLY)])
        first = import_path(self.store, archive)
        self.assertEqual(first["imported"], 1)
        second = import_path(self.store, archive)
        self.assertEqual(second["duplicate"], 1)
        self.assertEqual(self.store.count("source_document"), 1)

    def test_extract_archive_rejects_path_traversal(self):
        archive = os.path.join(self.tmp, "evil.zip")
        write_zip(archive, [("../跑出去.md", "# 越界")])
        dest = os.path.join(self.tmp, "out")
        os.makedirs(dest)
        with self.assertRaises(ValueError) as ctx:
            extract_archive(archive, dest)
        self.assertIn("越界", str(ctx.exception))

    def test_extract_archive_reports_empty_archive(self):
        archive = os.path.join(self.tmp, "空.zip")
        write_zip(archive, [("readme.pdf", "没有可导入的文件")])
        with self.assertRaises(ValueError) as ctx:
            extract_archive(archive, self.tmp)
        self.assertIn("没有可导入的文件", str(ctx.exception))

    def test_non_zip_file_is_rejected(self):
        path = os.path.join(self.tmp, "假的.zip")
        with open(path, "w", encoding="utf-8") as fp:
            fp.write("这不是压缩包")
        with self.assertRaises(ValueError) as ctx:
            extract_archive(path, self.tmp)
        self.assertIn("不是有效的 zip", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
