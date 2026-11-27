# -*- coding: utf-8 -*-
"""把已有 SQLite 库补齐到当前 schema/model.json 的结构（只增不减）。

用途：模型新增字段后，让既有的 data/growth.db、data/demo.db 等无需重建即可继续用。
只做安全操作：
  - 给缺列的表 ALTER TABLE ... ADD COLUMN（新列必须可空或有默认值）；
  - 补建模型声明了 idx 但库里缺失的普通索引（命名与 build_model.py 生成的一致：
    idx_<实体>_<字段>）。
不会删除列、不会改类型、不会动数据。

用法：
    python tools/migrate_db.py data/growth.db [data/demo.db ...]
    python tools/migrate_db.py --all      # 自动处理 data/*.db
"""
import glob
import io
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SQL_TYPE = {
    "uuid": "TEXT",
    "string": "TEXT",
    "text": "TEXT",
    "longtext": "TEXT",
    "enum": "TEXT",
    "date": "TEXT",
    "datetime": "TEXT",
    "json": "TEXT",
    "ref": "TEXT",
    "file": "TEXT",
    "integer": "INTEGER",
    "decimal": "REAL",
    "boolean": "INTEGER",
}


def sql_literal(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'%s'" % str(value).replace("'", "''")


def migrate(db_path, model, dry_run=False):
    actions = []
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        for entity in model["entities"]:
            table = entity["id"]
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not row:
                actions.append("跳过不存在的表 %s" % table)
                continue
            have = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
            for field in entity.get("full_fields", []):
                name = field["n"]
                if name in have:
                    continue
                col_type = SQL_TYPE.get(field.get("t"), "TEXT")
                clause = "%s %s" % (name, col_type)
                default = field.get("def")
                if field.get("req") and default is None:
                    # SQLite 不允许给已有数据的表加 NOT NULL 且无默认值的列；
                    # 这类列在此处只按可空添加，由应用层校验兜底。
                    actions.append(
                        "警告：%s.%s 必填但无默认值，只能按可空列添加" % (table, name)
                    )
                elif field.get("req") and default is not None:
                    clause += " NOT NULL DEFAULT %s" % sql_literal(default)
                elif default is not None:
                    clause += " DEFAULT %s" % sql_literal(default)
                actions.append("ALTER TABLE %s ADD COLUMN %s" % (table, clause))
                if not dry_run:
                    conn.execute("ALTER TABLE %s ADD COLUMN %s" % (table, clause))

            # 索引
            have_idx = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,)
                )
            }
            for field in entity.get("full_fields", []):
                name = field["n"]
                if not field.get("idx"):
                    continue
                idx_name = "idx_%s_%s" % (table, name)
                if idx_name in have_idx:
                    continue
                sql = "CREATE INDEX IF NOT EXISTS %s ON %s(%s)" % (idx_name, table, name)
                actions.append(sql)
                if not dry_run:
                    conn.execute(sql)
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return actions


def main(argv):
    if not argv:
        sys.stderr.write(__doc__)
        return 2
    if argv == ["--all"]:
        paths = sorted(glob.glob(os.path.join(ROOT, "data", "*.db")))
    else:
        paths = argv
    model = json.load(io.open(os.path.join(ROOT, "schema", "model.json"), encoding="utf-8"))
    for path in paths:
        if not os.path.isfile(path):
            sys.stderr.write("找不到数据库：%s\n" % path)
            return 1
        actions = migrate(path, model)
        print("=== %s" % os.path.relpath(path, ROOT))
        if not actions:
            print("  已是最新，无需变更")
        for a in actions:
            print("  " + a)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
