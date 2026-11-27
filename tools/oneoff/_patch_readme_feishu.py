# -*- coding: utf-8 -*-
"""一次性补丁：README 增加「飞书资料同步」小节并更新进度/目录/自检说明。"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")

FEISHU_SECTION = '''## 飞书资料同步（周报 / 月报）

把飞书知识库与云盘里名称含「周报」「月报」的资料直接拉进原始资料库。
应用凭据按下面的顺序查找，不需要写进代码或出现在命令行里：

1. 环境变量 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
2. `~/.dsh/.credentials.yaml` 的 `refs` 段（本机已登记 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`）
3. 工作区的 `config/feishu.json`（放本机凭据，不进版本库）

```bash
python -m app.cli feishu check                 # 凭据来源、应用令牌、可见知识库、云盘是否可读
python -m app.cli feishu spaces                # 应用可见的知识库列表
python -m app.cli feishu scan                  # 扫描名称含「周报」「月报」的资料（不写库）
python -m app.cli feishu scan --source both    # 知识库 + 云盘一起扫
python -m app.cli feishu pull                  # 导入原始资料库（按 external_id 判重）
python -m app.cli feishu pull --source both --label "飞书首批"
python -m app.cli feishu pull --dry-run        # 只读正文，不写库
```

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
- 权限改动后需要在开放平台**发布应用版本**才会生效。

## 演示数据'''

REPLACEMENTS = [
    (
        "| 2 | 原始资料存储与来源追溯 | ✅ `app/` 建库与导入 |",
        "| 2 | 原始资料存储与来源追溯 | ✅ `app/` 建库、导入与飞书资料同步 |",
    ),
    (
        """             extract.py AI 提取与审核（第 4 步）、cli.py 命令行
tests/       第 1–2 步、第 3 步、第 4 步的自检用例""",
        """             feishu.py 飞书只读接入、feishu_import.py 飞书资料同步、
             extract.py AI 提取与审核（第 4 步）、cli.py 命令行
tests/       第 1–2 步、第 3 步、第 4 步与飞书同步的自检用例""",
    ),
    (
        """             describe_entity.py（查实体字段规格）、step3_demo.sh、step4_demo.sh（演示）""",
        """             describe_entity.py（查实体字段规格）、migrate_db.py（给已有库补新字段）、
             feishu_probe.py（飞书连通性探测）、step3_demo.sh、step4_demo.sh（演示）""",
    ),
    (
        """bash tools/step4_demo.sh           # 用真实模型跑完第 4 步提取→审核→写档（日志 data/step4.log）
```""",
        """bash tools/step4_demo.sh           # 用真实模型跑完第 4 步提取→审核→写档（日志 data/step4.log）
python tools/migrate_db.py --all   # 模型加了字段后，给已有库补列与索引
```""",
    ),
    (
        """## 尚未实现

- 文档解析目前支持 `.txt` / `.md` / `.docx`；PDF、图片（OCR）会在后续步骤接入。""",
        """## 尚未实现

- 文档解析目前支持 `.txt` / `.md` / `.docx`；PDF、图片（OCR）会在后续步骤接入。
- 飞书侧目前只做「应用身份读取已授权的内容」；若要让应用直接读「我的空间」全部云文档，
  需要改用 `user_access_token`（用户 OAuth 授权，需在开放平台配置重定向 URL）。""",
    ),
]

# 把飞书小节插到「## 演示数据」之前
MARKER = "## 演示数据"


def main():
    text = io.open(README, encoding="utf-8").read()
    for index, (old, new) in enumerate(REPLACEMENTS, 1):
        count = text.count(old)
        if count != 1:
            sys.stderr.write("第 %d 处补丁命中 %d 次（应为 1），已中止\n" % (index, count))
            return 1
        text = text.replace(old, new, 1)
        print("✓ 第 %d 处补丁已应用" % index)
    if MARKER not in text:
        sys.stderr.write("找不到插入位置：%s\n" % MARKER)
        return 1
    if "## 飞书资料同步" not in text:
        text = text.replace(MARKER, FEISHU_SECTION, 1)
        print("✓ 已插入飞书资料同步小节")
    io.open(README, "w", encoding="utf-8", newline="\n").write(text)
    print("已写入 README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
