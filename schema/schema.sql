-- 个人成长档案系统 参考 DDL（由 schema/model.json 生成，请勿手工修改）
-- 语法以 SQLite 为准；NOT NULL / CHECK / 唯一索引等列级约束三库通用，
-- 类型映射与建表顺序见文档“技术中立性与实现建议”一节。
-- SQLite 需在每个连接执行：PRAGMA foreign_keys = ON;（PostgreSQL 默认强制外键，MySQL 用 FOREIGN_KEY_CHECKS）
-- 表按外键依赖拓扑排序；带 PRIMARY KEY 的列一律 NOT NULL。

CREATE TABLE user_profile (
  id TEXT NOT NULL PRIMARY KEY,
  display_name TEXT NOT NULL,
  current_title TEXT,
  work_start_date TEXT,
  summary TEXT,
  email TEXT,
  phone TEXT,
  current_company TEXT,
  current_title_start_date TEXT,
  target_position TEXT,
  location_city TEXT,
  industry TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE attachment (
  id TEXT NOT NULL PRIMARY KEY,
  owner_type TEXT NOT NULL CHECK (owner_type IN ('user_profile', 'attachment', 'work_domain', 'dictionary', 'dict_item', 'tag', 'tag_link', 'provenance_link', 'entity_relation', 'audit_log', 'source_document', 'source_fragment', 'import_batch', 'project', 'business_system', 'function_module', 'work_item', 'work_theme', 'theme_member', 'role_record', 'achievement_case', 'achievement_metric', 'achievement_item_link', 'capability_evidence', 'evidence_evaluation', 'evaluation_dimension', 'evaluation_level', 'capability_category', 'capability', 'capability_alias', 'personal_trait', 'trait_evidence', 'self_assessment', 'growth_stage', 'growth_snapshot', 'growth_goal', 'material', 'material_citation', 'ai_job', 'change_proposal', 'proposal_evidence', 'prompt_template', 'agent_workflow', 'agent_credential', 'backup_record')),
  owner_id TEXT NOT NULL,
  file_name TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  content_hash TEXT,
  mime_type TEXT,
  file_size INTEGER CHECK (file_size >= 0),
  page_count INTEGER CHECK (page_count >= 0),
  storage_backend TEXT,
  thumbnail_path TEXT,
  file_modified_at TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE work_domain (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  parent_id TEXT REFERENCES work_domain(id),
  description TEXT,
  code TEXT,
  is_system INTEGER DEFAULT 0 CHECK (is_system IN (0, 1)),
  is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1)),
  sort_order INTEGER DEFAULT 0 CHECK (sort_order >= 0),
  aliases TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE dictionary (
  id TEXT NOT NULL PRIMARY KEY,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
  description TEXT,
  scope TEXT,
  is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1)),
  sort_order INTEGER DEFAULT 0 CHECK (sort_order >= 0),
  is_ai_extendable INTEGER DEFAULT 0 CHECK (is_ai_extendable IN (0, 1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE entity_relation (
  id TEXT NOT NULL PRIMARY KEY,
  from_type TEXT NOT NULL CHECK (from_type IN ('user_profile', 'attachment', 'work_domain', 'dictionary', 'dict_item', 'tag', 'tag_link', 'provenance_link', 'entity_relation', 'audit_log', 'source_document', 'source_fragment', 'import_batch', 'project', 'business_system', 'function_module', 'work_item', 'work_theme', 'theme_member', 'role_record', 'achievement_case', 'achievement_metric', 'achievement_item_link', 'capability_evidence', 'evidence_evaluation', 'evaluation_dimension', 'evaluation_level', 'capability_category', 'capability', 'capability_alias', 'personal_trait', 'trait_evidence', 'self_assessment', 'growth_stage', 'growth_snapshot', 'growth_goal', 'material', 'material_citation', 'ai_job', 'change_proposal', 'proposal_evidence', 'prompt_template', 'agent_workflow', 'agent_credential', 'backup_record')),
  from_id TEXT NOT NULL,
  to_type TEXT NOT NULL CHECK (to_type IN ('user_profile', 'attachment', 'work_domain', 'dictionary', 'dict_item', 'tag', 'tag_link', 'provenance_link', 'entity_relation', 'audit_log', 'source_document', 'source_fragment', 'import_batch', 'project', 'business_system', 'function_module', 'work_item', 'work_theme', 'theme_member', 'role_record', 'achievement_case', 'achievement_metric', 'achievement_item_link', 'capability_evidence', 'evidence_evaluation', 'evaluation_dimension', 'evaluation_level', 'capability_category', 'capability', 'capability_alias', 'personal_trait', 'trait_evidence', 'self_assessment', 'growth_stage', 'growth_snapshot', 'growth_goal', 'material', 'material_citation', 'ai_job', 'change_proposal', 'proposal_evidence', 'prompt_template', 'agent_workflow', 'agent_credential', 'backup_record')),
  to_id TEXT NOT NULL,
  relation_type TEXT NOT NULL CHECK (relation_type IN ('contains', 'belongs_to', 'relates_to', 'derived_from', 'evidences', 'merged_into', 'split_from', 'duplicate_of', 'replaced_by')),
  strength REAL CHECK (strength BETWEEN 0 AND 1),
  is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1)),
  basis_text TEXT,
  valid_from TEXT,
  valid_to TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE import_batch (
  id TEXT NOT NULL PRIMARY KEY,
  source_channel TEXT NOT NULL CHECK (source_channel IN ('file_upload', 'manual_input', 'paste', 'agent_api', 'email', 'third_party_import', 'feishu')),
  file_count INTEGER DEFAULT 0 CHECK (file_count >= 0),
  success_count INTEGER DEFAULT 0 CHECK (success_count >= 0),
  failed_count INTEGER DEFAULT 0 CHECK (failed_count >= 0),
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  initiated_by TEXT DEFAULT 'user' CHECK (initiated_by IN ('user', 'ai_agent', 'system')),
  started_at TEXT,
  finished_at TEXT,
  failure_reason TEXT,
  duplicate_count INTEGER DEFAULT 0 CHECK (duplicate_count >= 0),
  total_size_bytes INTEGER DEFAULT 0 CHECK (total_size_bytes >= 0),
  batch_label TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE role_record (
  id TEXT NOT NULL PRIMARY KEY,
  target_type TEXT NOT NULL CHECK (target_type IN ('user_profile', 'attachment', 'work_domain', 'dictionary', 'dict_item', 'tag', 'tag_link', 'provenance_link', 'entity_relation', 'audit_log', 'source_document', 'source_fragment', 'import_batch', 'project', 'business_system', 'function_module', 'work_item', 'work_theme', 'theme_member', 'role_record', 'achievement_case', 'achievement_metric', 'achievement_item_link', 'capability_evidence', 'evidence_evaluation', 'evaluation_dimension', 'evaluation_level', 'capability_category', 'capability', 'capability_alias', 'personal_trait', 'trait_evidence', 'self_assessment', 'growth_stage', 'growth_snapshot', 'growth_goal', 'material', 'material_citation', 'ai_job', 'change_proposal', 'proposal_evidence', 'prompt_template', 'agent_workflow', 'agent_credential', 'backup_record')),
  target_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('lead', 'owner', 'core', 'participant', 'support', 'observer')),
  responsibility_scope TEXT,
  contribution_description TEXT,
  start_date TEXT NOT NULL,
  end_date TEXT,
  date_precision TEXT DEFAULT 'month' CHECK (date_precision IN ('day', 'week', 'month', 'quarter', 'year', 'unknown')),
  contribution_evidence TEXT,
  role_change_reason TEXT,
  is_ongoing INTEGER NOT NULL DEFAULT 0 CHECK (is_ongoing IN (0, 1)),
  previous_record_id TEXT REFERENCES role_record(id),
  is_primary_role INTEGER NOT NULL DEFAULT 0 CHECK (is_primary_role IN (0, 1)),
  target_label TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE evaluation_dimension (
  id TEXT NOT NULL PRIMARY KEY,
  code TEXT NOT NULL CHECK (code IN ('complexity', 'autonomy', 'responsibility_scope', 'outcome_quality')),
  name TEXT NOT NULL,
  definition TEXT NOT NULL,
  sort_order INTEGER DEFAULT 0 CHECK (sort_order >= 0),
  applies_to TEXT,
  scoring_guidance TEXT,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  source_reference TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE evaluation_level (
  id TEXT NOT NULL PRIMARY KEY,
  dimension_code TEXT NOT NULL CHECK (dimension_code IN ('complexity', 'autonomy', 'responsibility_scope', 'outcome_quality')),
  level_value INTEGER NOT NULL CHECK (level_value BETWEEN 1 AND 5),
  label TEXT NOT NULL,
  criteria TEXT NOT NULL,
  examples TEXT,
  counter_examples TEXT,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  effective_from TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE capability_category (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  parent_id TEXT REFERENCES capability_category(id),
  description TEXT,
  sort_order INTEGER DEFAULT 0 CHECK (sort_order >= 0),
  category_path TEXT,
  level_depth INTEGER CHECK (level_depth >= 1),
  is_assignable INTEGER DEFAULT 1 CHECK (is_assignable IN (0, 1)),
  merged_into_id TEXT REFERENCES capability_category(id),
  category_boundary_note TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE personal_trait (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  trait_type TEXT NOT NULL CHECK (trait_type IN ('work_style', 'thinking_pattern', 'behavior_habit', 'task_handling', 'communication', 'problem_solving', 'decision_making', 'interest')),
  description TEXT,
  polarity TEXT NOT NULL DEFAULT 'neutral' CHECK (polarity IN ('strength', 'neutral', 'improvement')),
  support_count INTEGER DEFAULT 0 CHECK (support_count >= 0),
  counter_count INTEGER DEFAULT 0 CHECK (counter_count >= 0),
  first_observed_at TEXT,
  last_observed_at TEXT,
  user_note TEXT,
  applicable_context TEXT,
  risk_note TEXT,
  observation_span_months INTEGER CHECK (observation_span_months >= 0),
  display_order INTEGER DEFAULT 0 CHECK (display_order >= 0),
  merged_into_id TEXT REFERENCES personal_trait(id),
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  is_fact INTEGER NOT NULL DEFAULT 1 CHECK (is_fact IN (0, 1)),
  fact_basis TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE prompt_template (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  job_type TEXT NOT NULL CHECK (job_type IN ('document_extract', 'entity_link', 'theme_merge', 'achievement_extract', 'capability_evidence', 'portrait_analysis', 'growth_analysis', 'material_generate', 'dictionary_build')),
  version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
  system_prompt TEXT NOT NULL,
  user_prompt_template TEXT NOT NULL,
  variables TEXT,
  output_schema TEXT,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  target_models TEXT,
  output_format_note TEXT,
  eval_metrics TEXT,
  applies_to_scopes TEXT,
  parent_template_id TEXT REFERENCES prompt_template(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE agent_credential (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  token_hash TEXT NOT NULL,
  client_type TEXT NOT NULL CHECK (client_type IN ('mcp', 'cli', 'rest_api', 'web')),
  scopes TEXT NOT NULL,
  last_used_at TEXT,
  revoked_at TEXT,
  expires_at TEXT,
  rate_limit_per_minute INTEGER DEFAULT 60 CHECK (rate_limit_per_minute >= 0),
  usage_count INTEGER DEFAULT 0 CHECK (usage_count >= 0),
  rotation_due_at TEXT,
  revoke_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE backup_record (
  id TEXT NOT NULL PRIMARY KEY,
  operation_type TEXT NOT NULL CHECK (operation_type IN ('export', 'backup', 'restore', 'migrate')),
  scope TEXT NOT NULL,
  format TEXT,
  file_path TEXT,
  checksum TEXT,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  started_at TEXT,
  finished_at TEXT,
  record_count INTEGER CHECK (record_count >= 0),
  size_bytes INTEGER CHECK (size_bytes >= 0),
  duration_ms INTEGER CHECK (duration_ms >= 0),
  entity_counts TEXT,
  restore_verification TEXT,
  is_encrypted INTEGER DEFAULT 0 CHECK (is_encrypted IN (0, 1)),
  encryption_note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE dict_item (
  id TEXT NOT NULL PRIMARY KEY,
  dictionary_id TEXT NOT NULL REFERENCES dictionary(id),
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  parent_id TEXT REFERENCES dict_item(id),
  sort_order INTEGER DEFAULT 0 CHECK (sort_order >= 0),
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  description TEXT,
  aliases TEXT,
  is_default INTEGER DEFAULT 0 CHECK (is_default IN (0, 1)),
  merged_into_id TEXT REFERENCES dict_item(id),
  external_ref TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE source_document (
  id TEXT NOT NULL PRIMARY KEY,
  title TEXT NOT NULL,
  doc_type TEXT NOT NULL CHECK (doc_type IN ('weekly_report', 'monthly_report', 'work_summary', 'project_doc', 'requirement_doc', 'product_plan', 'system_record', 'work_log', 'achievement_note', 'personal_note', 'other')),
  source_channel TEXT NOT NULL CHECK (source_channel IN ('file_upload', 'manual_input', 'paste', 'agent_api', 'email', 'third_party_import', 'feishu')),
  period_start TEXT,
  period_end TEXT,
  raw_text TEXT NOT NULL,
  content_hash TEXT,
  attachment_id TEXT REFERENCES attachment(id),
  import_batch_id TEXT REFERENCES import_batch(id),
  processing_status TEXT NOT NULL DEFAULT 'pending' CHECK (processing_status IN ('pending', 'extracting', 'extracted', 'reviewing', 'completed', 'failed')),
  duplicate_handling TEXT CHECK (duplicate_handling IN ('skip', 'new_version', 'import_anyway')),
  external_id TEXT,
  external_url TEXT,
  external_updated_at TEXT,
  summary TEXT,
  word_count INTEGER CHECK (word_count >= 0),
  language TEXT,
  source_created_at TEXT,
  duplicate_of_id TEXT REFERENCES source_document(id),
  version_no INTEGER DEFAULT 1 CHECK (version_no >= 1),
  processing_error TEXT,
  archive_note TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE project (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  alias_names TEXT,
  background TEXT,
  goal TEXT,
  status TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN ('planning', 'active', 'launched', 'maintaining', 'closed', 'paused', 'unknown')),
  project_type TEXT CHECK (project_type IN ('new_build', 'enhancement', 'maintenance', 'research', 'process', 'support', 'other')),
  start_date TEXT,
  end_date TEXT,
  domain_id TEXT REFERENCES work_domain(id),
  my_role TEXT CHECK (my_role IN ('lead', 'owner', 'core', 'participant', 'support', 'observer')),
  responsibility_scope TEXT,
  contribution_summary TEXT,
  outcome_summary TEXT,
  importance_level INTEGER CHECK (importance_level BETWEEN 1 AND 5),
  project_code TEXT,
  external_refs TEXT,
  team_size INTEGER CHECK (team_size >= 1),
  milestones TEXT,
  tech_stack TEXT,
  is_representative INTEGER NOT NULL DEFAULT 0 CHECK (is_representative IN (0, 1)),
  merged_from_ids TEXT,
  consolidation_note TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  is_fact INTEGER NOT NULL DEFAULT 1 CHECK (is_fact IN (0, 1)),
  fact_basis TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE business_system (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  alias_names TEXT,
  system_type TEXT NOT NULL DEFAULT 'business_system' CHECK (system_type IN ('business_system', 'product', 'platform', 'middle_platform', 'tool', 'data_system', 'other')),
  description TEXT,
  domain_id TEXT REFERENCES work_domain(id),
  status TEXT DEFAULT 'unknown' CHECK (status IN ('planning', 'building', 'online', 'maintaining', 'offline', 'unknown')),
  start_date TEXT,
  end_date TEXT,
  my_role TEXT CHECK (my_role IN ('lead', 'owner', 'core', 'participant', 'support', 'observer')),
  responsibility_scope TEXT,
  system_code TEXT,
  external_refs TEXT,
  user_scale TEXT,
  milestones TEXT,
  tech_stack TEXT,
  is_representative INTEGER NOT NULL DEFAULT 0 CHECK (is_representative IN (0, 1)),
  merged_from_ids TEXT,
  consolidation_note TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  is_fact INTEGER NOT NULL DEFAULT 1 CHECK (is_fact IN (0, 1)),
  fact_basis TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE capability (
  id TEXT NOT NULL PRIMARY KEY,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  category_id TEXT NOT NULL REFERENCES capability_category(id),
  definition TEXT NOT NULL,
  evaluation_reference TEXT,
  level_scale_note TEXT,
  source_type TEXT NOT NULL DEFAULT 'builtin' CHECK (source_type IN ('builtin', 'user', 'ai_suggested')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deprecated')),
  is_core INTEGER NOT NULL DEFAULT 0 CHECK (is_core IN (0, 1)),
  framework_name TEXT,
  capability_level_rank INTEGER CHECK (capability_level_rank BETWEEN 1 AND 5),
  typical_behavior TEXT,
  misuse_boundary_note TEXT,
  job_role_relation_note TEXT,
  status_changed_at TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE trait_evidence (
  id TEXT NOT NULL PRIMARY KEY,
  trait_id TEXT NOT NULL REFERENCES personal_trait(id),
  direction TEXT NOT NULL CHECK (direction IN ('support', 'counter')),
  target_type TEXT NOT NULL CHECK (target_type IN ('work_item', 'project', 'business_system', 'function_module', 'achievement_case', 'role_record', 'work_theme', 'achievement_metric')),
  target_id TEXT NOT NULL,
  statement TEXT NOT NULL,
  weight INTEGER CHECK (weight BETWEEN 1 AND 5),
  occurred_at TEXT,
  recorded_by TEXT NOT NULL DEFAULT 'user' CHECK (recorded_by IN ('user', 'ai_agent', 'system')),
  is_adopted INTEGER DEFAULT 0 CHECK (is_adopted IN (0, 1)),
  adopted_at TEXT,
  reject_reason TEXT,
  observation_context TEXT,
  weight_basis TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE agent_workflow (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  job_type TEXT NOT NULL CHECK (job_type IN ('document_extract', 'entity_link', 'theme_merge', 'achievement_extract', 'capability_evidence', 'portrait_analysis', 'growth_analysis', 'material_generate', 'dictionary_build')),
  description TEXT,
  steps TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
  target_models TEXT,
  output_constraints TEXT,
  eval_metrics TEXT,
  applies_to_scopes TEXT,
  parent_workflow_id TEXT REFERENCES agent_workflow(id),
  default_prompt_template_id TEXT REFERENCES prompt_template(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE tag (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  category_item_id TEXT REFERENCES dict_item(id),
  description TEXT,
  is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1)),
  sort_order INTEGER DEFAULT 0 CHECK (sort_order >= 0),
  applicable_entity_types TEXT,
  aliases TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE source_fragment (
  id TEXT NOT NULL PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES source_document(id),
  order_index INTEGER NOT NULL CHECK (order_index >= 0),
  fragment_type TEXT NOT NULL CHECK (fragment_type IN ('heading', 'paragraph', 'list_item', 'table_row', 'quote', 'code', 'other')),
  heading_path TEXT,
  text TEXT NOT NULL,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL CHECK (char_end >= 1),
  parse_confidence REAL CHECK (parse_confidence BETWEEN 0 AND 1),
  page_no INTEGER CHECK (page_no >= 1),
  anchor_selector TEXT,
  text_hash TEXT,
  heading_level INTEGER CHECK (heading_level >= 1),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE function_module (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  system_id TEXT NOT NULL REFERENCES business_system(id),
  parent_module_id TEXT REFERENCES function_module(id),
  module_type TEXT DEFAULT 'business' CHECK (module_type IN ('core', 'business', 'technical', 'admin', 'data', 'other')),
  description TEXT,
  my_role TEXT CHECK (my_role IN ('lead', 'owner', 'core', 'participant', 'support', 'observer')),
  start_date TEXT,
  end_date TEXT,
  module_code TEXT,
  alias_names TEXT,
  external_refs TEXT,
  scale_note TEXT,
  milestones TEXT,
  tech_stack TEXT,
  is_representative INTEGER NOT NULL DEFAULT 0 CHECK (is_representative IN (0, 1)),
  merged_from_ids TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  is_fact INTEGER NOT NULL DEFAULT 1 CHECK (is_fact IN (0, 1)),
  fact_basis TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE work_theme (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  theme_type TEXT NOT NULL DEFAULT 'system_building' CHECK (theme_type IN ('system_building', 'project', 'domain', 'role', 'other')),
  description TEXT,
  domain_id TEXT REFERENCES work_domain(id),
  project_id TEXT REFERENCES project(id),
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'paused', 'ended')),
  first_seen_at TEXT,
  last_seen_at TEXT,
  summary TEXT,
  merge_similarity REAL CHECK (merge_similarity BETWEEN 0 AND 1),
  merge_method TEXT,
  merge_candidate_items TEXT,
  merge_rejected_items TEXT,
  key_evidence_ids TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  is_fact INTEGER NOT NULL DEFAULT 1 CHECK (is_fact IN (0, 1)),
  fact_basis TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE capability_evidence (
  id TEXT NOT NULL PRIMARY KEY,
  capability_id TEXT NOT NULL REFERENCES capability(id),
  evidence_type TEXT NOT NULL CHECK (evidence_type IN ('responsibility', 'performance', 'complexity', 'contribution')),
  target_type TEXT NOT NULL CHECK (target_type IN ('work_item', 'project', 'business_system', 'function_module', 'achievement_case', 'role_record', 'work_theme', 'achievement_metric')),
  target_id TEXT NOT NULL,
  statement TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  strength INTEGER CHECK (strength BETWEEN 1 AND 5),
  strength_basis TEXT,
  aspect_focus TEXT,
  is_supplement_needed INTEGER NOT NULL DEFAULT 0 CHECK (is_supplement_needed IN (0, 1)),
  supplement_note TEXT,
  confirmation_note TEXT,
  counter_note TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  is_fact INTEGER NOT NULL DEFAULT 1 CHECK (is_fact IN (0, 1)),
  fact_basis TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE capability_alias (
  id TEXT NOT NULL PRIMARY KEY,
  capability_id TEXT NOT NULL REFERENCES capability(id),
  alias TEXT NOT NULL,
  normalized_alias TEXT,
  language TEXT,
  usage_count INTEGER DEFAULT 0 CHECK (usage_count >= 0),
  last_matched_at TEXT,
  is_preferred INTEGER DEFAULT 0 CHECK (is_preferred IN (0, 1)),
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE self_assessment (
  id TEXT NOT NULL PRIMARY KEY,
  scope TEXT NOT NULL CHECK (scope IN ('overall', 'capability', 'trait', 'growth_stage')),
  target_id TEXT,
  content TEXT NOT NULL,
  assessment_source TEXT NOT NULL DEFAULT 'user' CHECK (assessment_source IN ('user', 'ai_draft')),
  trigger_context TEXT,
  is_portrait_visible INTEGER DEFAULT 1 CHECK (is_portrait_visible IN (0, 1)),
  follow_up_note TEXT,
  origin_document_id TEXT REFERENCES source_document(id),
  self_rating INTEGER CHECK (self_rating BETWEEN 1 AND 5),
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE growth_goal (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  goal_type TEXT NOT NULL DEFAULT 'capability' CHECK (goal_type IN ('capability', 'experience', 'output', 'completeness', 'habit', 'other')),
  description TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('proposed', 'active', 'paused', 'achieved', 'abandoned')),
  start_date TEXT NOT NULL,
  end_date TEXT,
  date_precision TEXT DEFAULT 'month' CHECK (date_precision IN ('day', 'week', 'month', 'quarter', 'year', 'unknown')),
  progress_percent INTEGER NOT NULL DEFAULT 0 CHECK (progress_percent BETWEEN 0 AND 100),
  success_criteria TEXT,
  measurement_note TEXT,
  progress_note TEXT,
  related_project_id TEXT REFERENCES project(id),
  related_domain_id TEXT REFERENCES work_domain(id),
  related_capability_id TEXT REFERENCES capability(id),
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  is_fact INTEGER NOT NULL DEFAULT 1 CHECK (is_fact IN (0, 1)),
  fact_basis TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE ai_job (
  id TEXT NOT NULL PRIMARY KEY,
  job_type TEXT NOT NULL CHECK (job_type IN ('document_extract', 'entity_link', 'theme_merge', 'achievement_extract', 'capability_evidence', 'portrait_analysis', 'growth_analysis', 'material_generate', 'dictionary_build')),
  trigger_type TEXT NOT NULL DEFAULT 'manual' CHECK (trigger_type IN ('manual', 'scheduled', 'agent_api', 'system')),
  input_scope TEXT NOT NULL,
  model_provider TEXT,
  model_name TEXT,
  prompt_template_id TEXT REFERENCES prompt_template(id),
  workflow_id TEXT REFERENCES agent_workflow(id),
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  started_at TEXT,
  finished_at TEXT,
  error_message TEXT,
  result_summary TEXT,
  duration_ms INTEGER CHECK (duration_ms >= 0),
  token_usage TEXT,
  cost_amount REAL DEFAULT 0 CHECK (cost_amount >= 0),
  input_fragment_count INTEGER CHECK (input_fragment_count >= 0),
  proposal_count INTEGER DEFAULT 0 CHECK (proposal_count >= 0),
  retry_count INTEGER DEFAULT 0 CHECK (retry_count >= 0),
  error_code TEXT CHECK (error_code IN ('parse_failed', 'model_error', 'timeout', 'rate_limited', 'invalid_input', 'conflict', 'unknown')),
  parent_job_id TEXT REFERENCES ai_job(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE tag_link (
  id TEXT NOT NULL PRIMARY KEY,
  tag_id TEXT NOT NULL REFERENCES tag(id),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('user_profile', 'attachment', 'work_domain', 'dictionary', 'dict_item', 'tag', 'tag_link', 'provenance_link', 'entity_relation', 'audit_log', 'source_document', 'source_fragment', 'import_batch', 'project', 'business_system', 'function_module', 'work_item', 'work_theme', 'theme_member', 'role_record', 'achievement_case', 'achievement_metric', 'achievement_item_link', 'capability_evidence', 'evidence_evaluation', 'evaluation_dimension', 'evaluation_level', 'capability_category', 'capability', 'capability_alias', 'personal_trait', 'trait_evidence', 'self_assessment', 'growth_stage', 'growth_snapshot', 'growth_goal', 'material', 'material_citation', 'ai_job', 'change_proposal', 'proposal_evidence', 'prompt_template', 'agent_workflow', 'agent_credential', 'backup_record')),
  entity_id TEXT NOT NULL,
  link_source TEXT DEFAULT 'user' CHECK (link_source IN ('user', 'ai_agent', 'import', 'system')),
  is_primary INTEGER DEFAULT 0 CHECK (is_primary IN (0, 1)),
  reason TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE provenance_link (
  id TEXT NOT NULL PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('user_profile', 'attachment', 'work_domain', 'dictionary', 'dict_item', 'tag', 'tag_link', 'provenance_link', 'entity_relation', 'audit_log', 'source_document', 'source_fragment', 'import_batch', 'project', 'business_system', 'function_module', 'work_item', 'work_theme', 'theme_member', 'role_record', 'achievement_case', 'achievement_metric', 'achievement_item_link', 'capability_evidence', 'evidence_evaluation', 'evaluation_dimension', 'evaluation_level', 'capability_category', 'capability', 'capability_alias', 'personal_trait', 'trait_evidence', 'self_assessment', 'growth_stage', 'growth_snapshot', 'growth_goal', 'material', 'material_citation', 'ai_job', 'change_proposal', 'proposal_evidence', 'prompt_template', 'agent_workflow', 'agent_credential', 'backup_record')),
  entity_id TEXT NOT NULL,
  field_name TEXT,
  fragment_id TEXT NOT NULL REFERENCES source_fragment(id),
  relation_type TEXT NOT NULL DEFAULT 'primary_source' CHECK (relation_type IN ('primary_source', 'supporting', 'contradicting', 'inferred', 'metric_source', 'citation', 'merged_from', 'split_from', 'imported_from')),
  quote_text TEXT,
  match_method TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE work_item (
  id TEXT NOT NULL PRIMARY KEY,
  title TEXT NOT NULL,
  item_type TEXT NOT NULL CHECK (item_type IN ('requirement_analysis', 'solution_design', 'development', 'testing', 'release', 'operations', 'issue_handling', 'communication', 'documentation', 'review', 'research', 'coordination', 'management', 'other')),
  content TEXT NOT NULL,
  problem_background TEXT,
  process TEXT,
  result TEXT,
  my_role TEXT CHECK (my_role IN ('lead', 'owner', 'core', 'participant', 'support', 'observer')),
  complexity_level INTEGER CHECK (complexity_level BETWEEN 1 AND 5),
  is_routine INTEGER NOT NULL DEFAULT 0 CHECK (is_routine IN (0, 1)),
  occurred_at TEXT NOT NULL,
  date_precision TEXT NOT NULL DEFAULT 'day' CHECK (date_precision IN ('day', 'week', 'month', 'quarter', 'year', 'unknown')),
  project_id TEXT REFERENCES project(id),
  system_id TEXT REFERENCES business_system(id),
  module_id TEXT REFERENCES function_module(id),
  domain_id TEXT REFERENCES work_domain(id),
  source_document_id TEXT REFERENCES source_document(id),
  effort_hours REAL CHECK (effort_hours >= 0),
  deliverables TEXT,
  complexity_basis TEXT,
  collaborators TEXT,
  is_follow_up_needed INTEGER NOT NULL DEFAULT 0 CHECK (is_follow_up_needed IN (0, 1)),
  follow_up_note TEXT,
  follow_up_at TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  is_fact INTEGER NOT NULL DEFAULT 1 CHECK (is_fact IN (0, 1)),
  fact_basis TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE theme_member (
  id TEXT NOT NULL PRIMARY KEY,
  theme_id TEXT NOT NULL REFERENCES work_theme(id),
  member_type TEXT NOT NULL CHECK (member_type IN ('work_item', 'achievement_case', 'source_document')),
  member_id TEXT NOT NULL,
  relation_type TEXT NOT NULL DEFAULT 'primary' CHECK (relation_type IN ('primary', 'secondary')),
  similarity_score REAL CHECK (similarity_score BETWEEN 0 AND 1),
  match_reason TEXT,
  added_by_job_id TEXT REFERENCES ai_job(id),
  evidence_fragment_id TEXT REFERENCES source_fragment(id),
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE achievement_case (
  id TEXT NOT NULL PRIMARY KEY,
  title TEXT NOT NULL,
  case_type TEXT NOT NULL CHECK (case_type IN ('project_delivery', 'issue_resolution', 'efficiency_improvement', 'business_growth', 'technical_innovation', 'process_building', 'cost_reduction', 'other')),
  background TEXT,
  problem TEXT,
  action TEXT,
  implementation TEXT,
  result TEXT,
  business_impact TEXT,
  personal_contribution TEXT,
  my_role TEXT NOT NULL DEFAULT 'participant' CHECK (my_role IN ('lead', 'owner', 'core', 'participant', 'support', 'observer')),
  team_contribution TEXT,
  experience_summary TEXT,
  project_id TEXT REFERENCES project(id),
  system_id TEXT REFERENCES business_system(id),
  module_id TEXT REFERENCES function_module(id),
  domain_id TEXT REFERENCES work_domain(id),
  occurred_at TEXT NOT NULL,
  date_precision TEXT NOT NULL DEFAULT 'month' CHECK (date_precision IN ('day', 'week', 'month', 'quarter', 'year', 'unknown')),
  value_level INTEGER CHECK (value_level BETWEEN 1 AND 5),
  is_resume_ready INTEGER NOT NULL DEFAULT 0 CHECK (is_resume_ready IN (0, 1)),
  highlight TEXT,
  applicable_scenarios TEXT,
  is_disclosable INTEGER NOT NULL DEFAULT 0 CHECK (is_disclosable IN (0, 1)),
  disclosure_note TEXT,
  limitations TEXT,
  is_result_verified INTEGER NOT NULL DEFAULT 0 CHECK (is_result_verified IN (0, 1)),
  reuse_notes TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  is_fact INTEGER NOT NULL DEFAULT 1 CHECK (is_fact IN (0, 1)),
  fact_basis TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE evidence_evaluation (
  id TEXT NOT NULL PRIMARY KEY,
  evidence_id TEXT REFERENCES capability_evidence(id),
  dimension_code TEXT NOT NULL CHECK (dimension_code IN ('complexity', 'autonomy', 'responsibility_scope', 'outcome_quality')),
  level_value INTEGER NOT NULL CHECK (level_value BETWEEN 1 AND 5),
  basis_text TEXT NOT NULL,
  evaluated_by TEXT NOT NULL DEFAULT 'ai' CHECK (evaluated_by IN ('ai', 'user')),
  capability_id TEXT REFERENCES capability(id),
  is_aggregate INTEGER NOT NULL DEFAULT 0 CHECK (is_aggregate IN (0, 1)),
  period_start TEXT,
  period_end TEXT,
  covered_evidence_ids TEXT,
  data_coverage_note TEXT,
  is_stale INTEGER NOT NULL DEFAULT 0 CHECK (is_stale IN (0, 1)),
  supersedes_id TEXT REFERENCES evidence_evaluation(id),
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE growth_stage (
  id TEXT NOT NULL PRIMARY KEY,
  name TEXT NOT NULL,
  stage_index INTEGER NOT NULL CHECK (stage_index >= 1),
  stage_type TEXT NOT NULL DEFAULT 'other' CHECK (stage_type IN ('role_change', 'domain_shift', 'capability_leap', 'project_phase', 'organization_change', 'other')),
  start_date TEXT NOT NULL,
  end_date TEXT,
  date_precision TEXT DEFAULT 'month' CHECK (date_precision IN ('day', 'week', 'month', 'quarter', 'year', 'unknown')),
  description TEXT,
  responsibility_summary TEXT,
  capability_summary TEXT,
  division_basis TEXT NOT NULL,
  auto_detected INTEGER NOT NULL DEFAULT 0 CHECK (auto_detected IN (0, 1)),
  theme_summary TEXT,
  key_project_ids TEXT,
  key_achievement_ids TEXT,
  work_domain_ids TEXT,
  detected_by_job_id TEXT REFERENCES ai_job(id),
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  is_fact INTEGER NOT NULL DEFAULT 1 CHECK (is_fact IN (0, 1)),
  fact_basis TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE growth_snapshot (
  id TEXT NOT NULL PRIMARY KEY,
  scope_type TEXT NOT NULL DEFAULT 'global' CHECK (scope_type IN ('global', 'period', 'capability', 'domain', 'project', 'stage')),
  scope_id TEXT,
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  snapshot_at TEXT NOT NULL,
  metrics TEXT NOT NULL,
  data_coverage TEXT NOT NULL,
  metric_definitions TEXT NOT NULL,
  summary_text TEXT,
  analysis_note TEXT,
  generation_trigger TEXT NOT NULL DEFAULT 'manual' CHECK (generation_trigger IN ('manual', 'scheduled', 'agent_api', 'system')),
  sample_basis TEXT,
  dimension_distribution TEXT,
  is_public INTEGER DEFAULT 0 CHECK (is_public IN (0, 1)),
  generated_by_job_id TEXT REFERENCES ai_job(id),
  metrics_version TEXT DEFAULT 'v1',
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE material (
  id TEXT NOT NULL PRIMARY KEY,
  title TEXT NOT NULL,
  material_type TEXT NOT NULL CHECK (material_type IN ('resume', 'project_intro', 'performance_review', 'promotion', 'annual_summary', 'self_intro', 'other')),
  target_position TEXT,
  period_start TEXT,
  period_end TEXT,
  focus_direction TEXT,
  content TEXT,
  content_format TEXT DEFAULT 'markdown',
  version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no >= 1),
  parent_material_id TEXT REFERENCES material(id),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'pending_review', 'confirmed', 'exported', 'archived')),
  job_id TEXT REFERENCES ai_job(id),
  intended_usage TEXT,
  format_requirement TEXT,
  word_limit INTEGER DEFAULT 0 CHECK (word_limit >= 0),
  data_scope_snapshot TEXT,
  is_manually_edited INTEGER DEFAULT 0 CHECK (is_manually_edited IN (0, 1)),
  edited_sections TEXT,
  export_records TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE change_proposal (
  id TEXT NOT NULL PRIMARY KEY,
  job_id TEXT REFERENCES ai_job(id),
  batch_id TEXT,
  change_type TEXT NOT NULL CHECK (change_type IN ('create', 'update', 'merge', 'split', 'delete', 'link', 'unlink')),
  target_entity_type TEXT NOT NULL CHECK (target_entity_type IN ('user_profile', 'attachment', 'work_domain', 'dictionary', 'dict_item', 'tag', 'tag_link', 'provenance_link', 'entity_relation', 'audit_log', 'source_document', 'source_fragment', 'import_batch', 'project', 'business_system', 'function_module', 'work_item', 'work_theme', 'theme_member', 'role_record', 'achievement_case', 'achievement_metric', 'achievement_item_link', 'capability_evidence', 'evidence_evaluation', 'evaluation_dimension', 'evaluation_level', 'capability_category', 'capability', 'capability_alias', 'personal_trait', 'trait_evidence', 'self_assessment', 'growth_stage', 'growth_snapshot', 'growth_goal', 'material', 'material_citation', 'ai_job', 'change_proposal', 'proposal_evidence', 'prompt_template', 'agent_workflow', 'agent_credential', 'backup_record')),
  target_entity_id TEXT,
  proposed_payload TEXT NOT NULL,
  base_payload TEXT,
  diff_summary TEXT NOT NULL,
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'modified', 'rejected', 'superseded', 'expired')),
  reviewer_note TEXT,
  applied_entity_id TEXT,
  applied_at TEXT,
  priority INTEGER DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  impact_scope TEXT,
  final_payload TEXT,
  reviewed_at TEXT,
  review_duration_ms INTEGER CHECK (review_duration_ms >= 0),
  superseded_by_id TEXT REFERENCES change_proposal(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE audit_log (
  id TEXT NOT NULL PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('user_profile', 'attachment', 'work_domain', 'dictionary', 'dict_item', 'tag', 'tag_link', 'provenance_link', 'entity_relation', 'audit_log', 'source_document', 'source_fragment', 'import_batch', 'project', 'business_system', 'function_module', 'work_item', 'work_theme', 'theme_member', 'role_record', 'achievement_case', 'achievement_metric', 'achievement_item_link', 'capability_evidence', 'evidence_evaluation', 'evaluation_dimension', 'evaluation_level', 'capability_category', 'capability', 'capability_alias', 'personal_trait', 'trait_evidence', 'self_assessment', 'growth_stage', 'growth_snapshot', 'growth_goal', 'material', 'material_citation', 'ai_job', 'change_proposal', 'proposal_evidence', 'prompt_template', 'agent_workflow', 'agent_credential', 'backup_record')),
  entity_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('create', 'update', 'merge', 'split', 'delete', 'confirm', 'reject', 'export', 'import', 'restore')),
  before_payload TEXT,
  after_payload TEXT,
  actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'ai_agent', 'system')),
  proposal_id TEXT REFERENCES change_proposal(id),
  job_id TEXT REFERENCES ai_job(id),
  occurred_at TEXT NOT NULL,
  client_type TEXT CHECK (client_type IN ('mcp', 'cli', 'rest_api', 'web')),
  client_ip TEXT,
  client_agent TEXT,
  batch_id TEXT,
  actor_credential_id TEXT REFERENCES agent_credential(id),
  remark TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE achievement_metric (
  id TEXT NOT NULL PRIMARY KEY,
  achievement_id TEXT NOT NULL REFERENCES achievement_case(id),
  metric_name TEXT NOT NULL,
  metric_value TEXT NOT NULL,
  unit TEXT,
  baseline_value TEXT,
  measurement_method TEXT,
  is_verified INTEGER NOT NULL DEFAULT 0 CHECK (is_verified IN (0, 1)),
  stat_period_start TEXT,
  stat_period_end TEXT,
  data_source TEXT,
  verified_by TEXT,
  verified_at TEXT,
  baseline_period TEXT,
  baseline_type TEXT,
  is_estimate INTEGER NOT NULL DEFAULT 0 CHECK (is_estimate IN (0, 1)),
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  is_fact INTEGER NOT NULL DEFAULT 1 CHECK (is_fact IN (0, 1)),
  fact_basis TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE achievement_item_link (
  id TEXT NOT NULL PRIMARY KEY,
  achievement_id TEXT NOT NULL REFERENCES achievement_case(id),
  work_item_id TEXT NOT NULL REFERENCES work_item(id),
  relation_type TEXT NOT NULL DEFAULT 'evidence' CHECK (relation_type IN ('evidence', 'derived_from')),
  link_reason TEXT,
  similarity_score REAL CHECK (similarity_score BETWEEN 0 AND 1),
  added_by_job_id TEXT REFERENCES ai_job(id),
  contribution_weight REAL CHECK (contribution_weight BETWEEN 0 AND 1),
  evidence_fragment_id TEXT REFERENCES source_fragment(id),
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE material_citation (
  id TEXT NOT NULL PRIMARY KEY,
  material_id TEXT NOT NULL REFERENCES material(id),
  section_key TEXT NOT NULL DEFAULT 'body',
  snippet TEXT,
  cited_entity_type TEXT NOT NULL CHECK (cited_entity_type IN ('user_profile', 'attachment', 'work_domain', 'dictionary', 'dict_item', 'tag', 'tag_link', 'provenance_link', 'entity_relation', 'audit_log', 'source_document', 'source_fragment', 'import_batch', 'project', 'business_system', 'function_module', 'work_item', 'work_theme', 'theme_member', 'role_record', 'achievement_case', 'achievement_metric', 'achievement_item_link', 'capability_evidence', 'evidence_evaluation', 'evaluation_dimension', 'evaluation_level', 'capability_category', 'capability', 'capability_alias', 'personal_trait', 'trait_evidence', 'self_assessment', 'growth_stage', 'growth_snapshot', 'growth_goal', 'material', 'material_citation', 'ai_job', 'change_proposal', 'proposal_evidence', 'prompt_template', 'agent_workflow', 'agent_credential', 'backup_record')),
  cited_entity_id TEXT NOT NULL,
  fragment_id TEXT REFERENCES source_fragment(id),
  citation_type TEXT NOT NULL CHECK (citation_type IN ('work_experience', 'capability', 'achievement', 'metric', 'trait', 'basic_info')),
  paragraph_index INTEGER CHECK (paragraph_index >= 1),
  is_source_verified INTEGER CHECK (is_source_verified IN (0, 1)),
  verification_note TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'ai_agent', 'import', 'system')),
  review_status TEXT NOT NULL DEFAULT 'confirmed' CHECK (review_status IN ('draft', 'pending', 'confirmed', 'rejected', 'superseded')),
  confidence REAL CHECK (confidence BETWEEN 0 AND 1),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

CREATE TABLE proposal_evidence (
  id TEXT NOT NULL PRIMARY KEY,
  proposal_id TEXT NOT NULL REFERENCES change_proposal(id),
  fragment_id TEXT NOT NULL REFERENCES source_fragment(id),
  quote TEXT NOT NULL,
  relevance_type TEXT NOT NULL DEFAULT 'primary_source' CHECK (relevance_type IN ('primary_source', 'supporting', 'contradicting', 'context')),
  quote_char_start INTEGER CHECK (quote_char_start >= 0),
  quote_char_end INTEGER CHECK (quote_char_end >= 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT
);

-- 唯一索引：加 WHERE deleted_at IS NULL，使软删除后可以重建同名记录；
-- 组合键中含非必填列时额外加 WHERE 列 IS NOT NULL，避免 NULL 让唯一性失效。
CREATE UNIQUE INDEX uq_work_domain_name ON work_domain(name) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_work_domain_code ON work_domain(code) WHERE deleted_at IS NULL AND code IS NOT NULL;
CREATE UNIQUE INDEX uq_dictionary_code ON dictionary(code) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_dict_item_dictionary_id_code ON dict_item(dictionary_id, code) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_tag_name ON tag(name) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_tag_link_tag_id_entity_type_entity_id ON tag_link(tag_id, entity_type, entity_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_entity_relation_from_type_from_id_to_type_to_id_relation_type ON entity_relation(from_type, from_id, to_type, to_id, relation_type) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_theme_member_theme_id_member_type_member_id ON theme_member(theme_id, member_type, member_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_achievement_item_link_achievement_id_work_item_id_relation_type ON achievement_item_link(achievement_id, work_item_id, relation_type) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_evidence_evaluation_evidence_id_dimension_code ON evidence_evaluation(evidence_id, dimension_code) WHERE deleted_at IS NULL AND evidence_id IS NOT NULL;
CREATE UNIQUE INDEX uq_evaluation_dimension_code ON evaluation_dimension(code) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_evaluation_level_dimension_code_level_value ON evaluation_level(dimension_code, level_value) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_capability_category_name ON capability_category(name) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_capability_code ON capability(code) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_capability_alias_capability_id_alias ON capability_alias(capability_id, alias) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_material_citation_material_id_section_key_cited_entity_type_cited_entity_id ON material_citation(material_id, section_key, cited_entity_type, cited_entity_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_agent_credential_token_hash ON agent_credential(token_hash) WHERE deleted_at IS NULL;

-- 普通索引
CREATE INDEX idx_user_profile_email ON user_profile(email);
CREATE INDEX idx_attachment_owner_type ON attachment(owner_type);
CREATE INDEX idx_attachment_owner_id ON attachment(owner_id);
CREATE INDEX idx_attachment_content_hash ON attachment(content_hash);
CREATE INDEX idx_dict_item_dictionary_id ON dict_item(dictionary_id);
CREATE INDEX idx_tag_category_item_id ON tag(category_item_id);
CREATE INDEX idx_tag_link_tag_id ON tag_link(tag_id);
CREATE INDEX idx_tag_link_entity_type ON tag_link(entity_type);
CREATE INDEX idx_tag_link_entity_id ON tag_link(entity_id);
CREATE INDEX idx_provenance_link_entity_type ON provenance_link(entity_type);
CREATE INDEX idx_provenance_link_entity_id ON provenance_link(entity_id);
CREATE INDEX idx_provenance_link_fragment_id ON provenance_link(fragment_id);
CREATE INDEX idx_entity_relation_from_type ON entity_relation(from_type);
CREATE INDEX idx_entity_relation_from_id ON entity_relation(from_id);
CREATE INDEX idx_entity_relation_to_type ON entity_relation(to_type);
CREATE INDEX idx_entity_relation_to_id ON entity_relation(to_id);
CREATE INDEX idx_audit_log_entity_type ON audit_log(entity_type);
CREATE INDEX idx_audit_log_entity_id ON audit_log(entity_id);
CREATE INDEX idx_audit_log_occurred_at ON audit_log(occurred_at);
CREATE INDEX idx_audit_log_client_type ON audit_log(client_type);
CREATE INDEX idx_audit_log_batch_id ON audit_log(batch_id);
CREATE INDEX idx_source_document_doc_type ON source_document(doc_type);
CREATE INDEX idx_source_document_content_hash ON source_document(content_hash);
CREATE INDEX idx_source_document_processing_status ON source_document(processing_status);
CREATE INDEX idx_source_document_external_id ON source_document(external_id);
CREATE INDEX idx_source_document_source_created_at ON source_document(source_created_at);
CREATE INDEX idx_source_document_duplicate_of_id ON source_document(duplicate_of_id);
CREATE INDEX idx_source_fragment_document_id ON source_fragment(document_id);
CREATE INDEX idx_source_fragment_text_hash ON source_fragment(text_hash);
CREATE INDEX idx_project_name ON project(name);
CREATE INDEX idx_project_project_type ON project(project_type);
CREATE INDEX idx_project_domain_id ON project(domain_id);
CREATE INDEX idx_project_project_code ON project(project_code);
CREATE INDEX idx_project_is_representative ON project(is_representative);
CREATE INDEX idx_project_is_fact ON project(is_fact);
CREATE INDEX idx_business_system_name ON business_system(name);
CREATE INDEX idx_business_system_domain_id ON business_system(domain_id);
CREATE INDEX idx_business_system_system_code ON business_system(system_code);
CREATE INDEX idx_business_system_is_representative ON business_system(is_representative);
CREATE INDEX idx_business_system_is_fact ON business_system(is_fact);
CREATE INDEX idx_function_module_name ON function_module(name);
CREATE INDEX idx_function_module_system_id ON function_module(system_id);
CREATE INDEX idx_function_module_module_code ON function_module(module_code);
CREATE INDEX idx_function_module_is_representative ON function_module(is_representative);
CREATE INDEX idx_function_module_is_fact ON function_module(is_fact);
CREATE INDEX idx_work_item_item_type ON work_item(item_type);
CREATE INDEX idx_work_item_occurred_at ON work_item(occurred_at);
CREATE INDEX idx_work_item_project_id ON work_item(project_id);
CREATE INDEX idx_work_item_system_id ON work_item(system_id);
CREATE INDEX idx_work_item_module_id ON work_item(module_id);
CREATE INDEX idx_work_item_domain_id ON work_item(domain_id);
CREATE INDEX idx_work_item_source_document_id ON work_item(source_document_id);
CREATE INDEX idx_work_item_is_follow_up_needed ON work_item(is_follow_up_needed);
CREATE INDEX idx_work_item_is_fact ON work_item(is_fact);
CREATE INDEX idx_work_theme_name ON work_theme(name);
CREATE INDEX idx_work_theme_domain_id ON work_theme(domain_id);
CREATE INDEX idx_work_theme_is_fact ON work_theme(is_fact);
CREATE INDEX idx_theme_member_theme_id ON theme_member(theme_id);
CREATE INDEX idx_theme_member_member_type ON theme_member(member_type);
CREATE INDEX idx_theme_member_member_id ON theme_member(member_id);
CREATE INDEX idx_role_record_target_type ON role_record(target_type);
CREATE INDEX idx_role_record_target_id ON role_record(target_id);
CREATE INDEX idx_role_record_is_ongoing ON role_record(is_ongoing);
CREATE INDEX idx_role_record_is_primary_role ON role_record(is_primary_role);
CREATE INDEX idx_achievement_case_case_type ON achievement_case(case_type);
CREATE INDEX idx_achievement_case_my_role ON achievement_case(my_role);
CREATE INDEX idx_achievement_case_project_id ON achievement_case(project_id);
CREATE INDEX idx_achievement_case_system_id ON achievement_case(system_id);
CREATE INDEX idx_achievement_case_domain_id ON achievement_case(domain_id);
CREATE INDEX idx_achievement_case_occurred_at ON achievement_case(occurred_at);
CREATE INDEX idx_achievement_case_is_disclosable ON achievement_case(is_disclosable);
CREATE INDEX idx_achievement_case_is_result_verified ON achievement_case(is_result_verified);
CREATE INDEX idx_achievement_case_is_fact ON achievement_case(is_fact);
CREATE INDEX idx_achievement_metric_achievement_id ON achievement_metric(achievement_id);
CREATE INDEX idx_achievement_metric_is_estimate ON achievement_metric(is_estimate);
CREATE INDEX idx_achievement_metric_is_fact ON achievement_metric(is_fact);
CREATE INDEX idx_achievement_item_link_achievement_id ON achievement_item_link(achievement_id);
CREATE INDEX idx_achievement_item_link_work_item_id ON achievement_item_link(work_item_id);
CREATE INDEX idx_capability_evidence_capability_id ON capability_evidence(capability_id);
CREATE INDEX idx_capability_evidence_target_type ON capability_evidence(target_type);
CREATE INDEX idx_capability_evidence_target_id ON capability_evidence(target_id);
CREATE INDEX idx_capability_evidence_occurred_at ON capability_evidence(occurred_at);
CREATE INDEX idx_capability_evidence_is_supplement_needed ON capability_evidence(is_supplement_needed);
CREATE INDEX idx_capability_evidence_is_fact ON capability_evidence(is_fact);
CREATE INDEX idx_evidence_evaluation_evidence_id ON evidence_evaluation(evidence_id);
CREATE INDEX idx_evidence_evaluation_capability_id ON evidence_evaluation(capability_id);
CREATE INDEX idx_evidence_evaluation_is_aggregate ON evidence_evaluation(is_aggregate);
CREATE INDEX idx_evidence_evaluation_is_stale ON evidence_evaluation(is_stale);
CREATE INDEX idx_evaluation_dimension_is_active ON evaluation_dimension(is_active);
CREATE INDEX idx_evaluation_level_dimension_code ON evaluation_level(dimension_code);
CREATE INDEX idx_evaluation_level_is_active ON evaluation_level(is_active);
CREATE INDEX idx_capability_category_category_path ON capability_category(category_path);
CREATE INDEX idx_capability_name ON capability(name);
CREATE INDEX idx_capability_category_id ON capability(category_id);
CREATE INDEX idx_capability_is_core ON capability(is_core);
CREATE INDEX idx_capability_alias_capability_id ON capability_alias(capability_id);
CREATE INDEX idx_capability_alias_normalized_alias ON capability_alias(normalized_alias);
CREATE INDEX idx_personal_trait_name ON personal_trait(name);
CREATE INDEX idx_personal_trait_trait_type ON personal_trait(trait_type);
CREATE INDEX idx_personal_trait_is_fact ON personal_trait(is_fact);
CREATE INDEX idx_trait_evidence_trait_id ON trait_evidence(trait_id);
CREATE INDEX idx_trait_evidence_target_type ON trait_evidence(target_type);
CREATE INDEX idx_trait_evidence_target_id ON trait_evidence(target_id);
CREATE INDEX idx_growth_stage_start_date ON growth_stage(start_date);
CREATE INDEX idx_growth_stage_is_fact ON growth_stage(is_fact);
CREATE INDEX idx_growth_snapshot_snapshot_at ON growth_snapshot(snapshot_at);
CREATE INDEX idx_growth_goal_name ON growth_goal(name);
CREATE INDEX idx_growth_goal_status ON growth_goal(status);
CREATE INDEX idx_growth_goal_related_project_id ON growth_goal(related_project_id);
CREATE INDEX idx_growth_goal_related_domain_id ON growth_goal(related_domain_id);
CREATE INDEX idx_growth_goal_related_capability_id ON growth_goal(related_capability_id);
CREATE INDEX idx_growth_goal_is_fact ON growth_goal(is_fact);
CREATE INDEX idx_material_material_type ON material(material_type);
CREATE INDEX idx_material_status ON material(status);
CREATE INDEX idx_material_citation_material_id ON material_citation(material_id);
CREATE INDEX idx_material_citation_section_key ON material_citation(section_key);
CREATE INDEX idx_material_citation_cited_entity_type ON material_citation(cited_entity_type);
CREATE INDEX idx_material_citation_cited_entity_id ON material_citation(cited_entity_id);
CREATE INDEX idx_ai_job_job_type ON ai_job(job_type);
CREATE INDEX idx_ai_job_status ON ai_job(status);
CREATE INDEX idx_change_proposal_job_id ON change_proposal(job_id);
CREATE INDEX idx_change_proposal_batch_id ON change_proposal(batch_id);
CREATE INDEX idx_change_proposal_change_type ON change_proposal(change_type);
CREATE INDEX idx_change_proposal_target_entity_type ON change_proposal(target_entity_type);
CREATE INDEX idx_change_proposal_status ON change_proposal(status);
CREATE INDEX idx_change_proposal_priority ON change_proposal(priority);
CREATE INDEX idx_proposal_evidence_proposal_id ON proposal_evidence(proposal_id);
CREATE INDEX idx_proposal_evidence_fragment_id ON proposal_evidence(fragment_id);
CREATE INDEX idx_prompt_template_job_type ON prompt_template(job_type);
CREATE INDEX idx_agent_workflow_job_type ON agent_workflow(job_type);
CREATE INDEX idx_backup_record_operation_type ON backup_record(operation_type);

-- 多态引用复合索引（entity_type + entity_id 成对查询）
CREATE INDEX idx_attachment_owner_type_owner_id ON attachment(owner_type, owner_id);
CREATE INDEX idx_tag_link_entity_type_entity_id ON tag_link(entity_type, entity_id);
CREATE INDEX idx_provenance_link_entity_type_entity_id ON provenance_link(entity_type, entity_id);
CREATE INDEX idx_entity_relation_from_type_from_id ON entity_relation(from_type, from_id);
CREATE INDEX idx_entity_relation_to_type_to_id ON entity_relation(to_type, to_id);
CREATE INDEX idx_audit_log_entity_type_entity_id ON audit_log(entity_type, entity_id);
CREATE INDEX idx_role_record_target_type_target_id ON role_record(target_type, target_id);
CREATE INDEX idx_material_citation_cited_entity_type_cited_entity_id ON material_citation(cited_entity_type, cited_entity_id);
CREATE INDEX idx_change_proposal_target_entity_type_target_entity_id ON change_proposal(target_entity_type, target_entity_id);

-- 只追加表的写保护（规则 A1：审计记录只增不改不删，在数据库层强制）
CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN
  SELECT RAISE(ABORT, 'audit_log 是只追加表，不允许 UPDATE');
END;
CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN
  SELECT RAISE(ABORT, 'audit_log 是只追加表，不允许 DELETE');
END;
