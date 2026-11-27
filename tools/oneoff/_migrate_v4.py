# -*- coding: utf-8 -*-
"""第六轮：material_citation.section_key 由可空改为必填 + 默认 body + 索引。
它是组合唯一约束 (material_id, section_key, cited_entity_type, cited_entity_id) 的一部分，
可空列会让该约束在 SQL 中失去去重能力（NULL 互不相等）。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "schema", "model.core.json")

OLD = '        { "n": "section_key", "l": "章节位置", "t": "string", "d": "材料中的章节或段落标识" },'
NEW = '        { "n": "section_key", "l": "章节位置", "t": "string", "req": true, "def": "body", "idx": true, "d": "材料中的章节或段落标识，对应材料模板的 section_key；没有章节结构的材料统一填 body。它是组合唯一约束的一部分，不允许为空。" },'


def main():
    with io.open(CORE, encoding="utf-8") as f:
        core = f.read()
    n = core.count(OLD)
    if n != 1:
        print(f"core 中 section_key 定义命中 {n} 次，预期 1 次")
        sys.exit(1)
    with io.open(CORE, "w", encoding="utf-8") as f:
        f.write(core.replace(OLD, NEW))
    print("material_citation.section_key 已改为必填，默认 body，并加索引")


if __name__ == "__main__":
    main()
