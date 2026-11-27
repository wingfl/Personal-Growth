"""档案库整库导出 / 导入：一人一库，拷走一个 zip 即可换机器继续用。"""
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone

MANIFEST = "manifest.json"


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def export_db(db_path, out_path):
    """把 SQLite 库和一个清单打成一个 zip；返回文件大小。"""
    if not os.path.exists(db_path):
        raise SystemExit("找不到数据库：%s" % db_path)
    tmpdir = tempfile.mkdtemp(prefix="growth-export-")
    try:
        copy = os.path.join(tmpdir, "growth.db")
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(copy)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        counts = {}
        conn = sqlite3.connect(copy)
        try:
            for table in ("work_item", "project", "capability_evidence", "job_posting", "source_document"):
                try:
                    counts[table] = conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
                except sqlite3.Error:
                    counts[table] = None
        finally:
            conn.close()
        manifest = {
            "format": "growth-archive/1",
            "exported_at": _now(),
            "schema_note": "整库快照，含数据与配置；导入后无需账号",
            "counts": counts,
        }
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(copy, "growth.db")
            zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        return os.path.getsize(out_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def import_db(zip_path, db_path, force=False):
    """从 zip 还原整库；返回清单。"""
    if not os.path.exists(zip_path):
        raise SystemExit("找不到导出文件：%s" % zip_path)
    if os.path.exists(db_path) and not force:
        raise SystemExit("目标库已存在：%s（加 --force 覆盖）" % db_path)
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        if "growth.db" not in names:
            raise SystemExit("不是有效的档案导出包：缺少 growth.db")
        manifest = {}
        if MANIFEST in names:
            manifest = json.loads(zf.read(MANIFEST).decode("utf-8"))
        tmpdir = tempfile.mkdtemp(prefix="growth-import-")
        try:
            zf.extract("growth.db", tmpdir)
            restore = os.path.join(tmpdir, "growth.db")
            conn = sqlite3.connect(restore)
            try:
                ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                conn.close()
            if ok != "ok":
                raise SystemExit("导出包损坏：%s" % ok)
            os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
            if os.path.exists(db_path):
                os.remove(db_path)
            shutil.copy2(restore, db_path)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return manifest
