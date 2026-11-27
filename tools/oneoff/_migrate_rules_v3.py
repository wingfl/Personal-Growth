# -*- coding: utf-8 -*-
"""第五轮：补 D7（能力级评价去重）——evidence_id 可空后，普通唯一约束拦不住重复的整体评价。"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(ROOT, "schema", "rules.json")

D7 = {
    "id": "D7",
    "text": "同一能力在同一评价维度、同一统计周期上只允许一条有效的整体评价：`is_aggregate = true` 的记录必须按 `capability_id` + `dimension_code` + `period_start` 去重，由应用层在写入前校验。数据库层因能力级记录的 `evidence_id` 为空，普通唯一约束无法拦截（SQL 中 NULL 互不相等），PostgreSQL 等支持部分索引的库应补 `CREATE UNIQUE INDEX ... WHERE evidence_id IS NULL`；单条证据级评价仍由组合唯一约束 `(evidence_id, dimension_code)` 保证不重复。",
    "refs": [
        "evidence_evaluation.capability_id",
        "evidence_evaluation.dimension_code",
        "evidence_evaluation.period_start",
        "evidence_evaluation.is_aggregate",
        "evidence_evaluation.evidence_id",
    ],
}


def main():
    with io.open(RULES, encoding="utf-8") as f:
        doc = json.load(f)
    groups = [g for g in doc["groups"] if g["id"] == "D"]
    if len(groups) != 1:
        print("rules.json 中 D 组不唯一")
        sys.exit(1)
    ids = [r["id"] for r in groups[0]["rules"]]
    if "D7" in ids:
        print("D7 已存在，跳过")
        return
    groups[0]["rules"].append(D7)
    with io.open(RULES, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    total = sum(len(g["rules"]) for g in doc["groups"])
    print(f"已新增 D7，规则总数 {total}")


if __name__ == "__main__":
    main()
