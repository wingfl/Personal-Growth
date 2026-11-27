# -*- coding: utf-8 -*-
"""第八轮：按覆盖度审计补充数据规则。

B6  事实与推断的落库要求（通用字段组 fact）
J13 capability.is_core 的确认口径
J14 合并/拆分血缘的权威来源
J15 主题成员的多态声明与时间线口径
I5  快照指标口径必须可解释
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(ROOT, "schema", "rules.json")

ADD = {
    "B": [{
        "id": "B6",
        "text": "凡挂 `fact` 字段组的内容型实体（事项、项目、系统、模块、主题、成果案例、量化指标、能力证据、个人特征、成长阶段），必须用 `is_fact` 标明该条内容是原文事实还是含 AI 推断：`is_fact = 0` 时必须填写 `fact_basis` 说明推断依据，界面与导出中不得把它当作事实陈述；事实、推断、评价不得写进同一个字段。",
        "refs": ["work_item.is_fact", "work_item.fact_basis", "project.is_fact", "achievement_case.is_fact",
                 "achievement_metric.is_fact", "capability_evidence.is_fact", "capability_evidence.fact_basis",
                 "personal_trait.is_fact", "growth_stage.is_fact"],
    }],
    "I": [{
        "id": "I5",
        "text": "`growth_snapshot.metric_definitions` 必须覆盖 `metrics` 中出现的每一个指标，逐项写明名称、单位、计算口径与统计时间范围；没有口径定义的指标不得在界面或材料中展示，避免出现无法解释的数字与趋势。",
        "refs": ["growth_snapshot.metric_definitions", "growth_snapshot.metrics"],
    }],
    "J": [{
        "id": "J13",
        "text": "`capability.is_core`（当前主要能力）只能由用户在看过证据后确认置位（`origin = user` 且 `review_status = confirmed`，且该能力至少有一条已确认的能力证据）；禁止按证据数量、事项数量或 AI 评分自动推导，成长总览的「核心能力概览」必须能下钻到证据。",
        "refs": ["capability.is_core", "capability.review_status", "capability_evidence.capability_id"],
    }, {
        "id": "J14",
        "text": "合并与拆分血缘以 `entity_relation` 为权威记录（`merged_into` / `split_from` / `duplicate_of` / `replaced_by`）；实体上的 `merged_from_ids`、`merged_into_id`、`supersedes_id` 等字段只是便于展示的冗余快照，写入时必须与 `entity_relation` 同时维护，两者不一致时以 `entity_relation` 为准。",
        "refs": ["entity_relation.relation_type", "project.merged_from_ids", "business_system.merged_from_ids",
                 "function_module.merged_from_ids", "capability_category.merged_into_id"],
    }, {
        "id": "J15",
        "text": "`theme_member.member_type` 必须显式声明成员是工作事项、成果案例还是原始资料：主题的时间线由成员记录的时间聚合而来，阶段性成果与原始资料同样作为成员登记，不得把成果内容抄进 `work_theme.summary` 充当成员。",
        "refs": ["theme_member.member_type", "theme_member.member_id", "work_theme.summary", "achievement_case"],
    }],
}


def main():
    with io.open(RULES, encoding="utf-8") as f:
        doc = json.load(f)
    added = []
    for gid, items in ADD.items():
        groups = [g for g in doc["groups"] if g["id"] == gid]
        if len(groups) != 1:
            print(f"规则组 {gid} 不唯一")
            sys.exit(1)
        have = {r["id"] for r in groups[0]["rules"]}
        for item in items:
            if item["id"] in have:
                print(f"{item['id']} 已存在，跳过")
                continue
            groups[0]["rules"].append(item)
            added.append(item["id"])
    with io.open(RULES, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    total = sum(len(g["rules"]) for g in doc["groups"])
    print(f"新增规则 {added}；规则总数 {total}")


if __name__ == "__main__":
    main()
