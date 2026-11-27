/** 与 schema 中 work_item.item_type 的 14 个枚举值一一对应（schema/schema.sql:712） */
export const ITEM_TYPE_LABEL: Record<string, string> = {
  requirement_analysis: "需求分析",
  solution_design: "方案设计",
  development: "开发",
  testing: "测试",
  release: "发布上线",
  operations: "运维",
  issue_handling: "问题处理",
  communication: "沟通协作",
  documentation: "文档沉淀",
  review: "复盘",
  research: "调研",
  coordination: "协调推进",
  management: "项目管理",
  other: "其他",
  unknown: "未分类",
};

export const DATE_PRECISION_LABEL: Record<string, string> = {
  day: "日",
  week: "周",
  month: "月",
  quarter: "季度",
  year: "年",
  unknown: "未知",
};

/** 建议摘要里的字段名换成中文，避免把内部字段直接摆给用户 */
const FIELD_LABEL: Record<string, string> = {
  system_id: "所属系统",
  module_type: "模块类型",
  domain_id: "工作领域",
  project_id: "所属项目",
  occurred_at: "发生时间",
  date_precision: "时间精度",
  item_type: "事项类型",
  title: "标题",
  content: "内容",
};

export function readable(text: string | null | undefined): string {
  if (!text) return "—";
  return text
    .replace(/\b([a-z_]+)\.([a-z_]+)\b/g, (_match, _entity: string, field: string) => FIELD_LABEL[field] ?? field)
    .replace(/缺少必填字段\s*/g, "缺")
    .replace(/字段值不合法：/g, "");
}
