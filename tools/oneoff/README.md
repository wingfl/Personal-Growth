# 一次性脚本（已执行完毕，不要重复运行）

这些脚本在项目推进过程中各自执行过一次，用于对**已经落盘**的模型与代码做精确补丁。
它们保留下来是为了让「当时为什么这么改」有迹可循，**不是**可重跑的迁移工具：

- 每个脚本都用「断言恰好命中 N 次」的方式定位待改文本，改完即失效；重复运行会以
  非零退出码中止（这是有意设计的保护）。
- 真正的、可重复执行的迁移工具是 `tools/migrate_db.py`（给已有数据库补新列与新索引）；
  数据模型的变更是改 `schema/model.core.json` / `schema/parts/*.json` 后重跑
  `tools/build_model.py`。

| 脚本 | 做了什么 |
| --- | --- |
| `_migrate_core_v1.py` | 补 origin/unique_together、audit_log 改 append-only 字段组、新增 duplicate_handling 等 15 处 |
| `_migrate_core_v2.py` | 删除与 review 字段组重复的 12 个字段、ai_job.error_code 改枚举等 18 处 + part 清理 |
| `_migrate_v3.py` | 把 provenance_link.quote_text / match_method 收进 core |
| `_migrate_v4.py` | 修 material_citation.section_key 为必填（可空列组合唯一约束失效） |
| `_migrate_v5.py` | trait_type 分面化、新增 project_type/is_core/fact 字段组、theme_member 多态化等 |
| `_migrate_v6.py` | 73 个数值字段的 min/max、tag.category→category_item_id、relevance_type 独立枚举等 |
| `_migrate_v7.py` | 新增 source_channel=feishu 与 source_document.external_* 三个字段 |
| `_migrate_rules_v2/v3/v4/v5/v6.py` | 规则集的五轮增补（D6/G5/I3–I5/B6/J10–J20 等） |
| `_patch_importers_feishu.py` | 导入层抽出 `parse_text` / `import_text`，支持外部来源 |
| `_patch_cli_feishu.py` | CLI 增加 `feishu` 命令组 |
| `_patch_oauth.py` | 飞书用户身份 OAuth 接线（客户端用户令牌、身份模式、`feishu auth/whoami/logout`） |
| `_patch_readme_feishu.py` | README 增加飞书同步小节 |
| `patch_prompt_v1.py` | 提示词 v1 增补 link_existing 分节与数组字段口径 |
