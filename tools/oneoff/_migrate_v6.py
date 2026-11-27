# -*- coding: utf-8 -*-
"""第九轮：按技术审计补齐取值约束与去伪外键。

1) 为数值字段补 min/max（生成 CHECK，制止等级/比例/计数类脏值）
2) `tag.category`（自由文本伪外键）→ `tag.category_item_id`（外键 dict_item）
3) `proposal_evidence.relevance_type` 独立枚举（原先复用 provenance_relation）
4) `evaluation_level` 补组合唯一 (dimension_code, level_value)
5) `content_hash` 中文名由「内容摘要」正名为「内容哈希」
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "schema", "model.core.json")
PARTS = os.path.join(ROOT, "schema", "parts")
RULES = os.path.join(ROOT, "schema", "rules.json")

RANGES = {
    # 1~5 等级类
    "project.importance_level": (1, 5),
    "work_item.complexity_level": (1, 5),
    "achievement_case.value_level": (1, 5),
    "capability_evidence.strength": (1, 5),
    "evidence_evaluation.level_value": (1, 5),
    "evaluation_level.level_value": (1, 5),
    "capability.capability_level_rank": (1, 5),
    "trait_evidence.weight": (1, 5),
    "self_assessment.self_rating": (1, 5),
    "change_proposal.priority": (1, 5),
    # 0~1 比例类
    "entity_relation.strength": (0, 1),
    "source_fragment.parse_confidence": (0, 1),
    "work_theme.merge_similarity": (0, 1),
    "theme_member.similarity_score": (0, 1),
    "achievement_item_link.similarity_score": (0, 1),
    "achievement_item_link.contribution_weight": (0, 1),
    "provenance_link.confidence": (0, 1),
    "tag_link.confidence": (0, 1),
    "project.confidence": (0, 1),
    "work_item.confidence": (0, 1),
    "capability_evidence.confidence": (0, 1),
    "growth_snapshot.confidence": (0, 1),
    # 计数 / 字节 / 毫秒（非负）
    "attachment.file_size": (0, None),
    "attachment.page_count": (0, None),
    "source_document.word_count": (0, None),
    "work_item.effort_hours": (0, None),
    "capability_alias.usage_count": (0, None),
    "personal_trait.support_count": (0, None),
    "personal_trait.counter_count": (0, None),
    "personal_trait.observation_span_months": (0, None),
    "material.word_limit": (0, None),
    "ai_job.duration_ms": (0, None),
    "ai_job.cost_amount": (0, None),
    "ai_job.input_fragment_count": (0, None),
    "ai_job.proposal_count": (0, None),
    "ai_job.retry_count": (0, None),
    "change_proposal.review_duration_ms": (0, None),
    "proposal_evidence.quote_char_start": (0, None),
    "proposal_evidence.quote_char_end": (0, None),
    "agent_credential.rate_limit_per_minute": (0, None),
    "agent_credential.usage_count": (0, None),
    "backup_record.record_count": (0, None),
    "backup_record.size_bytes": (0, None),
    "backup_record.duration_ms": (0, None),
    "import_batch.file_count": (0, None),
    "import_batch.success_count": (0, None),
    "import_batch.failed_count": (0, None),
    "import_batch.duplicate_count": (0, None),
    "import_batch.total_size_bytes": (0, None),
    "source_fragment.order_index": (0, None),
    # 从 1 开始的序号类
    "source_document.version_no": (1, None),
    "material.version_no": (1, None),
    "growth_stage.stage_index": (1, None),
    "capability_category.level_depth": (1, None),
    "project.team_size": (1, None),
    "source_fragment.page_no": (1, None),
    "source_fragment.heading_level": (1, None),
    "material_citation.paragraph_index": (1, None),
    "prompt_template.version": (1, None),
    "agent_workflow.version": (1, None),
    "source_fragment.char_end": (1, None),
    # 排序字段
    "work_domain.sort_order": (0, None),
    "dictionary.sort_order": (0, None),
    "dict_item.sort_order": (0, None),
    "tag.sort_order": (0, None),
    "evaluation_dimension.sort_order": (0, None),
    "capability_category.sort_order": (0, None),
    "personal_trait.display_order": (0, None),
}

NUMERIC = ("integer", "decimal")


def load(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, doc):
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    core = load(CORE)
    part_files = sorted(f for f in os.listdir(PARTS) if f.endswith(".entities.json")) if os.path.isdir(PARTS) else []
    parts = {name: load(os.path.join(PARTS, name)) for name in part_files}

    def all_entity_fields(eid):
        """返回 (doc, 字段 dict 列表) —— core 与各 part 中该实体的字段。"""
        found = []
        for ent in core["entities"]:
            if ent["id"] == eid:
                found.append((core, ent.get("fields", [])))
        for doc in parts.values():
            for ent in doc.get("entities", []):
                if ent["id"] == eid:
                    found.append((doc, ent.get("fields", [])))
        return found

    applied = []
    problems = []

    for ref, (lo, hi) in RANGES.items():
        eid, fname = ref.split(".", 1)
        hits = []
        for doc, fields in all_entity_fields(eid):
            for f in fields:
                if f["n"] == fname:
                    hits.append(f)
        # confidence 等落在通用字段组里
        for gname, g in core["standard_field_groups"].items():
            for f in g["fields"]:
                if f["n"] == fname and eid in [e["id"] for e in core["entities"] if gname in e.get("flags", [])]:
                    hits.append(f)
        if not hits:
            problems.append(f"未找到 {ref}")
            continue
        if hits[0].get("t") not in NUMERIC:
            problems.append(f"{ref} 类型为 {hits[0].get('t')}，不是数值字段")
        for f in hits:
            if lo is not None:
                f["min"] = lo
            if hi is not None:
                f["max"] = hi
        applied.append(ref)

    # 2) tag.category → tag.category_item_id
    tag = [e for e in core["entities"] if e["id"] == "tag"][0]
    cat = [f for f in tag["fields"] if f["n"] == "category"]
    if len(cat) == 1:
        cat[0].update({
            "n": "category_item_id",
            "l": "标签分类项",
            "t": "ref",
            "ref": "dict_item",
            "idx": True,
            "d": "指向 dictionary.code = tag_category 下的 dict_item：分类取值必须是已登记的字典项，"
                 "不得自由填写或在代码里硬编码；新增分类先加字典项再使用。",
        })
        applied.append("tag.category→tag.category_item_id")
    elif not any(f["n"] == "category_item_id" for f in tag["fields"]):
        problems.append("tag.category 未找到")

    # 3) proposal_evidence.relevance_type 独立枚举
    if "relevance_type" not in core["enums"]:
        core["enums"]["relevance_type"] = {
            "l": "证据与建议的关系",
            "v": [["primary_source", "主要来源", "建议主要依据的原文"],
                  ["supporting", "佐证", "支持建议的补充原文"],
                  ["contradicting", "反证", "与建议冲突、必须同等展示的原文"],
                  ["context", "背景", "帮助理解但不直接支持或反驳的原文"]],
        }
    changed = 0
    for doc in [core] + list(parts.values()):
        for ent in doc.get("entities", []):
            if ent["id"] != "proposal_evidence":
                continue
            for f in ent.get("fields", []):
                if f["n"] == "relevance_type" and f.get("e") == "provenance_relation":
                    f["e"] = "relevance_type"
                    f["d"] = ("该片段对建议的作用：主要来源 primary_source、佐证 supporting、"
                              "反证 contradicting、背景 context；反证必须与支持证据同等展示"
                              "（对应 C4 与事实/推断分离）。")
                    changed += 1
    if changed:
        applied.append(f"proposal_evidence.relevance_type 改用独立枚举（{changed} 处）")
    elif not any(f["n"] == "relevance_type" for doc in [core] + list(parts.values())
                 for ent in doc.get("entities", []) for f in ent.get("fields", [])):
        problems.append("proposal_evidence.relevance_type 未找到")

    # 4) evaluation_level 组合唯一
    lvl = [e for e in core["entities"] if e["id"] == "evaluation_level"][0]
    if not lvl.get("unique_together"):
        lvl["unique_together"] = [["dimension_code", "level_value"]]
        applied.append("evaluation_level(dimension_code, level_value) 组合唯一")

    # 5) content_hash 正名
    for eid in ("attachment", "source_document"):
        for doc, fields in all_entity_fields(eid):
            for f in fields:
                if f["n"] == "content_hash" and f.get("l") == "内容摘要":
                    f["l"] = "内容哈希"
                    applied.append(f"{eid}.content_hash 中文名正名")
                    break

    if problems:
        print("补丁前置校验失败：")
        for p in problems:
            print("  ✗", p)
        sys.exit(1)

    save(CORE, core)
    for name, doc in parts.items():
        save(os.path.join(PARTS, name), doc)

    # rules.json：tag.category → tag.category_item_id
    rules = load(RULES)
    fixed = 0
    for group in rules["groups"]:
        for r in group["rules"]:
            if "tag.category" in r["text"]:
                r["text"] = r["text"].replace("`tag.category`", "`tag.category_item_id`")
                fixed += 1
            r["refs"] = ["tag.category_item_id" if x == "tag.category" else x for x in r["refs"]]
    save(RULES, rules)

    print(f"已应用 {len(applied)} 项补丁：")
    for a in applied:
        print("  ·", a)
    print(f"规则文本同步 {fixed} 处")


if __name__ == "__main__":
    main()
