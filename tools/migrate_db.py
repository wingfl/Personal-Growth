# -*- coding: utf-8 -*-
"""把已有 SQLite 库补齐到当前 schema/model.json 的结构（只增不减）。

用途：模型新增字段后，让既有的 data/growth.db、data/demo.db 等无需重建即可继续用。
只做安全操作：
  - 缺表时按 schema/schema.sql 的 DDL 建表（模型新增实体后老库也能跟上）；
  - 给缺列的表 ALTER TABLE ... ADD COLUMN（新列必须可空或有默认值）；
  - 实体类型 CHECK 列表变了的表（audit_log / change_proposal / provenance_link /
    entity_relation 这类多态引用表）按「新建-复制-改名」重建，数据原样保留；
  - 补建模型声明了 idx 但库里缺失的普通索引（命名与 build_model.py 生成的一致：
    idx_<实体>_<字段>）。
不会删除列、不会改类型、不会丢数据。

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


def _schema_parts(path):
    """从 schema.sql 拆出建表语句与索引语句：表名 → [语句]。"""
    with io.open(path, encoding="utf-8") as fp:
        text = fp.read()
    tables, indexes = {}, {}
    for block in text.split(";\n"):
        stmt = block.strip()
        if not stmt or stmt.startswith("--"):
            continue
        upper = stmt.upper()
        if upper.startswith("CREATE TABLE "):
            name = stmt.split("CREATE TABLE ", 1)[1].split(" ", 1)[0].strip("`\"")
            tables[name] = stmt + ";"
        elif "CREATE INDEX" in upper and " ON " in upper:
            table = stmt.split(" ON ", 1)[1].split("(", 1)[0].strip("`\" ")
            indexes.setdefault(table, []).append(stmt + ";")
    return tables, indexes


def _norm(sql):
    """比较 DDL 时忽略空白、反引号与分号差异。"""
    return " ".join((sql or "").replace("`", "").replace('"', "").replace(";", "").split()).lower()


def _rebuild(conn, table, create_sql, index_sqls):
    """按 SQLite 官方 12 步的简化版重建一张表：新建-复制-删旧-改名。"""
    new = table + "__new"
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA legacy_alter_table=ON")
    conn.execute("DROP TABLE IF EXISTS %s" % new)
    body = create_sql.replace("CREATE TABLE %s (" % table,
                              "CREATE TABLE %s (" % new, 1)
    conn.execute(body)
    old_cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]
    new_cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % new)]
    cols = [c for c in old_cols if c in new_cols]
    collist = ", ".join(cols)
    conn.execute("INSERT INTO %s (%s) SELECT %s FROM %s" % (new, collist, collist, table))
    conn.execute("DROP TABLE %s" % table)
    conn.execute("ALTER TABLE %s RENAME TO %s" % (new, table))
    for sql in index_sqls:
        conn.execute(sql.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1))


def migrate(db_path, model, dry_run=False):
    actions = []
    conn = sqlite3.connect(db_path)
    schema_path = os.path.join(ROOT, "schema", "schema.sql")
    schema_tables, schema_indexes = _schema_parts(schema_path)
    try:
        # 重建多态引用表时会短暂 DROP 被引用表，整个过程关闭外键检查；
        # 数据是整表复制，提交前再打开。
        conn.execute("PRAGMA foreign_keys=OFF")
        for entity in model["entities"]:
            table = entity["id"]
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not row:
                create_sql = schema_tables.get(table)
                if not create_sql:
                    actions.append("跳过不存在的表 %s" % table)
                    continue
                actions.append("新建表 %s" % table)
                if not dry_run:
                    conn.execute(create_sql)
                    for sql in schema_indexes.get(table, []):
                        conn.execute(sql.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1))
                continue
            # 多态引用表的 CHECK 列表会随实体增减变化：结构不再一致时整表重建
            now_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            want_sql = schema_tables.get(table)
            if want_sql and _norm(now_sql) != _norm(want_sql):
                actions.append("重建表 %s（实体类型枚举变化）" % table)
                if not dry_run:
                    _rebuild(conn, table, want_sql, schema_indexes.get(table, []))
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
        # 触发器（只追加表的写保护）：直接复用生成好的 schema.sql，保证与全新库一致
        if os.path.isfile(schema_path):
            have_trg = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'")}
            for name, body in _schema_triggers(schema_path).items():
                table = name.replace("trg_", "").rsplit("_no_", 1)[0]
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                if name in have_trg or not exists:
                    continue
                actions.append("创建触发器 %s" % name)
                if not dry_run:
                    conn.execute(body)
        if not dry_run:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.commit()
    finally:
        conn.close()
    return actions


def _schema_triggers(path):
    """从 schema.sql 里取出 CREATE TRIGGER 语句（名字 → 完整语句）。"""
    with io.open(path, encoding="utf-8") as fp:
        text = fp.read()
    blocks = {}
    current = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("CREATE TRIGGER") or current:
            current.append(line)
            if stripped.upper() == "END;":
                body = "\n".join(current).strip()
                name = body.split("CREATE TRIGGER IF NOT EXISTS")[-1].split()[0] \
                    if "IF NOT EXISTS" in body else body.split("CREATE TRIGGER")[-1].split()[0]
                blocks[name] = body
                current = []
    return blocks


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
