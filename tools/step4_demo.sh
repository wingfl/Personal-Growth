#!/usr/bin/env bash
# 第 4 步演示：用真实模型（本机 DSH 配置的网关）从原始资料提取待审核建议，
# 人工确认 / 拒绝后写入档案，并检查来源追溯。
#
# 前置：先跑过第 1–3 步（tools/step3_demo.sh 会在这里自动执行）。
# 用法：bash tools/step4_demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8

DB=data/demo.db
CLI="python -m app.cli --db $DB"

echo "=== 0. 重建演示档案（第 1–3 步） ==="
bash tools/step3_demo.sh > data/step3.log 2>&1
echo "第 3 步演示完成，日志见 data/step3.log"
$CLI stats | tail -3

echo
echo "=== 1. 登记提示词模板与 Agent 工作流 ==="
$CLI ai seed

echo
echo "=== 2. 模型连通性 ==="
$CLI ai check

echo
echo "=== 3. 从周报提取（事项时间会按资料期间预填） ==="
eval "$(python tools/step4_pick.py $DB)"
$CLI ai extract "$weekly_doc"

echo
echo "=== 4. 从复盘提取（已有项目/系统应复用，不新建） ==="
$CLI ai extract "$review_doc"

echo
echo "=== 5. 待审核建议 ==="
eval "$(python tools/step4_pick.py $DB)"
$CLI ai proposals --limit 30

echo
echo "=== 6. 看一条建议的细节（出处 + 确认前还缺什么） ==="
$CLI ai show "$item"

echo
echo "=== 7. 确认「给已有项目补来源」（跨资料归并） ==="
$CLI ai confirm "$link_project" --note "复盘资料确属该项目"

echo
echo "=== 8. 确认事项（补上模型没给的时间） ==="
$CLI ai confirm "$item" --set occurred_at=2024-03-20 --set date_precision=day --note "人工核对了时间"

echo
echo "=== 9. 拒绝一条重复建议 ==="
if [ -n "${ex_item:-}" ]; then
  $CLI ai reject "$ex_item" --note "与已有事项重复，不单独建档"
fi

echo
echo "=== 10. 审核后的档案总览 ==="
$CLI overview

echo
echo "=== 11. 来源追溯：项目看得到两份资料的出处 ==="
$CLI trace project "$project"

echo
echo "=== 12. 作业记录（用了哪个模型、多少 token、覆盖多少片段） ==="
$CLI ai jobs --limit 5
