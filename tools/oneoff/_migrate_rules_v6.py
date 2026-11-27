# -*- coding: utf-8 -*-
"""第十一轮：产品决策落库（用户已拍板）。

J19 成长阶段必须由用户确认后生效（AI 只给候选）
J20 工作领域是弱分类，不得升格为必填或换算口径
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(ROOT, "schema", "rules.json")

ADD = [{
    "id": "J19",
    "text": "成长阶段必须由用户确认后才生效：`auto_detected = true` 的阶段只是 AI 候选，`review_status` 必须为 `confirmed` 才参与成长分析、时间轴与材料生成；每条阶段必须写明 `division_basis`（为何这样划分、依据哪些档案事实）与 `stage_type`（划分依据类型），AI 由 `detected_by_job_id` 回溯。AI 不得自行切换划分标准，给出候选时必须回显所用的标准。",
    "refs": ["growth_stage.auto_detected", "growth_stage.review_status", "growth_stage.division_basis",
             "growth_stage.stage_type", "growth_stage.detected_by_job_id"],
}, {
    "id": "J20",
    "text": "工作领域是**弱分类**：项目、工作事项、成果案例上的 `domain_id` 一律可选（不得设为必填），领域也不得作为能力评价或成长评级的换算口径；停用领域（`is_active = false`）只影响新增选择，不影响历史归属与统计。领域分布仅用于展示与筛选。",
    "refs": ["work_domain", "work_domain.is_active", "project.domain_id", "work_item.domain_id",
             "achievement_case.domain_id"],
}]


def main():
    with io.open(RULES, encoding="utf-8") as f:
        doc = json.load(f)
    groups = [g for g in doc["groups"] if g["id"] == "J"]
    if len(groups) != 1:
        print("规则组 J 不唯一")
        sys.exit(1)
    have = {r["id"] for r in groups[0]["rules"]}
    added = []
    for item in ADD:
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
