# -*- coding: utf-8 -*-
"""校验单个 schema/parts/*.entities.json 文件，供编写者自检。

用法：PYTHONIOENCODING=utf-8 python tools/check_part.py schema/parts/xx.entities.json
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "schema", "model.core.json")

TYPES = {"uuid", "string", "text", "longtext", "enum", "date", "datetime",
         "integer", "decimal", "boolean", "json", "ref", "file"}
KEYS = {"n", "l", "t", "d", "req", "u", "imm", "idx", "e", "ref", "def"}
NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")
BANNED_D = {"备注", "说明", "其他", "其他信息", "详见需求", "暂定", "待定", "无", "略", ""}


def check(path):
    core = json.load(open(CORE, encoding="utf-8"))
    ids = {e["id"] for e in core["entities"]}
    enums = set(core["enums"].keys())
    core_fields = {e["id"]: {f["n"] for f in e["fields"]} for e in core["entities"]}

    errs, warns = [], []
    try:
        part = json.load(open(path, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [f"文件不是合法 JSON：{exc}"], []

    if "entities" not in part:
        errs.append("缺少顶层 entities 数组")
        return errs, warns
    if part.get("enums"):
        errs.append("part 文件不得定义枚举（enums 必须为空或不存在）")
    if part.get("$schema") or part.get("meta"):
        warns.append("part 文件不需要 meta/$schema 字段")

    total = 0
    for ent in part["entities"]:
        eid = ent.get("id")
        if eid not in ids:
            errs.append(f"实体 {eid!r} 不在 model.core.json 中（不得新增实体）")
            continue
        names = set()
        fields = ent.get("fields", [])
        if len(fields) < 3 and not (ent.get("rules") or ent.get("notes")):
            warns.append(f"[{eid}] 只补了 {len(fields)} 个字段，预期 3 个以上")
        for f in fields:
            total += 1
            if not isinstance(f, dict):
                errs.append(f"[{eid}] fields 中存在非对象项：{f!r}")
                continue
            unknown = set(f) - KEYS
            if unknown:
                errs.append(f"[{eid}.{f.get('n')}] 出现不允许的键：{sorted(unknown)}（见 README）")
            n = f.get("n")
            if not n or not set(str(n)) <= NAME_CHARS:
                errs.append(f"[{eid}] 字段名不合法：{n!r}（要求小写蛇形）")
                continue
            if n in names:
                errs.append(f"[{eid}.{n}] part 内字段名重复")
            names.add(n)
            if n in core_fields.get(eid, set()):
                errs.append(f"[{eid}.{n}] 已存在于 model.core.json，重复定义（会被忽略）")
            for k in ("l", "t", "d"):
                if not f.get(k):
                    errs.append(f"[{eid}.{n}] 缺少必填键 {k}")
            if f.get("t") and f["t"] not in TYPES:
                errs.append(f"[{eid}.{n}] 类型非法：{f['t']}")
            if f.get("t") == "enum":
                if not f.get("e"):
                    errs.append(f"[{eid}.{n}] 枚举字段缺少 e")
                elif f["e"] not in enums:
                    errs.append(f"[{eid}.{n}] 使用了未登记的枚举：{f['e']}")
            elif f.get("e"):
                errs.append(f"[{eid}.{n}] 非枚举字段不应带 e")
            if f.get("t") == "ref":
                ref = f.get("ref")
                if not ref:
                    errs.append(f"[{eid}.{n}] ref 字段缺少 ref")
                elif ref != "ENTITY_TYPE" and ref not in ids:
                    errs.append(f"[{eid}.{n}] ref 目标不存在：{ref}")
            elif f.get("ref"):
                errs.append(f"[{eid}.{n}] 非 ref 字段不应带 ref")
            d = (f.get("d") or "").strip()
            if d in BANNED_D:
                errs.append(f"[{eid}.{n}] 说明为空话：{d!r}")
            elif len(d) < 10:
                warns.append(f"[{eid}.{n}] 说明过短（{len(d)} 字）：{d}")
            if n.startswith("is_") and f.get("t") not in ("boolean", None):
                warns.append(f"[{eid}.{n}] is_ 前缀建议使用 boolean 类型")
            if f.get("t") == "boolean" and not (n.startswith("is_") or n.startswith("has_")):
                errs.append(f"[{eid}.{n}] boolean 字段必须以 is_/has_ 开头（命名一致性）")
            for k in ("req", "u", "idx", "imm"):
                if k in f and not isinstance(f[k], bool):
                    errs.append(f"[{eid}.{n}] {k} 必须是 true/false")
        for key in ("rules", "notes"):
            v = ent.get(key)
            if v is not None and (not isinstance(v, list) or not all(isinstance(x, str) for x in v)):
                errs.append(f"[{eid}] {key} 必须是字符串数组")
    return errs, warns


def main():
    paths = sys.argv[1:]
    if not paths:
        print("用法：python tools/check_part.py schema/parts/xx.entities.json")
        sys.exit(2)
    all_errs, all_warns = [], []
    for p in paths:
        if not os.path.isabs(p):
            p = os.path.join(ROOT, p)
        if not os.path.exists(p):
            all_errs.append(f"文件不存在：{p}")
            continue
        errs, warns = check(p)
        all_errs += [f"{os.path.basename(p)}: {e}" for e in errs]
        all_warns += [f"{os.path.basename(p)}: {w}" for w in warns]
    for w in all_warns:
        print("  !", w)
    if all_errs:
        print("校验失败：")
        for e in all_errs:
            print("  ✗", e)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
