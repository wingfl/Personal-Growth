# -*- coding: utf-8 -*-
"""备份、校验与备份记录（需求 1.4⑧「正式数据支持导出和迁移」，第 7 章第 10 步的前置能力）。

做法：

- 用 SQLite 官方推荐的 `VACUUM INTO` 做**热备份**：不需要停写、自动处理 WAL，
  产出一个自洽的单文件库（比直接拷 .db 安全）。
- 附件按目录整体拷贝（附件与数据库成对才有意义，见 docs/部署与运维.md）。
- 每次备份都在 `backup_record` 里留一条记录：路径、大小、校验和、各实体条数、
  耗时、校验结果。这样「上次备份是什么时候、能不能用」是可查的。
- 备份产物本身**不含**这条记录（先备份后记账），恢复后可以用 `backup verify` 复核。

恢复不做自动化：覆盖数据库文件是破坏性操作，交给使用者按文档手动执行
（docs/部署与运维.md 第 6 节），这里只提供校验工具。
"""
import hashlib
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone

from .logging import get_logger
from .pathing import attachments_dir as _attachments_dir

log = get_logger("backup")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BACKUP_DIR = os.path.join(ROOT, "backup")
VERIFY_SAMPLE_ROWS = 3


class BackupError(Exception):
    """备份或校验无法继续（例如目标文件不可写、来源库不存在）。"""


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def sha256_file(path, chunk=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            block = fp.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def attachments_dir(db_path):
    """附件目录跟着数据库走（口径见 app/pathing.py）。"""
    return _attachments_dir(db_path)


def _entity_counts(db_path, entities):
    counts = {}
    conn = sqlite3.connect(db_path)
    try:
        for entity in entities:
            try:
                counts[entity] = conn.execute("SELECT count(*) FROM %s" % entity).fetchone()[0]
            except sqlite3.Error:
                counts[entity] = 0
    finally:
        conn.close()
    return counts


def _dir_size(path):
    total = 0
    files = 0
    for current, _dirs, names in os.walk(path):
        for name in names:
            full = os.path.join(current, name)
            if os.path.isfile(full):
                total += os.path.getsize(full)
                files += 1
    return files, total


def create_backup(store, out_dir=None, include_attachments=True, label=None, note=None):
    """做一次备份并记录 backup_record，返回报告 dict。"""
    source = os.path.abspath(store.db_path)
    if not os.path.exists(source):
        raise BackupError("数据库不存在：%s" % source)
    out_dir = os.path.abspath(out_dir or DEFAULT_BACKUP_DIR)
    os.makedirs(out_dir, exist_ok=True)

    stamp = _timestamp()
    stem = os.path.splitext(os.path.basename(source))[0]
    suffix = ("-" + label) if label else ""
    target = os.path.join(out_dir, "%s-%s%s.db" % (stem, stamp, suffix))
    if os.path.exists(target):
        raise BackupError("备份文件已存在：%s" % target)

    entities = _entity_ids_from_model(store.model)
    started = time.time()
    log.info("开始备份 %s → %s", source, target)

    conn = sqlite3.connect(source)
    try:
        conn.execute("VACUUM INTO ?", (target,))
    except sqlite3.Error as exc:
        raise BackupError("VACUUM INTO 失败：%s" % exc)
    finally:
        conn.close()

    verification = verify_database(target, entities)
    if not verification["ok"]:
        raise BackupError("备份产物自检未通过：%s" % "；".join(verification["problems"]))

    counts = _entity_counts(target, entities)
    record_count = sum(counts.values())
    size_bytes = os.path.getsize(target)
    checksum = sha256_file(target)

    scope = {
        "db_path": source,
        "include_attachments": bool(include_attachments),
        "entities": len(entities),
        "note": note or "",
    }
    attachment_report = None
    source_attachments = attachments_dir(source)
    if include_attachments and os.path.isdir(source_attachments):
        target_attachments = os.path.join(out_dir, "attachments-%s%s" % (stamp, suffix))
        shutil.copytree(source_attachments, target_attachments)
        files, total = _dir_size(target_attachments)
        attachment_report = {"path": target_attachments, "files": files, "bytes": total}
        scope["attachment_files"] = files
        scope["attachment_bytes"] = total
    elif include_attachments:
        scope["attachment_files"] = 0

    duration_ms = int((time.time() - started) * 1000)
    record = store.insert("backup_record", {
        "operation_type": "backup",
        "scope": scope,
        "format": "sqlite3",
        "file_path": os.path.relpath(target, ROOT).replace("\\", "/")
        if _same_drive(target, ROOT) else target,
        "checksum": checksum,
        "status": "succeeded",
        "started_at": _utc_now(),
        "finished_at": _utc_now(),
        "record_count": record_count,
        "size_bytes": size_bytes,
        "duration_ms": duration_ms,
        "entity_counts": counts,
        "restore_verification": verification,
    }, remark="备份 %s" % os.path.basename(target))
    store.commit()

    report = {
        "path": target,
        "format": "sqlite3",
        "checksum": checksum,
        "size_bytes": size_bytes,
        "record_count": record_count,
        "entity_counts": counts,
        "duration_ms": duration_ms,
        "verification": verification,
        "attachments": attachment_report,
        "backup_record_id": record,
    }
    log.info("备份完成 %s（%d 条记录，%.1f KB，%d ms）",
             target, record_count, size_bytes / 1024.0, duration_ms)
    return report


def _same_drive(a, b):
    try:
        os.path.relpath(a, b)
        return True
    except ValueError:
        return False


def verify_database(path, entities=None):
    """校验一个 SQLite 库：完整性、必需表与列、可读性。返回报告 dict。"""
    problems = []
    report = {"path": path, "ok": False, "problems": problems, "tables": 0, "rows": 0}
    if not os.path.exists(path):
        problems.append("文件不存在")
        return report
    if entities is None:
        entities = _model_entity_ids()
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    except sqlite3.Error as exc:
        problems.append("无法打开：%s" % exc)
        return report
    try:
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            problems.append("不是有效的 SQLite 数据库：%s" % exc)
            return report
        if not integrity or integrity[0] != "ok":
            problems.append("integrity_check 未通过：%s" % (integrity[0] if integrity else "无返回"))
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        report["tables"] = len(tables)
        missing = sorted(set(entities) - tables)
        if missing:
            problems.append("缺少表：%s" % "、".join(missing[:8]))
        rows = 0
        for entity in entities:
            if entity not in tables:
                continue
            try:
                rows += conn.execute("SELECT count(*) FROM %s" % entity).fetchone()[0]
                conn.execute("SELECT * FROM %s LIMIT %d" % (entity, VERIFY_SAMPLE_ROWS)).fetchall()
            except sqlite3.Error as exc:
                problems.append("读取 %s 失败：%s" % (entity, exc))
        report["rows"] = rows
    finally:
        conn.close()
    report["ok"] = not problems
    return report


def _entity_ids_from_model(model):
    """从 Model 实例或 model.json 的 dict 里取实体 id 列表（两种形态都支持）。"""
    entities = model["entities"] if isinstance(model, dict) else model.entities
    if isinstance(entities, dict):
        return list(entities.keys())
    return [entity["id"] for entity in entities]


def _model_entity_ids():
    """从 schema/model.json 读实体清单（避免为了校验再建一个连接）。"""
    path = os.path.join(ROOT, "schema", "model.json")
    with open(path, encoding="utf-8") as fp:
        model = json.load(fp)
    return [entity["id"] for entity in model["entities"]]


def verify_backup_file(path):
    """CLI 用的校验入口：在 verify_database 之上补校验和与字段完整性。"""
    report = verify_database(path)
    report["size_bytes"] = os.path.getsize(path) if os.path.exists(path) else 0
    report["checksum"] = sha256_file(path) if os.path.exists(path) else None
    if report["ok"]:
        schema_problems = _check_columns(path)
        report["problems"].extend(schema_problems)
        report["ok"] = not report["problems"]
    log.info("校验备份 %s：%s", path, "通过" if report["ok"] else "未通过")
    return report


def _check_columns(path):
    """对照模型检查列是否齐全（库比模型旧时应先跑 migrate_db.py）。"""
    problems = []
    with open(os.path.join(ROOT, "schema", "model.json"), encoding="utf-8") as fp:
        model = json.load(fp)
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    try:
        for entity in model["entities"]:
            table = entity["id"]
            try:
                have = {row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)}
            except sqlite3.Error as exc:
                problems.append("读取 %s 结构失败：%s" % (table, exc))
                continue
            if not have:
                continue
            missing = [field["n"] for field in entity.get("full_fields", [])
                       if field["n"] not in have]
            if missing:
                problems.append("%s 缺列：%s" % (table, "、".join(missing[:6])))
    finally:
        conn.close()
    return problems
