# -*- coding: utf-8 -*-
"""第七轮：按覆盖度审计结果补齐模型。

1) trait_type 分面化（需求 6.5：任务处理、沟通协作、问题解决、决策），把「优势/待发展」交给 trait_polarity。
2) 新增 project_type（需求 6.6：经历成长曲线含项目类型变化）并挂到 project。
3) capability.is_core（需求 6.2：核心能力概览「当前主要能力」）。
4) 新增通用字段组 fact（is_fact + fact_basis），落实 1.4⑤ 与 8.4 的「区分客观事实、AI 推断和评价结论」。
5) theme_member 改为多态成员（work_item / achievement_case / source_document），
   支撑需求「查看该主题下的完整工作时间线、原始资料和阶段性成果」。
6) snapshot_scope 增加「成长阶段」；growth_snapshot 增加指标口径字段（8.4 图表需标题/图例/单位/时间范围）。
7) 修正覆盖矩阵中三处与事实不符的自述，并补 8.4 的两条覆盖项。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "schema", "model.core.json")

TRAIT_OLD = '    "trait_type": { "l": "特征类型", "v": [["work_style", "工作风格", "任务处理与协作方式"], ["thinking_pattern", "思维方式", "分析与决策的思维特点"], ["behavior_habit", "行为习惯", "稳定出现的行为习惯"], ["interest", "兴趣倾向", "偏好的工作内容与方向"], ["strength", "优势", "已体现出的明显优势"], ["improvement_area", "待发展方向", "仍有提升空间的方面"]] },'
TRAIT_NEW = ('    "trait_type": { "l": "特征类型", "v": [["work_style", "工作风格", "整体工作风格与节奏"], '
             '["thinking_pattern", "思维方式", "分析与决策的思维特点"], '
             '["behavior_habit", "行为习惯", "稳定出现的行为习惯"], '
             '["task_handling", "任务处理", "承接、拆解与推进任务的方式"], '
             '["communication", "沟通协作", "信息同步、跨方协作与推动方式"], '
             '["problem_solving", "问题解决", "定位与解决复杂问题的方式"], '
             '["decision_making", "决策方式", "在不确定条件下做取舍的方式"], '
             '["interest", "兴趣倾向", "偏好的工作内容与方向"]] },\n'
             '    "project_type": { "l": "项目类型", "v": [["new_build", "新建/建设类", "从无到有的系统或能力建设"], ["enhancement", "优化/改造类", "在既有基础上做改造提升"], ["maintenance", "运维/支持类", "保障既有系统稳定运行"], ["research", "研究/预研类", "探索性、验证性工作"], ["process", "流程/制度类", "流程、规范、制度建设"], ["support", "支撑/协调类", "跨团队支撑与协调"], ["other", "其他", "无法归入以上类型"]] },\n'
             '    "theme_member_type": { "l": "主题成员类型", "v": [["work_item", "工作事项", "归入主题的工作事项，构成时间线"], ["achievement_case", "成果案例", "该主题下的阶段性成果"], ["source_document", "原始资料", "支撑该主题的原始资料"]] },')

PATCHES = [
    # 通用字段组 fact
    ('    "origin": {\n      "always": false,',
     '    "fact": {\n      "always": false,\n      "fields": [\n'
     '        { "n": "is_fact", "l": "是否事实", "t": "boolean", "req": true, "def": "true", "idx": true, "d": "内容是否直接来自事实（原文摘录或用户确认）。false 表示含 AI 推断成分，展示与分析时必须标注，不得当作事实陈述" },\n'
     '        { "n": "fact_basis", "l": "事实依据", "t": "text", "d": "判定为事实或推断的依据：来源片段、用户确认记录或推断链条说明；is_fact=false 时必填" }\n'
     '      ]\n    },\n'
     '    "origin": {\n      "always": false,'),
    # 枚举
    (TRAIT_OLD, TRAIT_NEW),
    ('["project", "项目", "针对某个项目"]] },', '["project", "项目", "针对某个项目"], ["stage", "成长阶段", "针对某个成长阶段"]] },'),
    # project：新增 project_type
    ('{ "n": "status", "l": "项目状态", "t": "enum", "e": "project_status", "req": true, "def": "unknown", "d": "项目所处阶段" },',
     '{ "n": "status", "l": "项目状态", "t": "enum", "e": "project_status", "req": true, "def": "unknown", "d": "项目所处阶段" },\n'
     '        { "n": "project_type", "l": "项目类型", "t": "enum", "e": "project_type", "idx": true, "d": "支撑需求 6.6“经历成长曲线”中的项目类型变化；与工作领域是两个维度，不要用领域代替类型" },'),
    # capability：新增 is_core
    ('{ "n": "status", "l": "词条状态", "t": "enum", "e": "capability_status", "req": true, "def": "active", "d": "停用后不再新增关联" }',
     '{ "n": "status", "l": "词条状态", "t": "enum", "e": "capability_status", "req": true, "def": "active", "d": "停用后不再新增关联" },\n'
     '        { "n": "is_core", "l": "当前主要能力", "t": "boolean", "req": true, "def": "false", "idx": true, "d": "成长总览“核心能力概览”的取数标记；只能由用户看过证据后确认（规则 J13），不得按证据数量自动置位" }'),
    # theme_member：多态成员
    ('"id": "theme_member", "layer": "02_experience", "name": "主题成员", "priority": "P1", "flags": ["origin", "review"], "unique_together": [["theme_id", "work_item_id"]],',
     '"id": "theme_member", "layer": "02_experience", "name": "主题成员", "priority": "P1", "flags": ["origin", "review"], "unique_together": [["theme_id", "member_type", "member_id"]],'),
    ('"purpose": "主题与工作事项的多对多关联，归并后原始事项完整保留，不因归并而丢失。",',
     '"purpose": "主题与工作事项/成果案例/原始资料的多对多关联，支撑“查看该主题下的完整工作时间线、原始资料和阶段性成果”；归并后原始记录完整保留，不因归并而丢失。",'),
    ('{ "n": "work_item_id", "l": "工作事项", "t": "ref", "ref": "work_item", "req": true, "idx": true, "d": "归入该主题的事项" },',
     '{ "n": "member_type", "l": "成员类型", "t": "enum", "e": "theme_member_type", "req": true, "idx": true, "d": "成员是工作事项、成果案例还是原始资料，决定 member_id 的解释方式" },\n'
     '        { "n": "member_id", "l": "成员主键", "t": "uuid", "req": true, "idx": true, "d": "成员记录主键，按 member_type 解释；多态引用，存在性由应用层校验" },'),
    # growth_snapshot
    ('{ "n": "scope_type", "l": "分析范围", "t": "enum", "e": "snapshot_scope", "req": true, "def": "global", "d": "全局/时间段/能力/领域/项目" },',
     '{ "n": "scope_type", "l": "分析范围", "t": "enum", "e": "snapshot_scope", "req": true, "def": "global", "d": "全局/时间段/能力/领域/项目/成长阶段" },'),
    ('{ "n": "data_coverage", "l": "数据覆盖度", "t": "json", "req": true, "imm": true, "d": "期间资料数、事项数、有证据的能力比例；用于区分“资料变多”和“能力提升”；写入后不可修改" },',
     '{ "n": "data_coverage", "l": "数据覆盖度", "t": "json", "req": true, "imm": true, "d": "期间资料数、事项数、有证据的能力比例；用于区分“资料变多”和“能力提升”；写入后不可修改" },\n'
     '        { "n": "metric_definitions", "l": "指标口径", "t": "json", "req": true, "imm": true, "d": "metrics 中每个指标的 code、名称、单位、计算口径与统计时间范围；图表的标题、图例与单位由此渲染，避免展示没有口径的数字；写入后不可修改" },'),
    # capability_evidence：is_fact 交给通用字段组，避免与组字段重名（连同上一行的逗号一起去掉）
    ('        { "n": "strength", "l": "支撑强度", "t": "integer", "d": "1~5，证据对能力的支撑程度" },\n'
     '        { "n": "is_fact", "l": "是否事实", "t": "boolean", "req": true, "def": "true", "d": "区分客观事实与 AI 推断，推断类不得作为正式结论" }\n',
     '        { "n": "strength", "l": "支撑强度", "t": "integer", "d": "1~5，证据对能力的支撑程度" }\n'),
]

FACT_ENTITIES = ["project", "business_system", "function_module", "work_item", "work_theme",
                 "achievement_case", "achievement_metric", "capability_evidence", "personal_trait", "growth_stage"]

COVERAGE_FIX = {
    "1.4-5": ("全部内容型实体（is_fact/fact_basis 字段组）", "统一用 origin 标记记录来源方式（用户录入/AI 生成/导入/系统生成），用 is_fact + fact_basis 区分原文事实与 AI 推断，用 review_status 标记确认状态；评价结论只落在 evidence_evaluation 与 self_assessment，不写进事实字段"),
    "6.5-2": ("personal_trait", "trait_type 已按需求分面为工作风格、思维方式、行为习惯、任务处理、沟通协作、问题解决、决策方式、兴趣倾向，优势/待提升由 trait_polarity 表达"),
    "6.6-2": ("project", "project.project_type 记录项目类型变化，role_record.role 记录职责范围变化，work_item.complexity_level 记录工作复杂度变化，domain_id 记录领域变化"),
}
COVERAGE_ADD = [
    {"id": "8.4-3", "src": "8.4 数据真实性与可视化", "req": "图表应有标题、图例、单位和时间范围",
     "entities": ["growth_snapshot", "achievement_metric"],
     "note": "growth_snapshot.metric_definitions 逐项记录指标名称、单位、口径与统计时间范围，图表元信息从这里取；achievement_metric 自带单位与统计区间"},
    {"id": "8.4-4", "src": "8.4 数据真实性与可视化", "req": "区分客观事实、AI 推断和评价结论",
     "entities": ["provenance_link", "capability_evidence", "evidence_evaluation", "self_assessment"],
     "note": "事实由 provenance_link 指回原文；推断由 is_fact=false + fact_basis 标注；评价只存在于 evidence_evaluation 与 self_assessment，三类数据不混放"},
]


def apply(text, old, new, expect=1):
    n = text.count(old)
    if n != expect:
        print(f"补丁命中 {n} 次（预期 {expect}）：{old[:60]}...")
        sys.exit(1)
    return text.replace(old, new)


def main():
    with io.open(CORE, encoding="utf-8") as f:
        core = f.read()
    for old, new in PATCHES:
        core = apply(core, old, new)

    lines = core.splitlines(keepends=True)
    touched = []
    for i, ln in enumerate(lines):
        for eid in FACT_ENTITIES:
            if f'"id": "{eid}", "layer"' in ln:
                if '"flags": ["origin", "review"]' in ln:
                    lines[i] = ln.replace('"flags": ["origin", "review"]', '"flags": ["origin", "review", "fact"]')
                    touched.append(eid)
                elif '"flags": ["origin"]' in ln:
                    lines[i] = ln.replace('"flags": ["origin"]', '"flags": ["origin", "fact"]')
                    touched.append(eid)
    core = "".join(lines)
    missing = [e for e in FACT_ENTITIES if e not in touched]
    if missing:
        print("未挂 fact 字段组的实体：", missing)
        sys.exit(1)

    doc = json.loads(core)
    ids = {it["id"] for it in doc["coverage"]}
    for cid, (ents, note) in COVERAGE_FIX.items():
        for it in doc["coverage"]:
            if it["id"] == cid:
                if isinstance(ents, str):
                    ents = [ents]
                it["entities"] = ents
                it["note"] = note
    for item in COVERAGE_ADD:
        if item["id"] in ids:
            print("覆盖项已存在：", item["id"])
            sys.exit(1)
        doc["coverage"].append(item)

    with io.open(CORE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"已挂 fact 字段组：{len(touched)} 个实体")
    print(f"覆盖项：{len(doc['coverage'])} 条；枚举：{len(doc['enums'])} 组")


if __name__ == "__main__":
    main()
