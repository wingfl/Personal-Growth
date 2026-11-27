#!/usr/bin/env bash
# 第 3 步演示：在演示库 data/demo.db 上录入项目 / 系统 / 模块 / 事项 / 主题 / 职责，
# 每条记录都关联到已导入的来源片段，并演示重复记录归并。
# 用法：bash tools/step3_demo.sh（可重复执行：先还原 data/demo.pristine.db）
set -e
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8
DB=data/demo.db
CLI="python -m app.cli --db $DB"

if [ -f data/demo.pristine.db ]; then
  cp data/demo.pristine.db "$DB"   # 每次从干净的演示库开始
fi

# 演示库中的来源片段
W_METRIC=01a21ac5-019d-79e2-822e-0e5df430b652   # 周报：完成客户数据平台指标口径梳理，覆盖 12 个核心指标
W_DISPUTE=01a21ac5-019d-7fa8-a7ec-2423bda2069c  # 周报：与业务方确认 3 个争议口径
W_FIX=01a21ac5-019d-7d9f-976b-c1da67a0e747      # 周报：修复数据质量校验规则 2 处误报
M_MODULE=01a21ac5-0196-7879-9373-ce32650bfc0c   # 月报：负责指标口径模块，主导口径梳理与校验规则设计
R_LEAD=01a21ac5-01ff-7581-a7bc-d4b9839ce263     # 复盘：主导口径梳理工作，建立指标定义模板
R_RESULT=01a21ac5-01ff-7c36-a351-1c595351293d   # 复盘：口径争议从每月 3 起降到 0 起
R_ROW=01a21ac5-01ff-7e8d-b771-f8d8e1133195      # 复盘表行：口径梳理 | 12 个核心指标定义 | 主导

echo "== 1. 项目 =="
$CLI project add "客户数据平台建设" \
  --type new_build --role lead --start 2024-01-08 \
  --domain 数据平台 --importance 5 --representative \
  --background "各业务线指标口径不一致，同一指标在不同报表中口径不同，月度经营分析反复返工" \
  --goal "统一指标口径，并把口径固化到数据质量校验规则" \
  --scope "指标口径模块：口径梳理、指标定义模板、校验规则设计" \
  --contribution "主导口径梳理，定义 12 个核心指标，落地 8 条校验规则" \
  --outcome "口径争议从每月 3 起降到 0 起" \
  --from $R_LEAD --from $R_RESULT

echo "== 2. 系统 =="
$CLI system add "客户数据平台" --type platform --status online --role owner \
  --domain 数据平台 --description "面向各业务线的指标体系与报表平台" --from $M_MODULE

echo "== 3. 功能模块 =="
$CLI module add "指标口径管理" --system "客户数据平台" --type core --role lead \
  --description "指标定义、口径说明与版本维护" --from $M_MODULE
$CLI module add "数据质量校验" --system "客户数据平台" --type data --role owner \
  --description "校验规则配置与误报处理" --from $W_FIX

echo "== 4. 工作事项 =="
$CLI item add "完成客户数据平台指标口径梳理" --type requirement_analysis \
  --project "客户数据平台建设" --system "客户数据平台" --module "指标口径管理" \
  --domain 数据平台 --role lead --complexity 4 --hours 24 \
  --from $W_METRIC --from $M_MODULE
$CLI item add "与业务方确认 3 个争议口径" --type communication \
  --project "客户数据平台建设" --module "指标口径管理" \
  --domain 数据平台 --role core --complexity 3 \
  --from $W_DISPUTE
$CLI item add "修复数据质量校验规则 2 处误报" --type testing \
  --system "客户数据平台" --module "数据质量校验" \
  --domain 数据平台 --role participant --complexity 2 --routine --from $W_FIX
$CLI item add "复盘平台建设经验" --type review \
  --project "客户数据平台建设" --domain 数据平台 --role lead \
  --date 2024-04-02 --precision day --from $R_ROW

echo "== 5. 持续工作主题 =="
$CLI theme add "客户数据平台建设" --type system_building \
  --project "客户数据平台建设" --domain 数据平台 \
  --description "从口径梳理到校验规则落地的跨月持续工作"

echo "== 6. 职责与贡献 =="
$CLI role add project "客户数据平台建设" --role lead --start 2024-01-08 --ongoing --primary \
  --scope "指标口径模块" --contribution "主导口径梳理与规则设计"

echo "== 7. 重复记录（同一项目的另一种叫法，用于演示归并） =="
$CLI project add "客户数据平台" --type enhancement --start 2024-02-01 --alias "指标平台" \
  --background "早期按需求变更记录的项目条目" --from $W_DISPUTE
$CLI item add "梳理指标口径争议" --type coordination --project "客户数据平台" \
  --domain 数据平台 --role core --date 2024-02-20 --precision day --from $W_DISPUTE

echo "== 8. 主题成员与时间线 =="
eval "$(python tools/step3_members.py)"
$CLI theme show "$theme"

echo "== 9. 归并重复项目 =="
$CLI project merge --keep "$project" --drop "$duplicate" \
  --note "同一项目的两种叫法，月报与周报各记一次"

echo "== 10. 归并后的项目档案 =="
$CLI project show --id "$project"

echo "== 11. 来源追溯 =="
$CLI trace project "$project"

echo "== 12. 事项列表 =="
$CLI item list --limit 6

echo "== 13. 总览 =="
$CLI overview
