# -*- coding: utf-8 -*-
"""备份、校验与日志的基础设施用例（离线，不联网、不触发外部副作用）。

运行：python -m unittest discover -s tests -v
"""
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.archive import Archive
from app.backup import (BackupError, _check_columns, create_backup,
                        verify_backup_file, verify_database)
from app.importers import import_file
from app.logging import DEFAULT_LOG_DIR, get_logger, setup_logging
from app.store import Store

WEEKLY = """# 2024年第12周 工作周报

- 完成客户数据平台指标口径梳理，覆盖 12 个核心指标
"""


class BackupCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-backup-")
        self.db = os.path.join(self.tmp, "growth.db")
        Store.init(self.db)
        self.store = Store(self.db)
        self.source = os.path.join(self.tmp, "weekly.md")
        with open(self.source, "w", encoding="utf-8") as fp:
            fp.write(WEEKLY)
        import_file(self.store, self.source)
        self.store.commit()

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- create ---------------------------------------------------
    def test_create_backup_writes_file_and_record(self):
        out = os.path.join(self.tmp, "out")
        report = create_backup(self.store, out_dir=out, label="单元")
        path = report["path"]
        self.assertTrue(os.path.exists(path))
        self.assertIn("单元", os.path.basename(path))
        self.assertEqual(report["format"], "sqlite3")
        self.assertGreater(report["size_bytes"], 0)
        self.assertEqual(len(report["checksum"]), 64)
        self.assertTrue(report["verification"]["ok"], report["verification"]["problems"])
        self.assertGreaterEqual(report["record_count"], 4)  # 资料 + 片段 + 附件 + 审计

        rows = self.store.query(
            "SELECT * FROM backup_record WHERE operation_type='backup' AND deleted_at IS NULL")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(row["id"], report["backup_record_id"])
        self.assertEqual(row["record_count"], report["record_count"])
        scope = json.loads(row["scope"])
        self.assertIsInstance(scope, dict)
        self.assertIn("db_path", scope)
        self.assertEqual(scope["attachment_files"], 1)

    def test_backup_copies_attachments_next_to_backup(self):
        report = create_backup(self.store, out_dir=os.path.join(self.tmp, "out"))
        copied = report["attachments"]
        self.assertEqual(copied["files"], 1)
        files = os.listdir(copied["path"])
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith("weekly.md"))

    def test_backup_without_attachments(self):
        report = create_backup(self.store, out_dir=os.path.join(self.tmp, "out"),
                               include_attachments=False)
        self.assertIsNone(report["attachments"])
        self.assertEqual([n for n in os.listdir(os.path.join(self.tmp, "out"))
                          if n.startswith("attachments")], [])

    def test_two_backups_make_two_records(self):
        create_backup(self.store, out_dir=os.path.join(self.tmp, "out"), label="一")
        time.sleep(1)                                 # 时间戳精确到秒
        create_backup(self.store, out_dir=os.path.join(self.tmp, "out"), label="二")
        rows = self.store.query(
            "SELECT * FROM backup_record WHERE operation_type='backup' AND deleted_at IS NULL")
        self.assertEqual(len(rows), 2)
        names = sorted(n for n in os.listdir(os.path.join(self.tmp, "out")) if n.endswith(".db"))
        self.assertEqual(len(names), 2)

    def test_backup_does_not_modify_source_database(self):
        before = self.store.count("source_document")
        create_backup(self.store, out_dir=os.path.join(self.tmp, "out"))
        self.assertEqual(self.store.count("source_document"), before)
        self.assertTrue(verify_database(self.db)["ok"])

    # ---- verify ---------------------------------------------------
    def test_verify_database_reports_tables_and_rows(self):
        report = verify_database(self.db)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["tables"], 44)
        self.assertGreater(report["rows"], 0)

    def test_verify_backup_file_returns_checksum_and_size(self):
        report = create_backup(self.store, out_dir=os.path.join(self.tmp, "out"))
        verified = verify_backup_file(report["path"])
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["checksum"], report["checksum"])
        self.assertEqual(verified["size_bytes"], os.path.getsize(report["path"]))

    def test_verify_rejects_non_database_file(self):
        bad = os.path.join(self.tmp, "bad.db")
        with open(bad, "w", encoding="utf-8") as fp:
            fp.write("这不是数据库")
        report = verify_backup_file(bad)
        self.assertFalse(report["ok"])
        self.assertTrue(any("不是有效的 SQLite 数据库" in p for p in report["problems"]),
                        report["problems"])

    def test_verify_rejects_missing_file(self):
        report = verify_database(os.path.join(self.tmp, "nothing.db"))
        self.assertFalse(report["ok"])
        self.assertTrue(report["problems"])

    def test_check_columns_detects_outdated_schema(self):
        old = os.path.join(self.tmp, "old.db")
        conn = sqlite3.connect(old)
        conn.execute("CREATE TABLE project (id TEXT PRIMARY KEY, name TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE source_document (id TEXT PRIMARY KEY, title TEXT)")
        conn.commit()
        conn.close()
        problems = _check_columns(old)
        self.assertTrue(problems, "旧库应当被检出缺列")
        self.assertTrue(any("project" in p for p in problems), problems)

    def test_check_columns_accepts_current_schema(self):
        self.assertEqual(_check_columns(self.db), [])

    # ---- 记录与恢复线索 -------------------------------------------
    def test_backup_record_keeps_entity_counts(self):
        report = create_backup(self.store, out_dir=os.path.join(self.tmp, "out"))
        row = self.store.get("backup_record", report["backup_record_id"])
        # json 字段在库里是文本（Store 保持原始行语义），校验时显式解码
        counts = json.loads(row["entity_counts"])
        self.assertIsInstance(counts, dict)
        self.assertEqual(counts.get("source_document"), 1)
        self.assertGreaterEqual(counts.get("audit_log", 0), 1)
        self.assertEqual(report["entity_counts"]["source_document"], 1)
        self.assertIsInstance(row["restore_verification"], (dict, str, type(None)))

    def test_backup_scope_records_note_and_db_path(self):
        report = create_backup(self.store, out_dir=os.path.join(self.tmp, "out"),
                               label="演练", note="上线前")
        row = self.store.get("backup_record", report["backup_record_id"])
        scope = json.loads(row["scope"])
        self.assertEqual(scope["note"], "上线前")
        self.assertIn("attachment", json.dumps(scope, ensure_ascii=False))
        self.assertTrue(row["checksum"])

    def test_backup_file_path_is_relative_or_absolute_but_existing(self):
        report = create_backup(self.store, out_dir=os.path.join(self.tmp, "out"))
        row = self.store.get("backup_record", report["backup_record_id"])
        stored = row["file_path"]
        self.assertTrue(os.path.isabs(stored) or not os.path.isabs(stored))
        resolved = stored if os.path.isabs(stored) else os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), stored)
        self.assertTrue(os.path.exists(resolved), resolved)

    def test_create_backup_creates_output_dir(self):
        out = os.path.join(self.tmp, "a", "b", "c")
        report = create_backup(self.store, out_dir=out)
        self.assertTrue(os.path.isdir(out))
        self.assertTrue(os.path.exists(report["path"]))

    def test_created_backup_is_openable_by_store(self):
        report = create_backup(self.store, out_dir=os.path.join(self.tmp, "out"))
        copy = Store(report["path"])
        try:
            self.assertEqual(copy.count("source_document"), 1)
            # 样例正文只有一个标题 + 一个列表项 = 2 个片段
            self.assertEqual(len(copy.list("source_fragment")), 2)
        finally:
            copy.close()


class LoggingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-log-")

    def tearDown(self):
        logger = logging.getLogger("growth")
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_setup_logging_writes_file(self):
        setup_logging(log_dir=self.tmp, force=True)
        get_logger("unit").info("hello 日志")
        for handler in logging.getLogger("growth").handlers:
            handler.flush()
        path = os.path.join(self.tmp, "app.log")
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as fp:
            self.assertIn("hello 日志", fp.read())

    def test_setup_logging_is_idempotent(self):
        setup_logging(log_dir=self.tmp, force=True)
        count = len(logging.getLogger("growth").handlers)
        setup_logging(log_dir=self.tmp)          # 第二次不应重复挂 handler
        self.assertEqual(len(logging.getLogger("growth").handlers), count)

    def test_get_logger_uses_package_prefix(self):
        self.assertEqual(get_logger("cli").name, "growth.cli")
        self.assertEqual(get_logger("growth.cli").name, "growth.cli")
        self.assertEqual(get_logger().name, "growth")

    def test_default_log_dir_inside_project(self):
        self.assertTrue(DEFAULT_LOG_DIR.endswith(os.path.join("data", "logs")))

    def test_unwritable_dir_falls_back_without_crashing(self):
        bogus = os.path.join(self.tmp, "file-not-dir")
        with open(bogus, "w", encoding="utf-8") as fp:
            fp.write("x")
        setup_logging(log_dir=os.path.join(bogus, "logs"), force=True)   # 不应抛异常
        self.assertTrue(logging.getLogger("growth").handlers)


if __name__ == "__main__":
    unittest.main()
