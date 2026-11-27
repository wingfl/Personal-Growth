# -*- coding: utf-8 -*-
"""第三轮：把规则文本与最终枚举 / 可空性 / 新增约束对齐，并补 6 条新规则。"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(ROOT, "schema", "rules.json")

PATCHES = [
    # A3 记录重复处理方式
    (
        '不得静默产生第二份完全相同的原始资料。", "refs": ["source_document.content_hash", "source_document.source_channel", "import_batch"] },',
        '不得静默产生第二份完全相同的原始资料，所选处理方式写入 `source_document.duplicate_handling` 以便复盘。", "refs": ["source_document.content_hash", "source_document.source_channel", "source_document.duplicate_handling", "import_batch"] },',
    ),
    # B2 推断不必强行编造佐证关系
    (
        '否则校验失败；无原文支撑的推断内容标记为 `supporting` 佐证并允许用户一键否定。", "refs": ["origin", "provenance_link", "provenance_link.relation_type", "source_fragment"] },',
        '否则校验失败；纯 AI 归纳得出的内容不建 `provenance_link`（没有可指认的片段），改用 `origin = ai_agent` + `is_fact = 0` 标记为推断并要求用户确认；若片段存在但结论属归纳，`relation_type` 取 `inferred`（枚举已登记），用户可一键否定。", "refs": ["origin", "provenance_link", "provenance_link.relation_type", "source_fragment", "provenance_relation"] },',
    ),
    # C1 材料是生成产物，不是档案
    (
        '与 `growth_snapshot`（快照需标注 `analysis_note` 为非正式结论）。", "refs": ["change_proposal", "ai_job", "proposal_evidence", "source_document.processing_status", "growth_snapshot", "growth_snapshot.analysis_note"] },',
        '与 `growth_snapshot`（快照需标注 `analysis_note` 为非正式结论）。`material` 是材料生成产物而非档案本身，允许 `ai_job` 直接写入，但必须以 `status = draft` 落库，经用户确认后才可进入 `confirmed` 与导出。", "refs": ["change_proposal", "ai_job", "proposal_evidence", "source_document.processing_status", "growth_snapshot", "growth_snapshot.analysis_note", "material", "material.status"] },',
    ),
    # D3 区分单条证据级与能力级整体评价
    (
        '        { "id": "D3", "text": "`evidence_evaluation` 必须同时具备被评价证据 `evidence_id`、维度 `dimension_code`、等级 `level_value` 与依据说明 `basis_text`，缺失依据的评价视为无效数据并在界面隐藏。", "refs": ["evidence_evaluation.evidence_id", "evidence_evaluation.dimension_code", "evidence_evaluation.level_value", "evidence_evaluation.basis_text"] },',
        '        { "id": "D3", "text": "`evidence_evaluation` 必须给出维度 `dimension_code`、等级 `level_value` 与依据说明 `basis_text`，两种口径二选一：单条证据级评价必填 `evidence_id`；能力级整体评价（`is_aggregate = true`）填 `capability_id` 与 `covered_evidence_ids` 且 `evidence_id` 可为空。缺依据的评价视为无效数据并在界面隐藏。", "refs": ["evidence_evaluation.evidence_id", "evidence_evaluation.capability_id", "evidence_evaluation.is_aggregate", "evidence_evaluation.covered_evidence_ids", "evidence_evaluation.dimension_code", "evidence_evaluation.level_value", "evidence_evaluation.basis_text"] },',
    ),
    # D6 新增：量化指标可作证据 + 整体评价必须有证据集合
    (
        '        { "id": "D5", "text": "能力证据被删除或降级时，依赖它的评价必须标记为需重新评估，不得保留无证据支撑的历史等级。", "refs": ["capability_evidence", "evidence_evaluation"] }\n      ]',
        '        { "id": "D5", "text": "能力证据被删除或降级时，依赖它的评价必须标记为需重新评估，不得保留无证据支撑的历史等级。", "refs": ["capability_evidence", "evidence_evaluation"] },\n        { "id": "D6", "text": "能力证据允许指向量化指标 `achievement_metric`（量化结果同样能证明能力），但该指标必须 `is_verified = 1`；能力级整体评价必须列出 `covered_evidence_ids`，没有证据集合的「整体评分」不得写入档案。", "refs": ["evidence_target_type", "achievement_metric.is_verified", "evidence_evaluation.covered_evidence_ids", "evidence_evaluation.capability_id"] }\n      ]',
    ),
    # E1 / E4 统一到 review_status
    (
        '        { "id": "E1", "text": "`personal_trait` 支持 `status`（候选/已确认/已否定/已废弃）；AI 提出的特征初始为候选，用户确认后才进入画像展示。", "refs": ["personal_trait.status", "personal_trait"] },',
        '        { "id": "E1", "text": "`personal_trait` 不另立状态字段，直接复用通用审核状态 `review_status`：`pending` 候选、`confirmed` 已确认、`rejected` 已否定、`superseded` 已废弃；AI 提出的特征初始为 `pending`，用户确认后才进入画像展示。", "refs": ["personal_trait.review_status", "review_status", "personal_trait"] },',
    ),
    (
        '        { "id": "E4", "text": "用户否定某特征时写入 `status = rejected` 并记录理由，该特征不再出现在画像与材料生成上下文中，但保留历史以备复盘。", "refs": ["personal_trait.status", "personal_trait"] }',
        '        { "id": "E4", "text": "用户否定某特征时写入 `review_status = rejected` 并把理由落 `audit_log`，该特征不再出现在画像与材料生成上下文中，但保留历史以备复盘。", "refs": ["personal_trait.review_status", "personal_trait", "audit_log"] }',
    ),
    # G5 新增：证据类型与评价维度不得混算
    (
        '        { "id": "G4", "text": "详情页必须能一键跳转到原始片段（资料 → 定位到段落），这是可追溯性的验收标准。", "refs": ["source_fragment", "provenance_link"] }\n      ]',
        '        { "id": "G4", "text": "详情页必须能一键跳转到原始片段（资料 → 定位到段落），这是可追溯性的验收标准。", "refs": ["source_fragment", "provenance_link"] },\n        { "id": "G5", "text": "`capability_evidence.evidence_type`（证据类型：职责/表现/复杂度/贡献）与 `evidence_evaluation.dimension_code`（评价维度）粒度不同、来源不同，不可合并统计；任何报表与图表必须显式标明使用哪一种口径，避免同一批证据被双重计数。", "refs": ["capability_evidence.evidence_type", "evidence_evaluation.dimension_code", "evaluation_dimension"] }\n      ]',
    ),
    # I3 明确不可修改字段，并补 I4
    (
        '        { "id": "I3", "text": "`growth_snapshot` 为时点快照，生成后不可修改（`scope_type` 标明快照范围），修正历史结论通过新增快照实现。", "refs": ["growth_snapshot.scope_type", "growth_snapshot"] }\n      ]',
        '        { "id": "I3", "text": "`growth_snapshot` 为时点快照：`snapshot_at` / `metrics` / `data_coverage` 标记为写入后不可修改（`imm`），`scope_type` 标明快照范围；修正历史结论只能通过新增快照实现。", "refs": ["growth_snapshot.scope_type", "growth_snapshot.snapshot_at", "growth_snapshot.metrics", "growth_snapshot.data_coverage", "growth_snapshot"] },\n        { "id": "I4", "text": "生成快照的 AI 作业必须记录 `ai_job` 并可回溯输入范围（用了哪些资料、哪段时间），使曲线上任一点都能回答「这份结论基于什么算出」。", "refs": ["growth_snapshot", "ai_job", "growth_snapshot.data_coverage"] }\n      ]',
    ),
    # J10–J12 新增通用规则
    (
        '        { "id": "J9", "text": "跨设备同步与备份不得改变主键与关联关系；`backup_record` 记录备份范围、格式、校验值与恢复结果，支持一键导出全量数据与迁移到新环境。", "refs": ["backup_record", "backup_record.operation_type"] }\n      ]',
        '        { "id": "J9", "text": "跨设备同步与备份不得改变主键与关联关系；`backup_record` 记录备份范围、格式、校验值与恢复结果，支持一键导出全量数据与迁移到新环境。", "refs": ["backup_record", "backup_record.operation_type"] },\n        { "id": "J10", "text": "分类类字段（如 `tag.category`、文件类型）取值必须是 `dictionary` 中已登记的 `dict_item.code`，不得自由填写或在代码里硬编码；界面用选择器而非文本输入。", "refs": ["tag.category", "dictionary", "dict_item.code"] },\n        { "id": "J11", "text": "同一事物重复出现时，`alias_names` / `aliases` 的匹配结果只能作为候选线索：必须结合时间、领域与上下文给出匹配理由（`theme_member.match_reason`、`work_theme.merge_method`）并由用户确认，禁止仅凭别名字符串相等自动归并。", "refs": ["project.alias_names", "function_module.alias_names", "capability_alias.alias", "theme_member.match_reason", "work_theme.merge_method"] },\n        { "id": "J12", "text": "`attachment` 与 `source_document` 的引用方向唯一：`attachment.owner_type` / `owner_id` 表示文件归属，`source_document.attachment_id` 表示该资料实际使用的文件；同一份文件按内容哈希去重，不得重复建档。", "refs": ["attachment.owner_type", "attachment.owner_id", "attachment.content_hash", "source_document.attachment_id"] }\n      ]',
    ),
]


def main():
    with io.open(RULES, encoding="utf-8") as f:
        text = f.read()
    for i, (old, new) in enumerate(PATCHES, 1):
        n = text.count(old)
        if n != 1:
            print(f"规则补丁 {i} 命中 {n} 次，期望 1 次：{old[:60]!r}")
            sys.exit(1)
        text = text.replace(old, new)
    with io.open(RULES, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"rules.json：已应用 {len(PATCHES)} 处补丁")


if __name__ == "__main__":
    main()
