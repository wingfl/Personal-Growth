# -*- coding: utf-8 -*-
"""一次性迁移：把评审发现的骨架问题修进 schema/model.core.json。

每一处替换都断言只命中一次，命中数不符即报错退出，避免静默改错。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "schema", "model.core.json")

PATCHES = [
    # 1. 能被 AI 提议新增的分类类实体补 origin（评审意见 8）
    (
        '      "id": "dict_item", "layer": "00_base", "name": "字典项", "priority": "P1", "flags": [],',
        '      "id": "dict_item", "layer": "00_base", "name": "字典项", "priority": "P1", "flags": ["origin"], "unique_together": [["dictionary_id", "code"]],',
    ),
    (
        '      "id": "tag", "layer": "00_base", "name": "标签", "priority": "P2", "flags": [],',
        '      "id": "tag", "layer": "00_base", "name": "标签", "priority": "P2", "flags": ["origin"],',
    ),
    (
        '      "id": "tag_link", "layer": "00_base", "name": "标签关联", "priority": "P2", "flags": [],',
        '      "id": "tag_link", "layer": "00_base", "name": "标签关联", "priority": "P2", "flags": ["origin"], "unique_together": [["tag_id", "entity_type", "entity_id"]],',
    ),
    # 2. 关联表补唯一约束（评审意见 6）
    (
        '      "id": "entity_relation", "layer": "00_base", "name": "实体关联", "priority": "P1", "flags": ["origin"],',
        '      "id": "entity_relation", "layer": "00_base", "name": "实体关联", "priority": "P1", "flags": ["origin"], "unique_together": [["from_type", "from_id", "to_type", "to_id", "relation_type"]],',
    ),
    (
        '      "id": "theme_member", "layer": "02_experience", "name": "主题成员", "priority": "P1", "flags": ["origin"],',
        '      "id": "theme_member", "layer": "02_experience", "name": "主题成员", "priority": "P1", "flags": ["origin"], "unique_together": [["theme_id", "work_item_id"]],',
    ),
    (
        '      "id": "achievement_item_link", "layer": "03_achievement", "name": "成果-事项关联", "priority": "P1", "flags": ["origin"],',
        '      "id": "achievement_item_link", "layer": "03_achievement", "name": "成果-事项关联", "priority": "P1", "flags": ["origin"], "unique_together": [["achievement_id", "work_item_id", "relation_type"]],',
    ),
    (
        '      "id": "evidence_evaluation", "layer": "03_achievement", "name": "能力维度评价", "priority": "P1", "flags": ["origin", "review"],',
        '      "id": "evidence_evaluation", "layer": "03_achievement", "name": "能力维度评价", "priority": "P1", "flags": ["origin", "review"], "unique_together": [["evidence_id", "dimension_code"]],',
    ),
    (
        '      "id": "capability_alias", "layer": "04_portrait", "name": "能力别名", "priority": "P2", "flags": ["origin"],',
        '      "id": "capability_alias", "layer": "04_portrait", "name": "能力别名", "priority": "P2", "flags": ["origin"], "unique_together": [["capability_id", "alias"]],',
    ),
    # 3. 审计日志只追加：不套用含 updated_at / revision / deleted_at 的通用字段组（评审意见 4）
    (
        '      "id": "audit_log", "layer": "00_base", "name": "变更历史", "priority": "P0", "flags": [],',
        '      "id": "audit_log", "layer": "00_base", "name": "变更历史", "priority": "P0", "flags": [], "base_group": "base_append_only",',
    ),
    (
        '    },\n    "origin": {',
        '''    },
    "base_append_only": {
      "always": false,
      "fields": [
        { "n": "id", "l": "主键", "t": "uuid", "req": true, "d": "UUIDv7；客户端可离线生成，按时间有序" },
        { "n": "created_at", "l": "创建时间", "t": "datetime", "req": true, "d": "记录首次写入时间（UTC）" }
      ]
    },
    "origin": {''',
    ),
    # 4. 来源关系补「推断」取值（评审意见 1）
    (
        '["contradicting", "反证", "与该记录不一致的出处，必须保留"], ',
        '["contradicting", "反证", "与该记录不一致的出处，必须保留"], ["inferred", "推断", "AI 基于多条原文归纳出的结论，须用户确认"], ',
    ),
    # 5. 补「重复导入处理方式」枚举（评审意见 3）
    (
        '    "document_type"',
        '''    "duplicate_handling": { "l": "重复导入处理", "v": [["skip", "跳过", "不导入，保留原有资料"], ["new_version", "作为新版本", "接在同一资料的版本链上新增一版"], ["import_anyway", "仍然导入", "作为独立资料导入，供人工后续合并"]] },
    "document_type"''',
    ),
    (
        '        { "n": "processing_status", "l": "处理状态", "t": "enum", "e": "processing_status", "req": true, "def": "pending", "idx": true, "d": "驱动资料列表的状态展示与重试" }\n      ]',
        '        { "n": "processing_status", "l": "处理状态", "t": "enum", "e": "processing_status", "req": true, "def": "pending", "idx": true, "d": "驱动资料列表的状态展示与重试" },\n        { "n": "duplicate_handling", "l": "重复处理方式", "t": "enum", "e": "duplicate_handling", "d": "导入时命中 content_hash 重复，用户选择的处理方式，用于复盘资料为何存在相似版本" }\n      ]',
    ),
    # 6. 片段偏移必填，规则 A4「区间不得越界」才有意义（评审意见 7）
    (
        '        { "n": "char_start", "l": "起始偏移", "t": "integer", "d": "在原始正文中的字符位置，用于高亮回原文" },\n        { "n": "char_end", "l": "结束偏移", "t": "integer", "d": "字符结束位置" }',
        '        { "n": "char_start", "l": "起始偏移", "t": "integer", "req": true, "d": "在原始正文中的字符位置，用于高亮回原文" },\n        { "n": "char_end", "l": "结束偏移", "t": "integer", "req": true, "d": "字符结束位置，必须大于 char_start" }',
    ),
    # 7. 标签分类不得是自由文本（评审意见 9）
    (
        '{ "n": "category", "l": "标签分类", "t": "string", "d": "如：技术栈、业务、阶段" }',
        '{ "n": "category", "l": "标签分类", "t": "string", "d": "取值必须是 dictionary 中 tag_category 字典已登记的 code，不得自由填写；如 tech_stack、business、stage" }',
    ),
]


def main():
    with io.open(CORE, encoding="utf-8") as f:
        text = f.read()
    for i, (old, new) in enumerate(PATCHES, 1):
        n = text.count(old)
        if n != 1:
            print(f"补丁 {i} 命中 {n} 次，期望 1 次：{old[:70]!r}")
            sys.exit(1)
        text = text.replace(old, new)
    with io.open(CORE, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"已应用 {len(PATCHES)} 处补丁：{CORE}")


if __name__ == "__main__":
    main()
