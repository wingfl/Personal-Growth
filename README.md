# 个人成长档案系统（Personal Growth OS）

以真实工作经历为基础的成长档案：原始资料沉淀在一起，AI 只做整理与分析助手，
所有正式档案都保留来源，用户确认后才生效。

当前实现进度（对应需求文档第 7 章实施顺序）：

| 步骤 | 内容 | 状态 |
| --- | --- | --- |
| 1 | 核心数据模型 | ✅ `schema/model.json`、`schema/schema.sql`、设计文档 |
| 2 | 原始资料存储与来源追溯 | ✅ `app/` 建库、导入与飞书资料同步 |
| 3 | 项目 / 系统 / 模块 / 事项档案 | ✅ `app/archive.py` 档案服务层 + CLI |
| 4 | AI 提取、匹配、归并、审核 | ✅ `app/llm.py` + `app/extract.py` + `ai` 命令组 |
| 界面 | 本地只读 Web UI（P0+P1） | ✅ `app/web.py` + `web/`（React + Vite + ECharts） |
| 5 | 能力词典、能力证据与能力画像 | ✅ `app/capability.py` + 「能力画像」页 |
| 6 前哨 | 就业市场样本与市场定位 | ✅ `collector/` + `app/market.py` + 「市场定位」页 |
| 6–10 | 特征画像、阶段快照/成长曲线、成果与材料、Agent 接入、备份迁移 | ⬜ 未开始 |

## 目录结构

新人或新会话先读 `AGENTS.md`（项目地图与约定）与 `docs/系统架构.md`（分层、数据流、设计取舍）。

```
schema/      model.core.json（人工维护的骨架）、parts/（分层的业务字段）、
             model.json 与 schema.sql（由 tools/build_model.py 生成，不要手改）
docs/        设计文档模板、生成的设计文档与字段清单
tools/       build_model.py（生成+校验）、check_part.py、export_fields_xlsx.py、
             describe_entity.py（查实体字段规格）、migrate_db.py（给已有库补新字段）、
             feishu_probe.py（飞书连通性探测）、step3_demo.sh、step4_demo.sh（演示）
prompts/     提示词与 Agent 工作流定义（document_extract.v1.json）
app/         ids.py 主键与时间、model_meta.py 模型元数据与校验、
             store.py 模型驱动数据访问、importers.py 原始资料导入、
             archive.py 档案服务层（第 3 步）、llm.py 模型接入层、
             feishu.py 飞书只读接入、feishu_import.py 飞书资料同步、
             extract.py AI 提取与审核（第 4 步）、cli.py 命令行
tests/       第 1–2 步、第 3 步、第 4 步与飞书同步的自检用例
web/         本地只读界面：React + Vite + Tailwind + ECharts（构建到 web/dist）
样例资料/    演示用的示例资料（内容已标注「示例」）
data/        growth.db（本地档案库）与 attachments/（原始文件副本）
```

## 快速开始

```bash
python -m app.cli init                              # 按 schema/schema.sql 建库
python -m app.cli import "资料/2024-03工作月报.md"   # 导入单个文件
python -m app.cli import "资料/" --recursive         # 导入整个目录（建立导入批次）
python -m app.cli docs                               # 已导入的资料列表
python -m app.cli fragments <文档ID>                 # 来源片段（含字符区间）
python -m app.cli verify <文档ID>                    # 校验片段能否在正文中原样取回
python -m app.cli audit --entity source_document     # 变更历史
python -m app.cli stats                              # 各实体记录数
```

第 3 步的录入与查询（每条记录都可以用 `--from <片段ID>` 挂上来源）：

```bash
python -m app.cli project add "客户数据平台建设" --type new_build --role lead \
    --start 2024-01-08 --domain 数据平台 --importance 5 --representative \
    --background "…" --scope "指标口径模块" --from <片段ID>
python -m app.cli system add "客户数据平台" --type platform --status online --role owner
python -m app.cli module add "指标口径管理" --system 客户数据平台 --type core
python -m app.cli item add "完成指标口径梳理" --type requirement_analysis \
    --project 客户数据平台建设 --module 指标口径管理 --complexity 4 --from <片段ID>
python -m app.cli theme add "客户数据平台建设" --type system_building --project 客户数据平台建设
python -m app.cli theme member <主题ID> --item <事项ID> --doc <资料ID>
python -m app.cli role add project 客户数据平台建设 --role lead --start 2024-01-08 --ongoing
python -m app.cli link project <项目ID> --from <片段ID>
python -m app.cli project merge --keep <保留ID> --drop <重复ID> --note "同一项目的两种叫法"
python -m app.cli overview                            # 成长总览：数量、代表项目、近期事项、领域分布
python -m app.cli trace project <项目ID>              # 一条记录的全部依据
```

