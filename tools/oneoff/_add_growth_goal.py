# -*- coding: utf-8 -*-
"""一次性补丁：在模型骨架中登记「成长目标」实体与两个枚举，并补一条覆盖项。

跑完之后执行 `python tools/build_model.py` 重新生成 schema.sql 与模型文档。
"""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = os.path.join(ROOT, "schema", "model.core.json")

ENUMS = {
    "goal_type": {
        "l": "目标类型",
        "v": [
            ["capability", "能力提升", "围绕能力维度定目标，如补齐数据建模能力"],
            ["experience", "经验积累", "争取某类经历，如独立负责一个从 0 到 1 的项目"],
            ["output", "成果产出", "产出可展示的成果，如一份方法论或一个上线系统"],
            ["completeness", "资料补全", "把档案本身补完整，如补齐工作领域与能力证据"],
            ["habit", "习惯养成", "周期性行为，如每周复盘"],
            ["other", "其他", "不属于以上类型的个人目标"],
        ],
    },
    "goal_status": {
        "l": "目标状态",
        "v": [
            ["proposed", "建议中", "由系统或用户提出，尚未开始"],
            ["active", "进行中", "开始推进，允许更新进度"],
            ["paused", "已暂停", "暂时搁置，保留进度"],
            ["achieved", "已达成", "达到 success_criteria 并已确认"],
            ["abandoned", "已放弃", "主动放弃，需写原因"],
        ],
    },
}

ENTITY = {
    "id": "growth_goal",
    "layer": "05_growth",
    "name": "成长目标",
    "priority": "P1",
    "flags": ["origin", "review", "fact"],
    "purpose": "把「下一步该往哪走」变成可跟踪、可验收的目标：有周期、有达成标准、有进度与证据，"
               "与工作事项、项目、能力维度关联；区别于 project.goal（项目的业务目标）。",
    "fields": [
        {"n": "name", "l": "目标名称", "t": "string", "req": True, "idx": True,
         "d": "一句话写清要达成什么；避免写成工作任务。"},
        {"n": "goal_type", "l": "目标类型", "t": "enum", "e": "goal_type", "req": True, "def": "capability",
         "d": "决定目标页的分组与建议口径。"},
        {"n": "description", "l": "目标说明", "t": "longtext",
         "d": "为什么定这个目标、当前差距在哪；来自用户自述，不由 AI 代写。"},
        {"n": "status", "l": "目标状态", "t": "enum", "e": "goal_status", "req": True, "def": "active", "idx": True,
         "d": "只有 active 的目标参与进度提醒；achieved 必须进度 100%。"},
        {"n": "start_date", "l": "开始日期", "t": "date", "req": True,
         "d": "目标起算日；只精确到月时按当月首日存。"},
        {"n": "end_date", "l": "目标日期", "t": "date",
         "d": "计划达成的日期；长期目标可留空并保持 active。"},
        {"n": "date_precision", "l": "时间精度", "t": "enum", "e": "date_precision", "def": "month",
         "d": "start_date/end_date 的精度，避免把「这个季度」伪造成某一天。"},
        {"n": "progress_percent", "l": "进度", "t": "integer", "req": True, "def": "0", "min": 0, "max": 100,
         "d": "0~100 的整数百分比；由用户按证据更新，不由 AI 估算。"},
        {"n": "success_criteria", "l": "达成标准", "t": "text",
         "d": "可判定的完成条件，如「独立完成一次全量评估并输出方案」；没有标准的进度不计入达成。"},
        {"n": "measurement_note", "l": "衡量方式", "t": "text",
         "d": "用什么数据或证据判断进度，如事项数量、项目结果、能力证据条数。"},
        {"n": "progress_note", "l": "进展说明", "t": "longtext",
         "d": "最近一次推进到什么程度、卡在哪；供复盘时回看。"},
        {"n": "related_project_id", "l": "关联项目", "t": "ref", "ref": "project", "idx": True,
         "d": "目标主要依托的项目，可空。"},
        {"n": "related_domain_id", "l": "关联领域", "t": "ref", "ref": "work_domain", "idx": True,
         "d": "目标所属的工作领域，可空。"},
        {"n": "related_capability_id", "l": "关联能力", "t": "ref", "ref": "capability", "idx": True,
         "d": "能力类目标可挂到具体能力项；能力词典未建立时留空。"},
    ],
    "rules": [
        "`status = achieved` 时 `progress_percent` 必须为 100，否则校验失败。",
        "`end_date` 早于 `start_date` 时校验失败。",
        "`progress_percent` 只能由用户确认后更新；AI 可以建议，但不得直接写正式档案。",
        "`abandoned` 的目标必须写 `progress_note` 说明放弃原因，避免目标无声消失。",
    ],
    "notes": [
        "与 `project.goal` 的区别：后者是项目的业务目标（为业务达成什么），本实体是个人的成长目标（为自己提升什么）。",
        "目标不自动生成事项；完成目标靠关联的 work_item 与 capability_evidence 支撑。",
    ],
}

COVERAGE = {
    "id": "5.1-G1",
    "src": "5.1 成长目标",
    "req": "目标可跟踪、可验收、能复盘",
    "entities": ["growth_goal"],
    "note": "目标有周期、达成标准、进度与关联；进度与状态只由用户确认更新，AI 仅提建议",
}


def main():
    with io.open(CORE, encoding="utf-8") as f:
        model = json.load(f)

    for name, spec in ENUMS.items():
        assert name not in model["enums"], f"枚举已存在：{name}"
        model["enums"][name] = spec

    ids = [e["id"] for e in model["entities"]]
    assert "growth_goal" not in ids
    pos = ids.index("growth_snapshot") + 1
    model["entities"].insert(pos, ENTITY)

    assert all(c["id"] != COVERAGE["id"] for c in model["coverage"])
    model["coverage"].append(COVERAGE)

    with io.open(CORE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("已登记 growth_goal 与 goal_type / goal_status，覆盖项 +1")


if __name__ == "__main__":
    main()
