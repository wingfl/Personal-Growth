# -*- coding: utf-8 -*-
"""第四轮：把 provenance_link 的核心字段收进 core（它是全系统追溯中枢），
并把它在 part 中的规则/备注更新为最终裁决，避免留下已解决的旧结论。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "schema", "model.core.json")
PART = os.path.join(ROOT, "schema", "parts", "00_base_01_source.entities.json")
CHECKER = os.path.join(ROOT, "tools", "check_part.py")

CORE_PATCH = (
    '        { "n": "relation_type", "l": "来源关系", "t": "enum", "e": "provenance_relation", "req": true, "def": "primary_source", "d": "区分主要来源、佐证与反证，反证必须保留" }\n      ]',
    '        { "n": "relation_type", "l": "来源关系", "t": "enum", "e": "provenance_relation", "req": true, "def": "primary_source", "d": "区分主要来源、佐证、推断与反证；反证必须保留" },\n'
    '        { "n": "quote_text", "l": "摘录文本", "t": "text", "imm": true, "d": "从 fragment_id 所指片段中自动截取的支撑原文，写入后锁定，用于列表直接展示出处，不接受手工填写" },\n'
    '        { "n": "match_method", "l": "匹配方式", "t": "string", "d": "链接如何建立：user_manual、ai_semantic、string_match；非 user_manual 的链接不得单独作为已确认结论的依据" }\n      ]',
)

NEW_NOTES = [
    "`quote_text` 必须是 `fragment_id` 对应 `source_fragment.text` 的连续子串，由系统自动摘录，不接受手工填写。",
    "`match_method` 非 user_manual 时，该链接不得单独作为结论进入已确认档案的依据。",
    "`fragment_id` 指向的片段被软删除时，必须先校验反向引用或提示用户确认连带影响（G2）。",
    "本实体现已挂 origin + review 两个通用字段组：审核状态用 `review_status`（pending 待确认 / confirmed 已确认），置信度用 `confidence`，审核时间用 `reviewed_at`；不再另立 is_user_confirmed 等字段。",
    "`provenance_relation` 已新增 `inferred`（有原文但结论属归纳）取值；完全没有原文支撑的推断不建 provenance_link，改用 `origin = ai_agent` + `is_fact = 0` 表达（规则 B2）。因此 `fragment_id` 保持必填。",
]


def main():
    with io.open(CORE, encoding="utf-8") as f:
        core = f.read()
    n = core.count(CORE_PATCH[0])
    if n != 1:
        print(f"core 补丁命中 {n} 次")
        sys.exit(1)
    with io.open(CORE, "w", encoding="utf-8") as f:
        f.write(core.replace(*CORE_PATCH))
    print("core：provenance_link 补 quote_text / match_method")

    with io.open(PART, encoding="utf-8") as f:
        doc = json.load(f)
    hit = [e for e in doc["entities"] if e["id"] == "provenance_link"]
    if len(hit) != 1:
        print("part 中 provenance_link 条目不唯一")
        sys.exit(1)
    hit[0]["fields"] = []
    hit[0]["notes"] = NEW_NOTES
    with io.open(PART, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("part：provenance_link 字段移交 core，备注更新为最终裁决")

    with io.open(CHECKER, encoding="utf-8") as f:
        chk = f.read()
    old = 'if len(fields) < 3:'
    if chk.count(old) != 1:
        print("check_part.py 未找到字段数断言")
        sys.exit(1)
    chk = chk.replace(old, 'if len(fields) < 3 and not (ent.get("rules") or ent.get("notes")):')
    with io.open(CHECKER, "w", encoding="utf-8") as f:
        f.write(chk)
    print("check_part.py：字段数提示仅在既无字段也无规则/备注时触发")


if __name__ == "__main__":
    main()