第 4 步的 AI 提取与审核（默认复用本机 DSH 配置的网关与密钥）：

```bash
python -m app.cli ai seed                            # 把 prompts/*.json 登记为提示词模板与工作流
python -m app.cli ai check                           # 看用哪个网关/模型/密钥来源，并做一次连通性检查
python -m app.cli ai extract <文档ID>                 # 提取：产出待审核建议（--dry-run 只看提示词）
python -m app.cli ai proposals                       # 待审核建议列表
python -m app.cli ai show <建议ID>                    # 建议字段 + 每条字段的原文出处
python -m app.cli ai confirm <建议ID> --set k=v --note "…"   # 确认写入（改过即记为 modified）
python -m app.cli ai reject <建议ID> --note "…"        # 拒绝，不写任何档案
python -m app.cli ai jobs                            # 作业记录：模型、token、覆盖片段、产出条数
```

批量入库（文件名没写年份时先补期间，再逐篇提取并自动确认）：

```bash
python -m app.cli import 飞书导出/周报月报-md --recursive --year 2026
python -m app.cli periods --year 2026 --dry-run      # 已导入的资料按年份补期间（只预览）
python -m app.cli ai extract <文档ID> --approve      # 提取后立即批量确认，缺日期按资料期间补齐
python tools/oneoff/_extract_all.py --only-missing   # 逐篇提取→确认，可重复执行（跳过已成功）
```

自检：

```bash
python -m unittest discover -s tests -v
python tools/build_model.py        # 改动物模型后重新生成 schema.sql 与文档
python tools/describe_entity.py project work_item    # 查某个实体的字段与枚举
bash tools/step3_demo.sh           # 在 data/demo.db 上跑完第 3 步全部录入动作
bash tools/step4_demo.sh           # 用真实模型跑完第 4 步提取→审核→写档（日志 data/step4.log）
python tools/migrate_db.py --all   # 模型加了字段后，给已有库补列与索引
```

## 本地界面（只读）

**一键启动**：双击根目录的 `启动个人成长档案.cmd`（缺依赖会自动 `npm install`/构建，端口被占用会顺延，
关闭窗口即停止服务）。该脚本用 **GBK 编码**保存——中文 Windows 的 cmd 按本地代码页读取批处理，
若存成 UTF-8 会变成乱码并「闪退」，改动时请保持 GBK。也可以手工：

```bash
cd web && npm install && npm run build     # 首次或前端改动后
python -m app.web --db data/growth.db --port 8765
# 浏览器打开 http://127.0.0.1:8765
```

界面只读：首页看状态与趋势，成长档案查事项/项目/资料，数据分析看 12/26/52 周趋势、构成与热力图，
能力画像页看 10 项能力的证据数、平均强度与最近原文（没有证据的能力留空，不给分），
成长目标页上半是**可跟踪的目标**（`growth_goal`，有周期/达成标准/进度），下半是系统按真实数据算出的
「下一步该补什么」建议；复盘页看 AI 待审建议，设置页看本人角色、库路径与常用命令。
确认/拒绝建议、导入、备份等写操作仍走命令行。

- 只监听 `127.0.0.1`，无登录、无外网请求；API 全为 GET。
- 亮/暗主题（`?theme=dark` 可深链）；≤768px 侧栏收进抽屉。
- `web/dist` 不进版本库：没有构建产物时服务仍能启动，但页面会提示先构建。
- 设计规范、页面方案与实施记录见 `docs/UI设计方案.md`。

## 飞书资料同步（周报 / 月报）

把飞书知识库与云盘里名称含「周报」「月报」的资料直接拉进原始资料库。
应用凭据按下面的顺序查找，不需要写进代码或出现在命令行里：

