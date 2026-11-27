# -*- coding: utf-8 -*-
"""个人成长档案系统 —— 实现包。

当前进度（对应需求第 7 章实施顺序）：
  1. 核心数据模型                ✅ schema/model.json + schema/schema.sql（44 实体 / 911 字段 / 51 枚举）
  2. 原始资料存储与来源追溯      ✅ app/importers.py（含 .zip、飞书导出包）
  3. 项目 / 系统 / 模块 / 事项档案 ✅ app/archive.py
  4. AI 提取、匹配、归并、审核    ✅ app/llm.py + app/extract.py（真实模型，AI 只提建议）
  5. 能力词典与能力证据模型       ⬜ 未开始
  6. 个人特征画像                ⬜
  7. 成长曲线与阶段分析          ⬜
  8. 成果案例与材料生成          ⬜
  9. API / MCP / CLI 接入        ⬜（CLI 已有；MCP/HTTP 未做）
 10. 备份迁移与安全验证          ◐ 备份与校验已做（app/backup.py），迁移与安全验证待补

横切：app/logging.py（统一日志）、app/backup.py（备份与校验）、app/feishu*.py（飞书只读接入与同步）。
工程文档见 docs/；代码索引见 docs/代码索引.md（生成物，机器索引在 .index/index.json）。
"""
__all__ = [
    "archive",
    "backup",
    "cli",
    "extract",
    "feishu",
    "feishu_auth",
    "feishu_import",
    "ids",
    "importers",
    "llm",
    "logging",
    "model_meta",
    "store",
]
