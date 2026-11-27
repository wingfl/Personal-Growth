# -*- coding: utf-8 -*-
"""构建个人成长档案系统的数据模型交付物。

输入：
  schema/model.core.json    骨架（分层 / 通用字段组 / 枚举 / 实体登记 / 覆盖矩阵）
  schema/parts/*.entities.json  各层补全的业务字段（子代理产出）
  schema/rules.json         校验规则（数据驱动，可被 DDL 与文档复用）
  docs/数据模型设计.template.md  手写叙述 + {{GEN:*}} 占位符

输出：
  schema/model.json                        合并并规范化后的完整模型（唯一事实来源）
  docs/个人成长档案系统-数据模型设计 V1.0.md  完整交付文档
  schema/schema.sql                        参考 DDL（SQLite 语法，兼容 PostgreSQL 大部分写法）

用法：python tools/build_model.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_DIR = os.path.join(ROOT, "schema")
PARTS_DIR = os.path.join(SCHEMA_DIR, "parts")
DOCS_DIR = os.path.join(ROOT, "docs")

SQL_TYPE = {
    "uuid": "TEXT",
    "string": "TEXT",
    "text": "TEXT",
    "longtext": "TEXT",
    "enum": "TEXT",
    "date": "TEXT",
    "datetime": "TEXT",
    "integer": "INTEGER",
    "decimal": "REAL",
    "boolean": "INTEGER",
    "json": "TEXT",
    "ref": "TEXT",
    "file": "TEXT",
}

# 生成 DDL 时不再重复建表的纯关联表（仍会在模型中保留）
LINK_TABLES = None  # 由实体定义推导，不硬编码

LAYER_ORDER = ["00_base", "01_source", "02_experience", "03_achievement", "04_portrait", "05_growth", "06_ai"]


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def merge_model():
    core = load_json(os.path.join(SCHEMA_DIR, "model.core.json"))
    by_id = {e["id"]: e for e in core["entities"]}
    extra_enums = {}
    parts = []
    if os.path.isdir(PARTS_DIR):
        for name in sorted(os.listdir(PARTS_DIR)):
            if not name.endswith(".entities.json"):
                continue
            parts.append(name)
            part = load_json(os.path.join(PARTS_DIR, name))
            extra_enums.update(part.get("enums", {}))
            for ent in part.get("entities", []):
                eid = ent["id"]
                if eid not in by_id:
                    core["entities"].append(ent)
                    by_id[eid] = ent
                    continue
                target = by_id[eid]
                existing = {f["n"] for f in target["fields"]}
                for f in ent.get("fields", []):
                    if f["n"] in existing:
                        continue  # 骨架优先，重复字段忽略
                    target["fields"].append(f)
                    existing.add(f["n"])
                for key in ("indexes", "constraints", "rules", "notes"):
                    if key in ent and key not in target:
                        target[key] = ent[key]
    core["enums"].update(extra_enums)
    return core, parts


def validate(model):
    errors = []
    warnings = []
    ids = [e["id"] for e in model["entities"]]
    idset = set(ids)
    if len(ids) != len(idset):
        seen = set()
        for i in ids:
            if i in seen:
                errors.append(f"实体 id 重复：{i}")
            seen.add(i)

    layer_ids = set(LAYER_ORDER)
    for e in model["entities"]:
        if e["layer"] not in layer_ids:
            errors.append(f"[{e['id']}] 未知分层：{e['layer']}")
        names = [f["n"] for f in e["fields"]]
        if len(names) != len(set(names)):
            errors.append(f"[{e['id']}] 字段名重复：{[n for n in names if names.count(n) > 1]}")
        for f in e["fields"]:
            if f.get("t") not in SQL_TYPE:
                errors.append(f"[{e['id']}.{f['n']}] 未知类型：{f.get('t')}")
            if f.get("t") == "enum" and f.get("e") not in model["enums"]:
                errors.append(f"[{e['id']}.{f['n']}] 未定义枚举：{f.get('e')}")
            ref = f.get("ref")
            if ref == "ENTITY_TYPE":
                if "entity_type" not in model["enums"]:
                    errors.append(f"[{e['id']}.{f['n']}] 多态引用列缺少 entity_type 枚举注册表")
            elif ref and ref not in idset and ref not in model["enums"]:
                errors.append(f"[{e['id']}.{f['n']}] ref 目标不存在：{ref}")
            elif ref and f.get("t") == "ref" and ref in model["enums"] and ref != "entity_type":
                warnings.append(f"[{e['id']}.{f['n']}] ref={ref} 指向枚举，建议改用 t=enum")
            if f.get("min") is not None and f.get("max") is not None and f["min"] > f["max"]:
                errors.append(f"[{e['id']}.{f['n']}] min 大于 max")
        for key in ("indexes", "constraints", "rules", "notes", "unique_together"):
            if key in e and not isinstance(e[key], list):
                errors.append(f"[{e['id']}] {key} 必须是数组")
        bg = e.get("base_group", "base")
        if bg not in model["standard_field_groups"]:
            errors.append(f"[{e['id']}] 未知通用字段组：{bg}")
        for ut in e.get("unique_together", []) or []:
            if not isinstance(ut, list) or len(ut) < 2:
                errors.append(f"[{e['id']}] unique_together 必须是至少两列的数组：{ut}")
                continue
            for cn in ut:
                if cn not in names:
                    errors.append(f"[{e['id']}] unique_together 引用了不存在的字段：{cn}")

    for c in model["coverage"]:
        for eid in c["entities"]:
            if eid not in idset:
                errors.append(f"[coverage {c['id']}] 引用了不存在的实体：{eid}")

    # 枚举覆盖度：所有枚举都被至少一个字段（含通用字段组）使用
    used = {f.get("e") for e in model["entities"] for f in e["fields"] if f.get("e")}
    for group in model["standard_field_groups"].values():
        used |= {f.get("e") for f in group["fields"] if f.get("e")}
    for name in model["enums"]:
        if name not in used and name != "entity_type":
            warnings.append(f"枚举未被任何字段使用：{name}")
    return errors, warnings


def add_derived_enum(model):
    """注册由实体清单派生的 entity_type 枚举，使多态引用列也能做取值校验。"""
    model["enums"]["entity_type"] = {
        "l": "实体类型（多态引用目标，由实体清单自动生成）",
        "v": [[e["id"], e.get("name", e["id"]), e.get("layer", "")] for e in model["entities"]],
    }
    return model


def expand_fields(entity, model):
    groups = model["standard_field_groups"]
    base = groups[entity.get("base_group", "base")]["fields"]
    out = [dict(f) for f in base if f["n"] == "id"]
    out += [{"n": f["n"], "l": f["l"], "t": f["t"], "d": f.get("d", ""), **{k: v for k, v in f.items() if k in ("req", "u", "idx", "e", "def", "imm", "ref", "refs", "min", "max")}} for f in entity["fields"]]
    flags = entity.get("flags", [])
    optional = [g for g in groups if g not in ("base", "base_append_only") and not groups[g].get("always")]
    optional.sort(key=lambda g: 0 if g in ("origin", "review") else 1)
    for gname in optional:
        if gname in flags:
            out += [dict(f) for f in groups[gname]["fields"]]
    out += [dict(f) for f in base if f["n"] != "id"]
    return out


def normalize(model):
    for e in model["entities"]:
        e["full_fields"] = expand_fields(e, model)
    model["stats"] = {
        "entities": len(model["entities"]),
        "enums": len(model["enums"]),
        "fields": sum(len(e["full_fields"]) for e in model["entities"]),
        "relations": sum(1 for e in model["entities"] for f in e["fields"] if f.get("t") == "ref" and f.get("ref") != "ENTITY_TYPE"),
        "coverage": len(model["coverage"]),
    }
    return model


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("\n", " ") for x in r) + " |")
    return "\n".join(out)


def gen_overview(model):
    lines = []
    names = {"00_base": "基础与横切机制", "01_source": "01 原始资料层", "02_experience": "02 工作经历",
             "03_achievement": "03 成果沉淀", "04_portrait": "04 个人画像层", "05_growth": "05 成长分析与输出层",
             "06_ai": "AI 与数据运维"}
    for layer in LAYER_ORDER:
        ents = [e for e in model["entities"] if e["layer"] == layer]
        if not ents:
            continue
        lines.append(f"\n**{names[layer]}**（{len(ents)} 个实体）\n")
        rows = [[f"`{e['id']}`", e["name"], e["priority"], len(e["full_fields"]), e["purpose"]] for e in ents]
        lines.append(md_table(["实体", "中文名", "优先级", "字段数", "职责"], rows))
    return "\n".join(lines)


def gen_enums(model):
    lines = []
    for name, spec in model["enums"].items():
        if name == "entity_type":
            continue
        rows = [[f"`{c}`", cn, d] for c, cn, d in spec["v"]]
        lines.append(f"\n**`{name}` — {spec['l']}**\n")
        lines.append(md_table(["取值", "含义", "说明"], rows))
    return "\n".join(lines)


def gen_entities(model):
    names = {"00_base": "基础与横切机制", "01_source": "01 原始资料层", "02_experience": "02 工作经历",
             "03_achievement": "03 成果沉淀", "04_portrait": "04 个人画像层", "05_growth": "05 成长分析与输出层",
             "06_ai": "AI 与数据运维"}
    lines = []
    for layer in LAYER_ORDER:
        ents = [e for e in model["entities"] if e["layer"] == layer]
        if not ents:
            continue
        lines.append(f"\n### {names[layer]}\n")
        for e in ents:
            flags = []
            if "origin" in e.get("flags", []):
                flags.append("含来源字段")
            if "review" in e.get("flags", []):
                flags.append("含审核状态字段")
            lines.append(f"\n#### `{e['id']}` {e['name']}　<sub>{e['priority']}{'　·　' + '　·　'.join(flags) if flags else ''}</sub>\n")
            lines.append(f"{e['purpose']}\n")
            rows = []
            for f in e["full_fields"]:
                bits = []
                if f.get("t") == "ref":
                    tgt = f.get("ref")
                    bits.append(f"`{tgt}`" if tgt != "ENTITY_TYPE" else "任意实体类型")
                elif f.get("t") == "enum":
                    bits.append(f"枚举 `{f['e']}`")
                else:
                    bits.append(f.get("t"))
                if f.get("min") is not None and f.get("max") is not None:
                    bits.append(f"取值 {f['min']}~{f['max']}")
                elif f.get("min") is not None:
                    bits.append(f"不小于 {f['min']}")
                elif f.get("max") is not None:
                    bits.append(f"不大于 {f['max']}")
                if f.get("req"):
                    bits.append("必填")
                if f.get("u"):
                    bits.append("唯一")
                if f.get("imm"):
                    bits.append("写入后不可修改")
                if f.get("idx"):
                    bits.append("索引")
                if f.get("def") is not None:
                    bits.append(f"默认 {f['def']}")
                rows.append([f"`{f['n']}`", f["l"], " / ".join(bits), f.get("d", "")])
            lines.append(md_table(["字段", "中文名", "类型与约束", "说明（来源 / 规则 / 用途）"], rows))
            if e.get("unique_together"):
                combos = "；".join("（" + "、".join(f"`{c}`" for c in ut) + "）" for ut in e["unique_together"])
                lines.append(f"\n组合唯一约束：{combos}。\n")
            if e.get("rules"):
                lines.append("\n约束规则：\n")
                for r in e["rules"]:
                    lines.append(f"- {r}")
            if e.get("notes"):
                lines.append("")
                for n in e["notes"]:
                    lines.append(f"> {n}")
    return "\n".join(lines)


def gen_coverage(model):
    groups = {}
    for c in model["coverage"]:
        groups.setdefault(c["src"], []).append(c)
    lines = []
    for src, rows in groups.items():
        lines.append(f"\n**{src}**\n")
        lines.append(md_table(["需求项", "支撑实体", "机制说明"], [
            [r["req"], "、".join(f"`{e}`" for e in r["entities"]), r.get("note", "")] for r in rows]))
    return "\n".join(lines)


def gen_er(model):
    """只画主键与外键，保证图可读；完整字段见第 5 章。"""
    lines = ["```mermaid", "erDiagram"]
    node_ids = {}
    for e in model["entities"]:
        node_ids[e["id"]] = e["id"].upper()
    for e in model["entities"]:
        lines.append(f"  {node_ids[e['id']]} {{")
        lines.append("    uuid id PK")
        for f in e["fields"]:
            if f.get("t") == "ref" and f.get("ref") in node_ids and f.get("ref") != "ENTITY_TYPE":
                lines.append(f"    uuid {f['n']} FK")
        lines.append("  }")
    seen = set()
    for e in model["entities"]:
        for f in e["fields"]:
            tgt = f.get("ref")
            if f.get("t") == "ref" and tgt in node_ids and tgt != e["id"]:
                key = (tgt, e["id"], f["n"])
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"  {node_ids[tgt]} ||--o{{ {node_ids[e['id']]} : \"{f['l']}\"")
    lines.append("```")
    return "\n".join(lines)


def gen_rules(model):
    rules = load_json(os.path.join(SCHEMA_DIR, "rules.json"))
    lines = []
    for group in rules["groups"]:
        lines.append(f"\n**{group['title']}**\n")
        lines.append(md_table(["编号", "规则", "落点"], [[r["id"], r["text"], "、".join(f"`{x}`" for x in r["refs"])] for r in group["rules"]]))
    return "\n".join(lines)


def gen_enum_index(model):
    rows = [[f"`{name}`", spec["l"], str(len(spec["v"])), ", ".join(c for c, _, _ in spec["v"][:6]) + (" …" if len(spec["v"]) > 6 else "")] for name, spec in model["enums"].items()]
    return md_table(["枚举名", "中文名", "取值数", "取值示例"], rows)


def gen_stats(model):
    s = model["stats"]
    return (f"- 实体：**{s['entities']}** 个\n- 字段：**{s['fields']}** 个\n- 枚举：**{s['enums']}** 组\n"
            f"- 外键关系：**{s['relations']}** 条\n- 需求覆盖项：**{s['coverage']}** 条\n")


def table_order(model):
    """按外键依赖拓扑排序建表顺序；返回 (顺序, 参与引用环的表)。"""
    ids = [e["id"] for e in model["entities"]]
    deps = {e["id"]: set() for e in model["entities"]}
    for e in model["entities"]:
        for f in e["full_fields"]:
            r = f.get("ref")
            if r in deps and r != e["id"]:
                deps[e["id"]].add(r)
    remaining = list(ids)
    placed, order = set(), []
    while remaining:
        ready = [i for i in remaining if deps[i] <= placed]
        if not ready:
            break
        for i in ready:
            order.append(i)
            placed.add(i)
            remaining.remove(i)
    return order + remaining, remaining


def gen_ddl(model):
    order, cyclic = table_order(model)
    by_id = {e["id"]: e for e in model["entities"]}
    ent_ids = set(by_id)
    et_vals = ", ".join(repr(c) for c, _, _ in model["enums"]["entity_type"]["v"])
    out = ["-- 个人成长档案系统 参考 DDL（由 schema/model.json 生成，请勿手工修改）",
           "-- 语法以 SQLite 为准；NOT NULL / CHECK / 唯一索引等列级约束三库通用，",
           "-- 类型映射与建表顺序见文档“技术中立性与实现建议”一节。",
           "-- SQLite 需在每个连接执行：PRAGMA foreign_keys = ON;（PostgreSQL 默认强制外键，MySQL 用 FOREIGN_KEY_CHECKS）",
           "-- 表按外键依赖拓扑排序；带 PRIMARY KEY 的列一律 NOT NULL。"]
    if cyclic:
        out.append("-- 以下表之间存在循环引用，移植到强制外键的数据库时需拆成建表 + 事后 ALTER TABLE 加外键：" + "、".join(cyclic))
    out.append("")
    for eid in order:
        e = by_id[eid]
        cols = []
        for f in e["full_fields"]:
            n = f["n"]
            t = SQL_TYPE[f.get("t", "text")]
            if n == "id":
                cols.append(f"  {n} {t} NOT NULL PRIMARY KEY")
                continue
            col = f"  {n} {t}"
            if f.get("req"):
                col += " NOT NULL"
            if f.get("def") is not None:
                dv = f["def"]
                if f.get("t") == "boolean":
                    col += " DEFAULT " + ("1" if str(dv).lower() in ("true", "1") else "0")
                elif str(dv).replace(".", "", 1).isdigit():
                    col += f" DEFAULT {dv}"
                else:
                    col += f" DEFAULT '{dv}'"
            checks = []
            if f.get("t") == "boolean":
                checks.append(f"{n} IN (0, 1)")
            if f.get("t") == "enum" and f.get("e") in model["enums"]:
                checks.append(f"{n} IN ({', '.join(repr(c) for c, _, _ in model['enums'][f['e']]['v'])})")
            if f.get("ref") == "ENTITY_TYPE" and f.get("t") == "ref":
                checks.append(f"{n} IN ({et_vals})")
            if f.get("min") is not None and f.get("max") is not None:
                checks.append(f"{n} BETWEEN {f['min']} AND {f['max']}")
            elif f.get("min") is not None:
                checks.append(f"{n} >= {f['min']}")
            elif f.get("max") is not None:
                checks.append(f"{n} <= {f['max']}")
            for ck in checks:
                col += f" CHECK ({ck})"
            if f.get("t") == "ref" and f.get("ref") in ent_ids:
                col += f" REFERENCES {f['ref']}(id)"
            cols.append(col)
        out.append(f"CREATE TABLE {eid} (")
        out.append(",\n".join(cols))
        out.append(");")
        out.append("")
    out.append("-- 唯一索引：加 WHERE deleted_at IS NULL，使软删除后可以重建同名记录；")
    out.append("-- 组合键中含非必填列时额外加 WHERE 列 IS NOT NULL，避免 NULL 让唯一性失效。")
    for e in model["entities"]:
        nset = {f["n"] for f in e["full_fields"]}
        soft = "deleted_at" in nset
        keys = [[f["n"]] for f in e["full_fields"] if f.get("u")]
        keys += [list(ut) for ut in e.get("unique_together", []) or []]
        seen = set()
        for cols_ in keys:
            name = "uq_" + e["id"] + "_" + "_".join(cols_)
            if name in seen:
                continue
            seen.add(name)
            conds = ["deleted_at IS NULL"] if soft else []
            for c in cols_:
                cf = next((x for x in e["full_fields"] if x["n"] == c), None)
                if cf is not None and not cf.get("req"):
                    conds.append(f"{c} IS NOT NULL")
            where = (" WHERE " + " AND ".join(conds)) if conds else ""
            out.append(f"CREATE UNIQUE INDEX {name} ON {e['id']}({', '.join(cols_)}){where};")
    out.append("")
    out.append("-- 普通索引")
    for e in model["entities"]:
        for f in e["full_fields"]:
            if f.get("idx"):
                out.append(f"CREATE INDEX idx_{e['id']}_{f['n']} ON {e['id']}({f['n']});")
    out.append("")
    out.append("-- 多态引用复合索引（entity_type + entity_id 成对查询）")
    for e in model["entities"]:
        nset = {f["n"] for f in e["full_fields"]}
        for f in e["full_fields"]:
            if f.get("ref") == "ENTITY_TYPE" and f["n"].endswith("_type"):
                sib = f["n"][:-5] + "_id"
                if sib in nset:
                    out.append(f"CREATE INDEX idx_{e['id']}_{f['n']}_{sib} ON {e['id']}({f['n']}, {sib});")
    out.append("")
    return "\n".join(out)


def render_doc(model):
    tpl_path = os.path.join(DOCS_DIR, "数据模型设计.template.md")
    with open(tpl_path, encoding="utf-8") as f:
        tpl = f.read()
    gens = {
        "STATS": gen_stats(model),
        "OVERVIEW": gen_overview(model),
        "ER": gen_er(model),
        "ENTITIES": gen_entities(model),
        "ENUM_INDEX": gen_enum_index(model),
        "ENUMS": gen_enums(model),
        "RULES": gen_rules(model),
        "COVERAGE": gen_coverage(model),
    }
    for key, val in gens.items():
        tpl = tpl.replace("{{GEN:" + key + "}}", val)
    left = re.findall(r"\{\{GEN:[A-Z_]+\}\}", tpl)
    if left:
        raise SystemExit(f"模板存在未替换占位符：{left}")
    return tpl


def check_rules_refs(model):
    """校验 schema/rules.json 的 refs 全部指向真实存在的实体与字段。"""
    ids = {e["id"]: e for e in model["entities"]}
    all_fields = {f["n"] for e in model["entities"] for f in e["full_fields"]}
    bare_ok = set(ids) | set(model["enums"]) | all_fields | {"enums"}
    bad = []
    for group in load_json(os.path.join(SCHEMA_DIR, "rules.json"))["groups"]:
        for r in group["rules"]:
            for ref in r["refs"]:
                if "." not in ref:
                    if ref not in bare_ok:
                        bad.append(f"{r['id']}: 未知实体/枚举/字段 `{ref}`")
                    continue
                ent, fld = ref.split(".", 1)
                if ent not in ids:
                    bad.append(f"{r['id']}: 未知实体 `{ent}`")
                elif fld not in {f["n"] for f in ids[ent]["full_fields"]}:
                    bad.append(f"{r['id']}: {ent} 不存在字段 `{fld}`")
    return bad


def check_template_refs(model, text):
    """确保模板里以 `实体.字段` 形式引用的字段真实存在，避免文档与模型脱节。"""
    ids = {e["id"]: e for e in model["entities"]}
    bad = []
    for m in re.finditer(r"`([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)`", text):
        ent, fld = m.group(1), m.group(2)
        if ent not in ids:
            continue
        if fld not in {f["n"] for f in ids[ent]["full_fields"]}:
            bad.append(f"{ent}.{fld}")
    return sorted(set(bad))


def validate_ddl(ddl):
    """把生成的 DDL 实际灌进内存 SQLite，确保语法与约束可用。"""
    import sqlite3
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(ddl)
    except sqlite3.Error as exc:
        return None, str(exc)
    tables = con.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    indexes = con.execute("SELECT count(*) FROM sqlite_master WHERE type='index'").fetchone()[0]
    con.close()
    return (tables, indexes), None


def main():
    model, parts = merge_model()
    model = add_derived_enum(model)
    errors, warnings = validate(model)
    if errors:
        print("校验失败：")
        for e in errors:
            print("  ✗", e)
        sys.exit(1)
    model = normalize(model)
    os.makedirs(DOCS_DIR, exist_ok=True)

    with open(os.path.join(SCHEMA_DIR, "model.json"), "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)

    ddl = gen_ddl(model)
    counts, ddl_err = validate_ddl(ddl)
    if ddl_err:
        print("生成的 DDL 无法在 SQLite 中执行：", ddl_err)
        sys.exit(3)
    with open(os.path.join(SCHEMA_DIR, "schema.sql"), "w", encoding="utf-8") as f:
        f.write(ddl)

    doc = render_doc(model)
    bad = check_template_refs(model, doc)
    out_doc = os.path.join(DOCS_DIR, "个人成长档案系统-数据模型设计 V1.0.md")
    with open(out_doc, "w", encoding="utf-8") as f:
        f.write(doc)

    s = model["stats"]
    print(f"合并 part 文件：{parts or '无'}")
    print(f"实体 {s['entities']} / 字段 {s['fields']} / 枚举 {s['enums']} / 覆盖项 {s['coverage']}")
    print(f"DDL 已在 SQLite 中执行通过：{counts[0]} 张表 / {counts[1]} 个索引")
    print(f"已生成 schema/model.json、schema/schema.sql、{os.path.basename(out_doc)}（{len(doc)} 字符）")
    if warnings:
        print("提示：")
        for w in warnings:
            print("  !", w)
    rule_bad = check_rules_refs(model)
    if rule_bad:
        print("schema/rules.json 引用了不存在的对象：")
        for b in rule_bad:
            print("  ✗", b)
    if bad or rule_bad:
        if bad:
            print("模板引用了不存在的字段：", bad)
        sys.exit(2)


if __name__ == "__main__":
    main()