1. 环境变量 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
2. `~/.dsh/.credentials.yaml` 的 `refs` 段（本机已登记 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`）
3. 工作区的 `config/feishu.json`（放本机凭据，不进版本库）

```bash
python -m app.cli feishu check                 # 凭据来源、身份、令牌、可见知识库、云盘是否可读
python -m app.cli feishu spaces                # 当前身份可见的知识库列表
python -m app.cli feishu scan                  # 扫描名称含「周报」「月报」的资料（不写库）
python -m app.cli feishu scan --source both    # 知识库 + 云盘一起扫
python -m app.cli feishu pull                  # 导入原始资料库（按 external_id 判重）
python -m app.cli feishu pull --source both --label "飞书首批"
python -m app.cli feishu pull --dry-run        # 只读正文，不写库
```

### 身份：应用身份 vs 用户身份

| | 应用身份（tenant_access_token） | 用户身份（user_access_token） |
| --- | --- | --- |
| 能读到什么 | 只有**被显式分享给应用**的文档 | 你本人能看到的全部云文档（含「我的空间」） |
| 怎么开通 | 开放平台开权限 + 把应用加为知识库成员/文件夹协作者 + 发布版本 | 开放平台开权限 + 发布版本，然后跑一次 `feishu auth` 授权 |
| 有效期 | 自动续期，无需干预 | 访问令牌约 2 小时，用刷新令牌自动续（scope 含 `offline_access`） |

默认 `--auth auto`：本机有用户令牌就用用户身份，否则退回应用身份。
想强制某一种身份时加 `--auth user` 或 `--auth tenant`。

用户身份授权（一次即可，令牌存在 `~/.dsh/.credentials.yaml` 的 `refs` 段）：

```bash
python -m app.cli feishu auth          # 打印授权链接并在本机 8765 端口等回调
python -m app.cli feishu auth --no-wait # 只打印链接，之后用 --code 手动换取
python -m app.cli feishu whoami        # 查看当前授权的身份与令牌有效期
python -m app.cli feishu logout        # 清除本机保存的用户令牌
```

授权前需要在飞书开放平台做三件事（做一次就好）：

1. 「安全设置 → 重定向 URL」加入 `http://localhost:8765/callback`；
2. 「权限管理」开通用户身份权限：`drive:drive:readonly`、`wiki:wiki:readonly`、
   `docx:document:readonly`、`sheets:spreadsheet:readonly`、`offline_access`；
3. **发布应用版本**（企业自建应用通常还需要管理员审核通过）。

拉进来的资料与手动上传走同一套解析：正文（`raw_text`）写入后不可修改、片段带
`char_start/char_end` 可回原文核对，另外多记 `external_id`（飞书文档 token）与
`external_url`（原文链接），重复拉取按 `external_id` 判重。因此 `docs`、`fragments`、
`verify`、`trace`、`ai extract` 都可以直接用在这批资料上；一次同步会留下一条
`import_batch`（`source_channel=feishu`），可复盘这次拉了哪些文档。

**应用身份能读到什么，取决于飞书侧的授权**（当前状态以 `feishu check` 的输出为准）：

- 读云盘：应用需要 `drive:drive:readonly`（或 `drive:drive`、`space:document:retrieve`）；
- 读云文档正文：需要 `docx:document:readonly`（旧版文档加 `doc:document:readonly`，
  表格加 `sheets:spreadsheet:readonly`）；
- 知识库：要把应用加为该知识库成员（可阅读）；云盘：要把存放资料的文件夹分享给应用；
- 权限改动后需要在开放平台**发布应用版本**才会生效；
- 以上是**应用身份**的限制；用用户身份授权（`feishu auth`）时按你自己的可见范围读，不需要逐个分享。

## 演示数据

`样例资料/` 三个文件与 `data/demo.db` 是功能演示用的示例内容（标题与指标都标注了「示例」），
可以直接删除；真实档案请使用默认的 `data/growth.db`。
`data/demo.pristine.db` 是只导入过演示资料的干净副本，`tools/step3_demo.sh` 与
`tools/step4_demo.sh` 每次运行都会先还原它，因此演示脚本可以反复执行。
`data/step3.log`、`data/step4.log` 是这两个脚本最近一次的完整输出。

