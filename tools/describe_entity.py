# -*- coding: utf-8 -*-
"""按实体打印字段规格，便于写实现代码时核对列名、必填、默认值与枚举取值。

用法：
    python tools/describe_entity.py project work_item
    python tools/describe_entity.py --layer 02_experience
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_model():
    with open(os.path.join(ROOT, "schema", "model.json"), encoding="utf-8") as f:
        return json.load(f)


def main(argv):
    model = load_model()
    entities = model["entities"]
    want_layer = None
    brief = False
    ids = []
    i = 0
    while i < len(argv):
        if argv[i] == "--layer":
            want_layer = argv[i + 1]
            i += 2
        elif argv[i] == "--brief":
            brief = True
            i += 1
        else:
            ids.append(argv[i])
            i += 1
    if want_layer:
        ids = [e["id"] for e in entities if e.get("layer") == want_layer]
    if not ids:
        ids = [e["id"] for e in entities]

    by_id = {e["id"]: e for e in entities}
    for eid in ids:
        ent = by_id.get(eid)
        if not ent:
            print("!! 未知实体：%s" % eid)
            continue
        flags = ",".join(ent.get("flags") or []) or "-"
        print("=" * 78)
        print("%s  %s  [layer=%s priority=%s flags=%s]" % (
            ent["id"], ent.get("name", ""), ent.get("layer"), ent.get("priority"), flags))
        if ent.get("purpose"):
            print("用途：%s" % ent["purpose"])
        if ent.get("unique_together"):
            print("组合唯一：%s" % json.dumps(ent["unique_together"], ensure_ascii=False))
        print("-" * 78)
        for f in ent.get("full_fields", []):
            bits = [f.get("t", "?")]
            if f.get("ref"):
                bits.append("ref=%s" % f["ref"])
            if f.get("enum"):
                bits.append("enum=%s" % f["enum"])
            if f.get("req"):
                bits.append("必填")
            if f.get("imm"):
                bits.append("不可改")
            if f.get("idx"):
                bits.append("索引")
            if f.get("u"):
                bits.append("唯一")
            if f.get("min") is not None or f.get("max") is not None:
                bits.append("范围[%s,%s]" % (f.get("min"), f.get("max")))
            if "def" in f:
                bits.append("默认=%s" % json.dumps(f["def"], ensure_ascii=False))
            print("  %-26s %s" % (f.get("n"), " ".join(bits)))
            if f.get("d") and not brief:
                print("      %s" % f["d"])
            ev = f.get("e")
            if ev and ev in model.get("enums", {}):
                items = model["enums"][ev].get("v", [])
                print("      取值：%s" % ", ".join(
                    "%s(%s)" % (v[0], v[1]) if isinstance(v, (list, tuple)) and len(v) > 1
                    else json.dumps(v, ensure_ascii=False) for v in items))
    print("=" * 78)


if __name__ == "__main__":
    main(sys.argv[1:])
