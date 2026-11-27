# 数据模型 part 文件编写规范

本目录下的 `*.entities.json` 用于**补全各层的业务字段**。骨架（分层、通用字段、枚举、已登记字段）在 `../model.core.json`，各 part 只负责自己那部分实体的**其余业务字段**。

## 你要产出什么

一个 JSON 文件，形如：

```json
{
  "$comment": "02_experience 与 03_achievement 层业务字段补全",
  "entities": [
    {
      "id": "project",
      "fields": [
        { "n": "code", "l": "项目代号", "t": "string", "d": "内部简称或立项编号，用于在列表中快速识别；无编号时可空。", "idx": true }
      ],
      "rules": [
        "`end_date` 早于 `start_date` 时校验失败。"
      ],
      "notes": [
        "项目与系统的关系是多对多，通过 `entity_relation` 表达，不在本表建外键。"
      ]
    }
  ]
}
```

- `entities[].id` 必须是 `../model.core.json` 中已登记的实体 id，**不得新增实体**。
- `fields` 只写该实体**还没有的**字段（core 里已有的字段会自动合并，重复的会被忽略，所以写重复等于白写；但也不要依赖这一点）。
- `rules`（可选）：该实体的跨字段业务约束，每条一句话，用反引号引用字段名。写实质规则（时间区间、状态机、互斥字段、派生字段口径），不写「必须填写有效数据」这类废话。
- `notes`（可选）：需要设计者知道但无法用规则表达的取舍说明。

## 字段对象的键（只能用这几个）

| 键 | 必填 | 含义 |
| --- | --- | --- |
| `n` | 是 | 字段名，小写蛇形，全模型唯一（同一实体内不得重复） |
| `l` | 是 | 中文名 |
| `t` | 是 | 类型，取值见下表 |
| `d` | 是 | 说明。写清 **来源 / 计算口径 / 用途** 中的关键点，至少 10 个字，禁止写「备注」「其他」这类空话 |
| `req` | 否 | `true` 表示必填（非空）。慎用：只有业务上确实不可能为空的字段才标 |
| `u` | 否 | `true` 表示唯一 |
| `idx` | 否 | `true` 表示需要索引（只给真正会被查询/排序/过滤的字段） |
| `imm` | 否 | `true` 表示写入后不可修改（原始资料、快照、日志类字段） |
| `e` | 否 | 枚举名，仅当 `t = "enum"` |
| `def` | 否 | 默认值 |
| `ref` | 否 | 外键目标实体 id，仅当 `t = "ref"`；指向「实体类型」本身的用 `ENTITY_TYPE` |

类型取值：`uuid` `string` `text` `longtext` `enum` `date` `datetime` `integer` `decimal` `boolean` `json` `ref` `file`

约定：日期用 `date`，时点用 `datetime`（UTC）；布尔用 `boolean` 且名字以 `is_`/`has_` 开头；数值在 `d` 里写单位；结构化数据用 `json`。

## 硬性要求

1. **不得新增枚举。** 只能用 `../model.core.json` 的 `enums` 里已有的枚举名与取值（取值不要写进 part 文件）。如果确实缺枚举，在 `notes` 里写出来，不要自己造。
2. **不得修改或删除 core 已有字段。** 如果认为 core 的某个字段设计有问题，写在 `notes` 里。
3. **不得新增实体。** 缺实体写在 `notes` 里。
4. 每个实体至少补 3 个字段；字段要有信息量，不要为了凑数把同一件事拆成两个字段。
5. `d` 的写法要像给实现者看的注释：例如「记录该事项发生的具体日期；`date_precision` 为 month 时表示该月首日，展示时不显示到日」。
6. **遵循需求文档的三条底线**：原始内容不可修改、AI 产出不能直接进正式档案、事实与推断与评价必须能区分。凡是可能由 AI 产生的实体，要保证 `origin` / `review_status` 能表达出来（通用字段组已提供，不要重复定义）。

## 自检（必须做）

写完后运行：

```
cd /d/deepseek-workspace/个人成长 && PYTHONIOENCODING=utf-8 python tools/check_part.py schema/parts/<你的文件>
```

输出必须为 `OK`，退出码 0。有报错就改到通过为止。

## 参考

- 需求原文：`tools/reqdoc/out/doc_dump.txt`（由 `tools/reqdoc/` 下的脚本从需求文档提取）
- 骨架与枚举：`schema/model.core.json`
- 已有字段查询：`python -c "import json;m=json.load(open('schema/model.core.json',encoding='utf-8'));print([f['n'] for e in m['entities'] if e['id']=='project' for f in e['fields']])"`