## 已实现的约束（对应需求 1.4 设计原则）
1. **原始内容不可覆盖**：`source_document.raw_text`、`source_fragment.text` 等字段带
   `imm` 标记，应用层拒绝任何后续修改；`schema.sql` 不提供绕过路径。
2. **来源可追溯**：每个片段记录 `heading_path` 与 `char_start/char_end`，
   `verify` 命令可校验它们仍能精确定位回正文；第 3 步起每条档案记录都可写
   `provenance_link`（含引用原文 `quote_text`），`trace` 命令可反查到原始资料与标题。
3. **AI 只提建议**：AI 写出的结构化记录默认 `review_status = pending`
   （`app/model_meta.py::defaults_for`），用户确认后才参与分析与材料。
4. **变更留痕**：所有写入自动追加 `audit_log`（写入前后 payload + 操作者类型），
   `audit_log` 只增不改不删（`base_append_only` 字段组）。
5. **并发安全**：`update` 需要 `expected_revision`，与库中 `revision` 不一致即拒绝。
6. **不虚构数据**：导入只记录文件里真实存在的内容，字数与期间口径明确写在下文。

## 导入时的口径说明

- **内容哈希**：文件 sha256；内容相同的文件默认判定为重复并跳过
  （`--handling new_version` 另存为下一版本并写 `duplicate_of_id`，`import_anyway` 强制新建）。
- **字数**：中日韩字符按字计，其余按空白切分的词计（`app/importers.py::count_words`）。
- **语言**：按正文前 4000 字里中日韩字符与拉丁字母的比例判定，非模型推测。
- **期间**：从文件名推断，支持 `2024-03`、`2024年3月`（月）、`2024Q2`（季）、`2024年第5周`（周）、
  `2024`（年）；推断不出来就留空，不猜测。
- **资料类型**：按文件名关键词推断（周报 / 月报 / 需求 / 方案 / 复盘 …），可用 `--type` 覆盖。
- **片段解析置信度**：txt / md / docx 属结构化提取，记为 1.0；将来接入 PDF 与 OCR 时会低于 1.0。
- **附件**：原始文件复制到「数据库同目录 / attachments / <哈希前12位>_<原名>」，
  `attachment.storage_path` 尽量记为工作区相对路径（跨盘符时记绝对路径），
  `attachment.owner_type/owner_id` 指向所属资料，`source_document.attachment_id` 指向实际使用的文件。
  附件跟着数据库走，测试或换个库文件都不会污染既有档案。

## 录入时的口径说明（第 3 步）

- **来源**：`--from <片段ID>` 可重复；写入 `provenance_link` 时一并存下片段原文
  `quote_text`（不可修改），因此原始资料被替换后仍能核对当时依据。
- **事实与推断**：档案记录默认 `is_fact = 1`（事实）；标 `--fact false` 时必须同时写
  `--basis "依据"`，否则拒绝写入（数据规则 B6）。
- **时间**：`--date` + `--precision` 明确给出；只给 `--date` 时按日。都不给时取来源资料的期间，
  期间是整周则记 `week`、整月记 `month`（`app/archive.py::precision_from_period`），
  拿不到期间又没给日期就报错，不猜时间。
- **角色**：每个记录上的 `my_role`（主导 / 负责 / 参与 / 协助…）只是展示用冗余；
  权威口径是 `role_record`（`role add`，含起止时间与职责范围），见数据规则 J16。
- **工作领域**：弱分类（取舍十二）。`--domain` 填了但库里没有就自动新建，
  不填也不影响录入；它不参与能力或成长评级换算。
- **持续主题**：一个主题的成员可以是工作事项、成果案例或原始资料；
  首次 / 最近出现时间由成员时间聚合得出（`refresh_theme_span`），不手工填写，
  跨周报月报的同一项工作用主题串起来，而不是新建重复项目（规则 J15）。
- **重复记录归并**：`merge` 会把重复记录上所有引用（含多态引用）改指到保留记录，
  写一条 `entity_relation(merged_into)` 血缘、在保留记录上记 `merged_from_ids`，
  再把重复记录软删除；过程中出错整体回滚。关联表上撞唯一约束的重复关联会被丢弃并在
  命令输出里列出（规则 J14）。

