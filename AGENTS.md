# AGENTS.md — 项目认知与工作约定

给后续会话（人或其他 Agent）的项目地图。**先读这一页，再按任务需要读代码**，不要每次全量重扫。

## 这是什么

个人成长档案系统（Personal Growth OS）：把周报/月报/项目资料沉淀成可检索、可回顾、可分析的个人经历库，再从经历里提炼能力证据与成长轨迹，并与就业市场数据对照。

- 单机、单用户、本地优先；一人一库（`data/profiles/<名字>.db` 是规划中的形态，现在是 `data/growth.db`）。
- 产品代码 `app/` **零第三方依赖**（只用标准库）；前端 `web/` 与采集器 `collector/` 可以引依赖。
- 不做账号体系；分享方式是导出「数据 + 配置」。

## 快速开始

```bat
启动个人成长档案.cmd        :: 一键启动：检查 Python、构建前端（首次）、开浏览器
```

```bash
python -m app.cli overview                    # 终端总览
python -m app.web --port 8765                 # 只读界面
python -m app.cli --db data/growth.db goal list
python tools\check_all.py                     # 质量闸门（9 步）
```

`--db` 是全局参数，必须放在子命令之前。

## 目录地图

| 路径 | 作用 |
|---|---|
| `app/` | 后端：store / archive / importers / extract / llm / capability / market / projects / roles / web / cli |
| `schema/model.core.json` | **数据模型唯一来源**（实体、字段、枚举、规则、覆盖项） |
| `schema/schema.sql`、`schema/parts/` | 由模型生成的 DDL 与按层的实体清单 |
| `web/` | React + Vite + shadcn 风格组件 + ECharts，只读 |
| `collector/` | 招聘网站采集器（Node + puppeteer-core，当前只有 51job 列表可用） |
| `docs/` | 架构、模块接口、开发规范、UI 方案、市场闭环方案、代码索引 |
| `tools/` | `build_model.py`、`check_all.py`、`index_code.py`、`migrate_db.py`、`launch_ui.py` |
| `tests/` | `unittest`，按步骤分文件（step1…step6） |
| `data/` | 本地库、日志、市场原始数据（均在 .gitignore） |

## 关键约定（改代码前先看）

1. **改模型只改 `schema/model.core.json`**，然后 `python tools/build_model.py`，再 `python tools/migrate_db.py --all`。不要手改 `schema.sql`。
2. **实体名是中文**（`项目`、`工作事项`…），表名是英文（`project`、`work_item`）。`store.fields(entity)` 返回中文字段定义。
3. **写库后显式 `store.commit()`**；`close()` 不提交（踩过）。
4. `app/` 不允许 import 第三方库；`tests/test_engineering.py` 会检查依赖边界。
5. Web 是**只读**入口：只有 GET API，写操作留在 CLI；监听 `127.0.0.1`。
6. 页面只用 `web/src/index.css` 的 token 与 `components/ui/*`，不要逐页自定义颜色/字号。
7. 数据必须可追溯：AI 产出的每条建议带 `quote`/`target_id`，确认后才写正式档案；推断证据 `is_fact=0`。
8. 提交前跑 `python tools/check_all.py`，并 `python tools/index_code.py build --changed` 更新索引（否则闸门第 8 步失败）。

## 常用命令

```bash
python -m app.cli import "飞书导出/周报月报-md" --recursive --year 2026
python -m app.cli periods --year 2026 --dry-run
python -m app.cli ai extract --approve            # 提取并批量确认
python -m app.cli capability map --batch 25
python -m app.cli capability infer --approve      # 按岗位链路补隐含环节（is_fact=0）
python -m app.cli project intro --all             # 生成项目介绍
python -m app.cli goal add "目标名" --type capability --start 2026-12-01 --end 2027-03-31
python -m app.cli profile set --title 产品经理 --set
python -m app.cli market ingest data/market/raw/2026W48/51job-杭州-2026-11-27.jsonl
```

## 文档索引

| 想知道什么 | 看哪里 |
|---|---|
| 系统怎么分层、数据怎么流、为什么这么设计 | `docs/系统架构.md` |
| 每个模块的函数与行号、CLI/API 清单 | `docs/模块与接口.md` |
| 编码风格、测试、提交、长任务纪律 | `docs/开发规范.md` |
| 界面信息架构与设计 token | `docs/UI设计方案.md` |
| 市场数据与能力闭环的规划 | `docs/市场与能力闭环设计方案.md` |
| 代码符号/引用索引 | `docs/代码索引.md`（机器可读在 `.index/`） |

## 工作方式（重要）

- 接任务先判断范围：只读相关模块，不要 `ls -R` 全仓、不要重复读已看过的文件。
- 发现新的架构事实（新模块、新表、新链路），补进 `docs/系统架构.md` 或本文件对应小节；只写「以后会用到」的结论，不写流水账。
- 大任务拆后台作业 + 日志文件（`data/logs/`），不要在前台轮询；作业结束再回来收结果。
- 长上下文时先写交接：当前目标、已完成、未完成、关键文件、下一步。

## 已知环境坑

- Windows `cmd` 按 GBK 读批处理：`启动个人成长档案.cmd` 必须保存为 GBK + CRLF，存 UTF-8 会闪退。
- 同端口可能有两个 Python 进程同时 LISTENING（SO_REUSEADDR）；排查用 `Get-CimInstance Win32_Process` + PowerShell `Stop-Process`，不要用 `taskkill //PID`（MSYS 会转换路径）。
- SQLite 连接不能跨线程；`app/web.py` 用 `threading.local()` 每线程一个连接。
- 从库里读出的 JSON 字段是字符串（如 `alias_names`），更新前先 `json.loads`。
- 51job 的 WAF 会话很容易失效：复用同一个 page、限速、失败即停。
