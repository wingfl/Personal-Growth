# -*- coding: utf-8 -*-
"""一次性补丁：为「飞书等外部来源导入」补字段。

1) source_channel 枚举增加 feishu；
2) source_document 增加 external_id / external_url / external_updated_at，
   用于记录外部系统的对象标识与原文链接（需求 1.4③「重要数据必须保留来源」、
   6.9「原始资料导入」）。

补丁在内存中完成，全部断言通过后一次性落盘。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "schema", "model.core.json")

ENUM_ADD = ("feishu", "飞书", "从飞书云文档 / 知识库按应用身份读取")


def main():
    model = json.load(io.open(CORE, encoding="utf-8"))
    problems = []

    # 1) source_channel 增加 feishu
    values = model["enums"]["source_channel"]["v"]
    codes = [v[0] for v in values]
    if "feishu" not in codes:
        values.append(list(ENUM_ADD))
        print("+ source_channel 增加取值 feishu")
    else:
        print("= source_channel 已有 feishu")

    # 2) source_document 增加外部来源字段
    doc = [e for e in model["entities"] if e["id"] == "source_document"]
    if not doc:
        problems.append("找不到实体 source_document")
    else:
        fields = doc[0]["fields"]
        existing = {f["n"] for f in fields}
        add = [
            {
                "n": "external_id",
                "l": "外部对象标识",
                "t": "string",
                "idx": True,
                "d": "外部系统（如飞书）中的文档 token，用于判断同一篇外部文档是否已导入、是否发生更新",
            },
            {
                "n": "external_url",
                "l": "原文链接",
                "t": "string",
                "d": "外部系统里该文档的访问链接，便于回原文核对",
            },
            {
                "n": "external_updated_at",
                "l": "外部修改时间",
                "t": "datetime",
                "d": "外部系统记录的最后修改时间（UTC），用于判断资料是否有更新版本",
            },
        ]
        for item in add:
            if item["n"] in existing:
                print("= source_document 已有字段 %s" % item["n"])
                continue
            fields.append(item)
            print("+ source_document 增加字段 %s" % item["n"])

    if problems:
        for p in problems:
            sys.stderr.write("错误：%s\n" % p)
        return 1

    text = json.dumps(model, ensure_ascii=False, indent=2) + "\n"
    io.open(CORE, "w", encoding="utf-8", newline="\n").write(text)
    print("已写入 %s" % os.path.relpath(CORE, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