## 项目整理与项目介绍

项目是经历的容器：需求、功能迭代是它的事项，不是新的项目。同一产品的多条记录用
`python -m app.cli project merge --keep "Aether 平台" --drop "Aether局部重绘" ...` 归并，
保留 `merged_into` 血缘与别名，事项自动改挂到保留的项目。

`python -m app.cli project intro` 让模型根据「名称、时间、角色、事项标题、已有成果」写三句话
（做什么 / 我承担什么 / 做到什么程度），不超过 110 字；出现没给过的百分比、金额或人数就退回规则稿，
宁可用词平实也不编造。界面在「成长档案 → 项目」的卡片与详情里展示。

## 成长轨迹的口径

成长看的是**能力证据的积累**，不是每周事项数。`/api/growth` 按月统计能力证据
与能力覆盖的累积；首页与「数据分析」的曲线都来自这里，事项数量只在「事项节奏」卡里作为交付节奏参考，
不作为成长指标。

## 能力证据与画像（第 5 步）

能力画像不是打分器，而是把已确认的工作事项映射到一套固定的能力词典，并保留原文依据。

- **词典**：4 个分类、10 项能力（用户洞察、产品设计、数据分析、项目推进、质量与验收、风险处理、
  跨团队协作、沟通表达、领域知识、复盘迁移）。`python -m app.cli capability seed` 幂等建表，
  改词典请改 `app/capability.py` 的 `CAPABILITIES` 后重跑。
- **标注**：`python -m app.cli capability map` 分批把没有证据的事项送进模型，产出
  `change_proposal`（target=`capability_evidence`）。每条建议必须带一句逐字来自事项标题或正文的引用，
  强度 1–5（1 参与 / 2 独立完成常规 / 3 独立负责复杂 / 4 定标准带人 / 5 定义方向并被外部验证）。
- **确认**：建议在「复盘 → 待处理建议」里确认，或用 `Review.confirm_batch(job_id=...)` 批量确认；
  只有确认后的证据才进入画像。
- **岗位链路**：周报常只写「XX 需求完成评审并推进」，不会写调研、PRD、方案。`capability infer`
  按 `user_profile.current_title` 选择岗位链路（产品经理：调研与验证 → PRD 与方案 → 推进与协作 →
  验收与复盘），对里程碑句子补出「落点 + 前一环」两项能力，计入本人能力（`is_fact=1`，
  `fact_basis` 注明「按岗位常规环节补全」）、强度封顶 2；确认前可删改，与实际不符的不要留。
- **查看**：`capability list`、`capability evidence CODE`，或界面「能力画像」页（雷达 + 分类卡片 +
  最近一条原文）。`/api/capabilities` 只读。

## 就业市场样本与市场定位（第 6 步前哨）

这一块回答的是「我现在的薪资和岗位要求，在本地市场上大概是什么位置」，只看**招聘信息**，
不碰简历、不做账号体系。

- **采集**：`collector/` 是独立 Node 工程（`npm i` 后 `npm run collect`），用本机 Edge 打开 51job
  搜索页，在页面上下文里调用列表接口；只取列表级结构化字段（薪资、经验、学历、标签、公司），
  不抓详情页正文、不登录。产出 `data/market/raw/<周>/51job-<城市>-<日期>.jsonl`。
  51job 有 WAF 与速度限制，脚本限速、单页异常即停，遇到验证码请停一段时间再跑。
- **入库**：`python -m app.cli market ingest data/market/raw/...jsonl`，按 `(platform, external_id)`
  去重；`market summary` 打印各方向样本数、薪资 P25/P50/P75 与高频标签。
- **口径**：薪资取招聘方给的区间中值，分位数由样本线性插值；样本少时三个分位会接近，页面不据此下结论。
  高频标签是招聘方的描述习惯，不等于硬门槛；要判断「该补什么」，回到能力画像的证据缺口。
- **看板**：界面「市场定位」页（`/api/market`），按方向显示 P25–P75 区间、中位和你当前月薪的位置；
  `target_role` 可多选，也可 `market role-add` 自由新增。
- **限制**：BOSS / 猎聘 / 智联的搜索接口都有签名或风控，匿名环境拿不到结构化列表，本仓库不提供绕过方案；
  官方统计（国家统计局分行业工资）粒度到行业不到岗位，只能作为背景基准。

