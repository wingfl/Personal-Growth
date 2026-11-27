# -*- coding: utf-8 -*-
"""UI 设计文档补「能力画像」页，并更新图表/信息架构/API 表。"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, "docs", "UI设计方案.md")

PAIRS = [
    ("├─ 数据分析        /insights          趋势、能力、阶段对比（数据不足时给空态）",
     "├─ 数据分析        /insights          趋势、构成、热力图、阶段对比（数据不足时给空态）\n"
     "├─ 能力画像        /capabilities      能力词典、证据、按月变化"),
    ("| 能力雷达 | `capability_evidence` × `evaluation_dimension` | ❌ 0 条 | 「能力证据还没建立」+ 第 5 步入口 |",
     "| 能力雷达 | `capability_evidence` × `capability` | ✅ 已实现（第 5 步） | 「还没有能力证据」+ `capability map` 入口 |"),
    ("| 数据分析 | 12/26/52 周切换；趋势（柱 + 4 周均线）、工作构成、活跃热力图；能力雷达与阶段对比为「数据未建立」空态 | `/api/insights/*` |",
     "| 数据分析 | 12/26/52 周切换；趋势（柱 + 4 周均线）、工作构成、活跃热力图；阶段对比为「数据未建立」空态 | `/api/insights/*` |\n"
     "| 能力画像 | 覆盖/证据/平均强度三张统计卡、雷达、分类能力卡（五点强度 + 最近原文）；空态给标注命令 | `/api/capabilities`、`/api/capabilities/{id}` |"),
    ("| `GET /api/goals` | 由真实数据算出的成长建议（`persisted: false`） |",
     "| `GET /api/goals` | 已持久化的 `growth_goal` + 由真实数据算出的建议 |\n"
     "| `GET /api/profile` | 身份与角色（`user_profile.current_title` 等） |\n"
     "| `GET /api/capabilities` | 能力词典、覆盖/证据/强度汇总、按分类聚合、近 8 个月变化 |\n"
     "| `GET /api/capabilities/{id}` | 单个能力的证据明细 |"),
]


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in PAIRS:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="\n").write(text)
    print("patched docs/UI设计方案.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
