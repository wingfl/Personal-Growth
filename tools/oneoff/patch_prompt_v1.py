# -*- coding: utf-8 -*-
"""更新 prompts/document_extract.v1.json：
1) json 类字段要求输出数组（deliverables / collaborators）；
2) 新增 link_existing 分节：模型指出这份资料属于哪些已有记录 → 引擎生成「补来源」建议；
3) 同步 output_schema 与取值口径说明。
每处替换都断言恰好命中一次，失败即退出且不写文件。
"""
import json
import os
import sys

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "prompts", "document_extract.v1.json")


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        print("✗ %s：预期命中 1 次，实际 %d 次" % (label, text.count(old)))
        sys.exit(1)
    return text.replace(old, new)


with open(PATH, encoding="utf-8") as fp:
    doc = json.load(fp)

# 1) system_prompt 增补一条硬约束
doc["system_prompt"] = replace_once(
    doc["system_prompt"],
    "8. 事实、推断、评价必须分开表达：评价性内容不要写进 content，可放进 notes。",
    "8. 事实、推断、评价必须分开表达：评价性内容不要写进 content，可放进 notes。\n"
    "9. 如果这份资料整体属于档案里某条已有记录（例如某个项目的复盘、某个系统的建设记录），"
    "请在 link_existing 里用该记录的准确名称列出它，不要重复放进 new_*。",
    "system_prompt 第 9 条")

# 2) 取值口径：json 字段必须是数组
doc["user_prompt_template"] = replace_once(
    doc["user_prompt_template"],
    "date_precision 只能取：{date_precision_values}\n",
    "date_precision 只能取：{date_precision_values}\n"
    "deliverables、collaborators 是数组字段，必须输出 JSON 数组"
    "（例如 [\"指标定义模板\", \"12 个核心指标定义\"]），不要写成用分号拼接的一句话。\n",
    "取值口径 json 数组说明")

# 3) 输出结构：deliverables / collaborators 改成数组
doc["user_prompt_template"] = replace_once(
    doc["user_prompt_template"],
    '      "deliverables": "交付物名称；原文提到才填",\n'
    '      "collaborators": "协作方；原文提到才填",\n',
    '      "deliverables": ["交付物名称"],\n'
    '      "collaborators": ["协作方"],\n',
    "输出结构 deliverables/collaborators")

# 4) 输出结构：新增 link_existing
doc["user_prompt_template"] = replace_once(
    doc["user_prompt_template"],
    '  "notes": "本次提取中不确定、需要用户确认的地方；没有就留空字符串"',
    '  "link_existing": [\n'
    '    {"entity": "project / business_system / function_module / work_domain / work_item",\n'
    '     "name": "档案里已有记录的准确名称（必须与【档案里已有的记录】里的写法一致）",\n'
    '     "reason": "为什么这份资料属于这条已有记录，一句话",\n'
    '     "evidence": [{"fragment_id": "片段 id", "quote": "关键原句"}]}\n'
    '  ],\n'
    '  "notes": "本次提取中不确定、需要用户确认的地方；没有就留空字符串"',
    "输出结构 link_existing")

# 5) output_format_note
doc["output_format_note"] = replace_once(
    doc["output_format_note"],
    "枚举取值只能取上面列出的值。",
    "枚举取值只能取上面列出的值；数组字段必须用 JSON 数组；link_existing 只列档案里已有的记录。",
    "output_format_note")

# 6) output_schema
schema = doc["output_schema"]
props = schema["properties"]
items = props["items"]["items"]["properties"]
items["deliverables"] = {"type": "array", "items": {"type": "string"}}
items["collaborators"] = {"type": "array", "items": {"type": "string"}}
props["link_existing"] = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["entity", "name"],
        "properties": {
            "entity": {"type": "string"},
            "name": {"type": "string"},
            "reason": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "object"}},
        },
    },
}

# 7) 工作流步骤说明里补一句，保持与实现一致
for step in doc["workflow"]["steps"]:
    if "change_proposal" in json.dumps(step, ensure_ascii=False) and "proposal_evidence" in json.dumps(step, ensure_ascii=False):
        step["detail"] = (step.get("detail") or "") + \
            "；已有的项目/系统/模块用 link 建议补来源，不新建记录"

with open(PATH, "w", encoding="utf-8") as fp:
    json.dump(doc, fp, ensure_ascii=False, indent=2)
    fp.write("\n")
print("✓ 已更新 %s（%d 字节）" % (os.path.relpath(PATH), os.path.getsize(PATH)))