## AI 提取与审核时的口径说明（第 4 步）

- **模型来源**：默认读本机 DSH 配置（`~/.dsh/profiles/<profile>/cordis.patch.yml` 的 `baseURL`
  与 `apiKeyEnv`，再回落到 `~/.dsh/.credentials.yaml` 的 `refs` 段），顺序是
  显式参数 → `GROWTH_LLM_API_KEY/BASE_URL/MODEL/PROVIDER` → `NEORIGIN_API_KEY` →
  profile 的 apiKeyEnv → 凭据文件。`ai check` 会打印实际用的是哪一个。
- **token 额度**：默认 `max_tokens = 32768`。这些模型是推理型的，额度太小会把预算花在思考上、
  返回被截断的 JSON；遇到 `finish_reason=length` 造成的 `parse_failed`，引擎会自动翻倍预算重试一次
  （上限 65536），仍失败才记 `failed`。
- **一次提取 = 一条 `ai_job`**：记下模型、提示词模板、工作流、送进去的片段 id、token 用量与
  产出条数；失败也会落一条 `status=failed` 的作业与错误码，不会留下永远 running 的作业。
- **AI 不写正式档案**：提取只产出 `change_proposal`（`status=pending`）+ `proposal_evidence`
  （片段 id 与原句），写入正式表只发生在用户 `ai confirm` 时（规则 C1/C2）。
- **确认时才做字段校验**：`ai show` 会列出「确认前还缺的必填项」，用 `--set 字段=值` 补齐；
  改过内容则建议记为 `modified` 并留下 `final_payload`。
- **时间**：模型只按原文或资料期间给出时间与精度；事项的 `occurred_at` 若模型没给、而资料有期间，
  引擎按期间起点预填并把「时间取自资料期间…」写进建议理由，供审核者核对；资料也没有期间时才留空并要求补齐。
- **跨资料归并**：模型报出的项目 / 系统 / 模块 / 领域若档案里已有同名记录，不再新建，
  改为生成「给已有记录补本次资料来源」的 `link` 建议（需求场景 2）；同一批次内新建的记录，
  先记「待关联」标记，等那条建议被确认后自动回填事项的外键。
- **未证实的量化数据**：模型给出的数字若原文标注为示例或无法核实，`ai show` 与作业说明里会保留
  模型的提醒；写材料前仍需按规则 F1/F4 核对 `achievement_metric` 的 `is_verified`。

## 尚未实现

- 文档解析目前支持 `.txt` / `.md` / `.docx`（`.zip` 会先解开再按目录导入，飞书「批量下载」
  出来的压缩包可以直接喂给 `import`）；PDF、图片（OCR）会在后续步骤接入。
- 飞书侧支持两种身份：应用身份（只能读已授权分享的内容）与用户身份 OAuth（`feishu auth`，
  可读你「我的空间」的全部云文档）。用户身份需要在开放平台配置重定向 URL
  `http://localhost:8765/callback` 并开通对应权限后发布版本，首次授权前 `feishu check`
  会提示还缺哪一步。
- 第 6 步及之后（特征画像、成长曲线、成果案例中心、个人材料中心、Agent 接口、备份迁移）未开始；
  `achievement_*`、`material`、`growth_stage`/`growth_snapshot` 等表已建好但还没有写入方。
- 主题归并（`theme_merge`）与事项级去重尚未做：第 4 步不做标题匹配，语义重叠的事项靠第 5 步的
  `work_theme` + `theme_member` 相似度处理。
- 界面首期只读：审核写操作、导出图片、键盘快捷流在 P2（`docs/UI设计方案.md` 第 9 节）。
- 能力雷达已可用（第 5 步）；阶段对比与成长曲线仍为空态：它们依赖第 7 步的 `growth_stage` / `growth_snapshot` 数据。
- 市场定位只覆盖 51job 列表样本，且没有 JD 正文：`job_requirement` 表已建好，等后续解析 JD 后再写入；
  `salary_benchmark` 也还没有录入行业报告口径的数据。
- 模板与设计文档中的 3 条待确认问题（材料引用粒度、多人协作、confidence 是否用于自动通过）
  仍需产品决策。
