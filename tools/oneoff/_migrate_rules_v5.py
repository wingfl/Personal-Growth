# -*- coding: utf-8 -*-
"""第十轮：技术审计后的规则补充。

G6  材料引用的两个口径不得混用
J16 角色与贡献以 role_record 为权威
J17 成果归属的唯一口径
J18 唯一性只在未删除记录之间成立
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(ROOT, "schema", "rules.json")

ADD = {
    "G": [{
        "id": "G6",
        "text": "材料引用必须同时给出引用方式 `citation_type` 与被引用对象类型 `cited_entity_type`：前者说明这段文字是原文引用、改写还是由多条记录派生，后者说明引用的是哪类对象；两者语义不同，不得互相替代。`citation_type = derived` 的段落不得计入「逐条可回溯原文」的统计口径。",
        "refs": ["material_citation.citation_type", "material_citation.cited_entity_type",
                 "material_citation.cited_entity_id", "material_citation.paragraph_index"],
    }],
    "J": [{
        "id": "J16",
        "text": "角色与贡献的权威记录是 `role_record`（含 `role`、`start_date`、`end_date` 与 `role_change_reason`）；项目、系统、模块、工作事项、成果案例上的 `my_role` 只是该对象当前角色的冗余展示，写入时必须与 `role_record` 同步，两者冲突时以 `role_record` 为准并在审核界面提示差异。职责范围与贡献说明不得只写在项目表上，必须能追溯到具体角色记录。",
        "refs": ["role_record.role", "role_record.start_date", "role_record.end_date", "role_record.role_change_reason",
                 "role_record.target_type", "role_record.target_id", "project.my_role", "work_item.my_role",
                 "achievement_case.my_role", "function_module.my_role"],
    }, {
        "id": "J17",
        "text": "成果的项目、系统、模块与领域归属以 `achievement_case` 上的直连字段（`project_id`、`system_id`、`module_id`、`domain_id`）为唯一口径；`achievement_item_link` 只描述成果与具体工作事项之间的贡献关系，不得据此反推出与该直连字段不同的归属。",
        "refs": ["achievement_case.project_id", "achievement_case.system_id", "achievement_case.module_id",
                 "achievement_case.domain_id", "achievement_item_link.achievement_id", "achievement_item_link.work_item_id"],
    }, {
        "id": "J18",
        "text": "唯一性只在未删除记录之间成立：所有唯一约束以带 `WHERE deleted_at IS NULL` 的部分唯一索引落地，软删除后允许重建同名记录（如删除错误项目后重新录入同名项目）；组合唯一键中含非必填列时，还必须追加该列的 `IS NOT NULL` 条件，否则 NULL 会让约束失效。物理删除不在 V1.0 范围内。",
        "refs": ["project", "dict_item.code", "capability.code", "evidence_evaluation.evidence_id"],
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
