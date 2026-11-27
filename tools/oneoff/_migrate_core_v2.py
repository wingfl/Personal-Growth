# -*- coding: utf-8 -*-
"""第二轮合并：把三个 part 的评审结论收敛回 core，并清掉 part 里与通用字段组重复的字段。

设计原则：同一语义只保留一处。凡 review 字段组已能表达的（审核状态 / AI 置信度 / 审核时间），
part 中自定义的 is_user_confirmed、confidence、confirmed_at、verified_at 一律删除。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "schema", "model.core.json")

# ---------------------------------------------------------------- core 补丁

CORE_PATCHES = [
    # 1. 量化指标可作为能力证据对象（原只能挂 achievement_case）
    (
        '["work_theme", "工作主题", "持续工作主题"]] },',
        '["work_theme", "工作主题", "持续工作主题"], ["achievement_metric", "量化指标", "以量化结果作为能力证据"]] },',
    ),
    # 2. 系统状态、主题状态各自成表，不再复用项目状态
    (
        '        { "n": "status", "l": "状态", "t": "enum", "e": "project_status", "def": "unknown", "d": "复用项目状态语义" },',
        '        { "n": "status", "l": "状态", "t": "enum", "e": "system_status", "def": "unknown", "d": "系统/产品自身生命周期，与项目阶段区分" },',
    ),
    (
        '        { "n": "status", "l": "主题状态", "t": "enum", "e": "project_status", "def": "active", "d": "活跃/暂停/结束" },',
        '        { "n": "status", "l": "主题状态", "t": "enum", "e": "theme_status", "def": "active", "d": "主题是否仍在持续；结束不代表没有成果" },',
    ),
    (
        '    "document_type"',
        '''    "system_status": { "l": "系统状态", "v": [["planning", "规划中", "已立项未开始建设"], ["building", "建设中", "正在实施"], ["online", "已上线", "已交付使用"], ["maintaining", "维护中", "上线后持续维护"], ["offline", "已下线", "停止使用"], ["unknown", "未知", "资料未说明"]] },
    "theme_status": { "l": "主题状态", "v": [["active", "活跃", "近期仍在发生"], ["paused", "暂停", "暂时中断"], ["ended", "已结束", "不再发生，已沉淀成果保留"]] },
    "job_error_code": { "l": "作业错误码", "v": [["parse_failed", "解析失败", "文件无法解析或正文为空"], ["model_error", "模型失败", "模型报错或返回不可用结果"], ["timeout", "超时", "超出执行时限"], ["rate_limited", "限流", "被模型或接口限流"], ["invalid_input", "输入不合法", "缺少必要资料或参数"], ["conflict", "数据冲突", "与现有档案冲突需人工处理"], ["unknown", "未知", "未能归类，需人工查看错误详情"]] },
    "document_type"''',
    ),
    # 3. 能力维度评价既支持「单条证据级」也支持「能力级整体」，故 evidence_id 可空
    (
        '        { "n": "evidence_id", "l": "能力证据", "t": "ref", "ref": "capability_evidence", "req": true, "idx": true, "d": "被评价的证据" },',
        '        { "n": "evidence_id", "l": "能力证据", "t": "ref", "ref": "capability_evidence", "idx": true, "d": "单条证据级评价时必填；能力级整体评价（is_aggregate=true）可空，但必须同时给出 capability_id 与 covered_evidence_ids" },',
    ),
    # 4. AI 建议最集中的几张关联表补 review 字段组（原来只有 origin，AI 建议无审核状态可依据）
    (
        '      "id": "provenance_link", "layer": "00_base", "name": "来源追溯链接", "priority": "P0", "flags": ["origin"],',
        '      "id": "provenance_link", "layer": "00_base", "name": "来源追溯链接", "priority": "P0", "flags": ["origin", "review"],',
    ),
    (
        '      "id": "tag_link", "layer": "00_base", "name": "标签关联", "priority": "P2", "flags": ["origin"],',
        '      "id": "tag_link", "layer": "00_base", "name": "标签关联", "priority": "P2", "flags": ["origin", "review"],',
    ),
    (
        '      "id": "entity_relation", "layer": "00_base", "name": "实体关联", "priority": "P1", "flags": ["origin"],',
        '      "id": "entity_relation", "layer": "00_base", "name": "实体关联", "priority": "P1", "flags": ["origin", "review"],',
    ),
    (
        '      "id": "theme_member", "layer": "02_experience", "name": "主题成员", "priority": "P1", "flags": ["origin"],',
        '      "id": "theme_member", "layer": "02_experience", "name": "主题成员", "priority": "P1", "flags": ["origin", "review"],',
    ),
    (
        '      "id": "achievement_item_link", "layer": "03_achievement", "name": "成果-事项关联", "priority": "P1", "flags": ["origin"],',
        '      "id": "achievement_item_link", "layer": "03_achievement", "name": "成果-事项关联", "priority": "P1", "flags": ["origin", "review"],',
    ),
    (
        '      "id": "capability_alias", "layer": "04_portrait", "name": "能力别名", "priority": "P2", "flags": ["origin"],',
        '      "id": "capability_alias", "layer": "04_portrait", "name": "能力别名", "priority": "P2", "flags": ["origin", "review"],',
    ),
    (
        '      "id": "material_citation", "layer": "05_growth", "name": "材料引用来源", "priority": "P1", "flags": [],',
        '      "id": "material_citation", "layer": "05_growth", "name": "材料引用来源", "priority": "P1", "flags": ["origin", "review"], "unique_together": [["material_id", "section_key", "cited_entity_type", "cited_entity_id"]],',
    ),
    # 5. 材料按自己的生命周期（draft→pending_review→confirmed→exported→archived）流转，
    #    不再叠加通用的 review_status，避免同一张表两个状态字段互相矛盾
    (
        '      "id": "material", "layer": "05_growth", "name": "个人材料", "priority": "P1", "flags": ["origin", "review"],',
        '      "id": "material", "layer": "05_growth", "name": "个人材料", "priority": "P1", "flags": ["origin"],',
    ),
    # 6. personal_trait.status 与通用 review_status 是同一语义，删除后者以外的那个
    (
        '        { "n": "status", "l": "特征状态", "t": "enum", "e": "review_status", "req": true, "def": "pending", "d": "AI 画像假设默认为待审核" },\n',
        '',
    ),
    # 7. 特征证据只能指向工作证据，不能指向自身形成自证闭环
    (
        '        { "n": "target_type", "l": "证据对象类型", "t": "ref", "ref": "ENTITY_TYPE", "req": true, "idx": true, "d": "证据指向的工作实体" },',
        '        { "n": "target_type", "l": "证据对象类型", "t": "enum", "e": "evidence_target_type", "req": true, "idx": true, "d": "证据指向的工作实体；限定取值，禁止指向特征自身形成自证闭环" },',
    ),
    # 8. 快照的分析结论不可修改，否则无法解释历史趋势
    (
        '        { "n": "snapshot_at", "l": "生成时间", "t": "datetime", "req": true, "idx": true, "d": "快照生成时刻" },',
        '        { "n": "snapshot_at", "l": "生成时间", "t": "datetime", "req": true, "idx": true, "imm": true, "d": "快照生成时刻，写入后不可修改" },',
    ),
    (
        '        { "n": "metrics", "l": "指标集合", "t": "json", "req": true, "d": "结构化指标：各能力证据数/强度、领域分布、职责变化等，键名固定以便对比" },',
        '        { "n": "metrics", "l": "指标集合", "t": "json", "req": true, "imm": true, "d": "结构化指标：各能力证据数/强度、领域分布、职责变化等，键名固定以便对比；写入后不可修改" },',
    ),
    (
        '        { "n": "data_coverage", "l": "数据覆盖度", "t": "json", "req": true, "d": "期间资料数、事项数、有证据的能力比例；用于区分“资料变多”和“能力提升”" },',
        '        { "n": "data_coverage", "l": "数据覆盖度", "t": "json", "req": true, "imm": true, "d": "期间资料数、事项数、有证据的能力比例；用于区分“资料变多”和“能力提升”；写入后不可修改" },',
    ),
]

# --------------------------------------------------------- part 字段清理规则
# 语义已被通用 review 字段组覆盖，删除以免同一件事两处维护
DROP_FIELDS = {
    "00_base_01_source": {
        "tag_link": ["confidence", "is_user_confirmed"],
        "provenance_link": ["confidence", "is_user_confirmed", "confirmed_at"],
        "entity_relation": ["confidence"],
    },
    "02_experience_03_achievement": {
        "work_theme": ["is_user_confirmed"],
        "theme_member": ["is_user_confirmed", "confirmed_at"],
        "achievement_item_link": ["is_user_confirmed"],
    },
    "04_portrait_05_growth_06_ai": {
        "material_citation": ["is_user_verified", "verified_at"],
    },
}

# part 中需要改成枚举的字段
ENUM_FIELDS = {
    "04_portrait_05_growth_06_ai": {
        ("ai_job", "error_code"): "job_error_code",
    }
}


def patch_core():
    with io.open(CORE, encoding="utf-8") as f:
        text = f.read()
    for i, (old, new) in enumerate(CORE_PATCHES, 1):
        n = text.count(old)
        if n != 1:
            print(f"core 补丁 {i} 命中 {n} 次，期望 1 次：{old[:70]!r}")
            sys.exit(1)
        text = text.replace(old, new)
    with io.open(CORE, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"core：已应用 {len(CORE_PATCHES)} 处补丁")


def patch_parts():
    for stem, drop_map in DROP_FIELDS.items():
        path = os.path.join(ROOT, "schema", "parts", stem + ".entities.json")
        with io.open(path, encoding="utf-8") as f:
            doc = json.load(f)
        enums = ENUM_FIELDS.get(stem, {})
        removed, converted = [], []
        for ent in doc["entities"]:
            drop = set(drop_map.get(ent["id"], []))
            keep = []
            for f in ent["fields"]:
                key = (ent["id"], f["n"])
                if f["n"] in drop:
                    removed.append(f"{ent['id']}.{f['n']}")
                    continue
                if key in enums:
                    f["t"] = "enum"
                    f["e"] = enums[key]
                    f.pop("ref", None)
                    converted.append(f"{ent['id']}.{f['n']}")
                keep.append(f)
            ent["fields"] = keep
        missing = [f"{e}.{n}" for e, names in drop_map.items() for n in names
                   if f"{e}.{n}" not in removed]
        if missing:
            print(f"{stem}：预期删除但未找到字段：{missing}")
            sys.exit(1)
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"{stem}：删除 {len(removed)} 个重复字段 {removed}；改为枚举 {converted}")


def main():
    patch_core()
    patch_parts()


if __name__ == "__main__":
    main()
