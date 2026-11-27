# -*- coding: utf-8 -*-
"""给 docs 补第 5 步（能力词典/证据/画像）的说明，并同步 README、架构设计、UI 方案。"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def patch(rel, pairs):
    path = os.path.join(ROOT, rel)
    text = io.open(path, encoding="utf-8").read()
    for old, new in pairs:
        assert text.count(old) == 1, (rel, text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)
    print("patched", rel)


MODULE_NEW = """### 2.16 `app/capability.py`

**职责**：能力词典（4 分类 / 10 项，`builtin`）与能力证据链路。第 5 步的写入方。

**依赖**：`app/store.py`、`app/extract.py`（`render_prompt`/`parse_json_reply`）、`app/llm.py`。

**公开 API**

| 函数/类 | 契约 |
| --- | --- |
| `seed(store)` | 幂等建 `capability_category` 与 `capability`（origin=system）；返回 `(新增分类, 新增能力)` |
| `capabilities(store)` | 按分类聚合，带 `evidence_count`、`avg_strength`、`last_evidence_at`、`months`、`recent` |
| `evidence(store, capability_id, limit=200)` | 某能力的证据明细（join 事项与项目，带原文） |
| `CapabilityMapper(store, llm=None)` | `run(limit, batch_size=25, dry_run, temperature, max_tokens)`：分批把事项映射成 `change_proposal`（target=`capability_evidence`），每批提交；503/超时自动重试 4 次 |

**关键行为**

- 证据只能来自已确认的 `work_item`；已经证据化或已有 pending 建议的事项会跳过（`_items()` 三重过滤）。
- 引用必须逐字出现在事项标题或正文里，否则计 `skipped`；`strength` 只接受 1–5，`evidence_type` 只接受四类。
- 建议确认后才写 `capability_evidence`；画像只展示证据数与平均强度，不生成成长总分。

---

"""

CLI_NEW = """### 3.6 能力组

| 命令 | 关键参数 | 位置 |
| --- | --- | --- |
| `capability seed` | 建内置词典（4 分类 / 10 能力），幂等 | `app/cli.py:1409`，实现 `:645` |
| `capability list` | 词典 + 证据数 / 平均强度 | 同上 |
| `capability profile` | 按分类汇总覆盖率 | 同上 |
| `capability evidence CODE` | `--limit`（默认 100）；列出证据与原文引用 | 同上 |
| `capability map` | `--limit`、`--batch`（默认 25）、`--dry-run`、`--max-tokens`、`--model`；产出 pending 证据建议 | 同上 |

标注作业产出的建议在 `复盘` 页或 `ai proposals` 里确认；`ai confirm` 一次一条，批量确认走 `Review.confirm_batch(job_id=...)`。

"""

README_SECTION = """## 能力证据与画像（第 5 步）

能力画像不是打分器，而是把已确认的工作事项映射到一套固定的能力词典，并保留原文依据。

- **词典**：4 个分类、10 项能力（用户洞察、产品设计、数据分析、项目推进、质量与验收、风险处理、
  跨团队协作、沟通表达、领域知识、复盘迁移）。`python -m app.cli capability seed` 幂等建表，
  改词典请改 `app/capability.py` 的 `CAPABILITIES` 后重跑。
- **标注**：`python -m app.cli capability map` 分批把没有证据的事项送进模型，产出
  `change_proposal`（target=`capability_evidence`）。每条建议必须带一句逐字来自事项标题或正文的引用，
  强度 1–5（1 参与 / 2 独立完成常规 / 3 独立负责复杂 / 4 定标准带人 / 5 定义方向并被外部验证）。
- **确认**：建议在「复盘 → 待处理建议」里确认，或用 `Review.confirm_batch(job_id=...)` 批量确认；
  只有确认后的证据才进入画像。
- **查看**：`capability list`、`capability evidence CODE`，或界面「能力画像」页（雷达 + 分类卡片 +
  最近一条原文）。`/api/capabilities` 只读。

"""


def main():
    patch("docs/模块与接口.md", [
        ("---\n\n## 3 命令行接口", "---\n\n" + MODULE_NEW + "## 3 命令行接口"),
        ("### 3.6 飞书组", CLI_NEW + "### 3.7 飞书组"),
        ("### 3.7 备份组", "### 3.8 备份组"),
        ("### 3.8 退出码与输出约定", "### 3.9 退出码与输出约定"),
    ])
    patch("README.md", [
        ("| 5–10 | 能力证据、特征画像、成长曲线、成果与材料、Agent 接入、备份迁移 | ⬜ 未开始 |",
         "| 5 | 能力词典、能力证据与能力画像 | ✅ `app/capability.py` + 「能力画像」页 |\n"
         "| 6–10 | 特征画像、成长曲线、成果与材料、Agent 接入、备份迁移 | ⬜ 未开始 |"),
        ("## AI 提取与审核时的口径说明（第 4 步）", README_SECTION + "## AI 提取与审核时的口径说明（第 4 步）"),
        ("- 第 5 步及之后（能力证据与画像、成长曲线、成果案例中心、个人材料中心、Agent 接口、\n"
         "  备份迁移）未开始；`achievement_*`、`capability_*`、`material` 等表已建好但还没有写入方。",
         "- 第 6 步及之后（特征画像、成长曲线、成果案例中心、个人材料中心、Agent 接口、备份迁移）未开始；\n"
         "  `achievement_*`、`material`、`growth_stage`/`growth_snapshot` 等表已建好但还没有写入方。"),
        ("- 界面里的能力雷达、阶段对比、成长曲线仍为空态：它们依赖第 5–7 步的 `capability_*` / `growth_snapshot` 数据。",
         "- 能力雷达已可用（第 5 步）；阶段对比与成长曲线仍为空态：它们依赖第 7 步的 `growth_stage` / `growth_snapshot` 数据。"),
    ])
    patch("docs/架构设计.md", [
        ("`schema/model.json:14478-14484`（模型统计含 45 实体 936 字段）；写入方为零 | **未实现（第 5 步）** |",
         "`schema/model.json:14478-14484`（模型统计含 45 实体 936 字段）；写入方 `app/capability.py` | **已实现（第 5 步）** |"),
    ])
    return 0


if __name__ == "__main__":
    sys.exit(main())
