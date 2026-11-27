# -*- coding: utf-8 -*-
"""一次性补丁：给 app/importers.py 增加「外部来源文本导入」能力。

- 抽出 _finish_parse(sink)，parse_file / parse_text 共用；
- 抽出 _insert_fragments(store, doc_id, blocks)；
- 新增 parse_text(text, fmt) 与 import_text(...)，供飞书云文档导入复用同一套
  片段切分与来源追溯逻辑（需求 6.9 原始资料导入、1.4③ 保留来源）。
每处替换都断言恰好命中一次，全部在内存改完后一次性落盘。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "importers.py")

FINISH_HELPERS = '''def _finish_parse(sink):
    """把 _Sink 里累积的块整理成 (full_text, blocks, meta)。"""
    full_text = sink.text()
    blocks = []
    for order, block in enumerate(sink.blocks):
        block = dict(block)
        block["order_index"] = order
        block["text_hash"] = hashlib.sha256(block["text"].encode("utf-8")).hexdigest()
        block["parse_confidence"] = 1.0
        blocks.append(block)
    meta = {
        "word_count": count_words(full_text),
        "language": detect_language(full_text),
        "char_count": len(full_text),
    }
    return full_text, blocks, meta


def parse_text(text, fmt="markdown"):
    """解析内存中的文本（飞书云文档等外部来源），返回 (full_text, blocks, meta)。

    fmt="markdown" 走 Markdown 规则；其他值按空行切段落。
    """
    sink = _Sink()
    if fmt == "markdown":
        _parse_markdown(text, sink)
    else:
        for para in re.split(r"\\n\\s*\\n", text):
            sink.add("paragraph", para)
    return _finish_parse(sink)


def parse_file(path):'''

IMPORT_HELPERS = '''def _insert_fragments(store, doc_id, blocks):
    """把解析出的块写成 source_fragment，并保留正文中的字符区间。"""
    for block in blocks:
        store.insert("source_fragment", {
            "document_id": doc_id,
            "order_index": block["order_index"],
            "fragment_type": block["fragment_type"],
            "heading_path": block["heading_path"],
            "text": block["text"],
            "char_start": block["char_start"],
            "char_end": block["char_end"],
            "parse_confidence": block["parse_confidence"],
            "anchor_selector": block.get("anchor_selector"),
            "text_hash": block["text_hash"],
            "heading_level": block["heading_level"],
            "page_no": block["page_no"],
        }, write_audit=False)


def _bump_duplicate(store, import_batch_id):
    batch = store.get("import_batch", import_batch_id)
    store.update("import_batch", import_batch_id,
                 {"duplicate_count": (batch["duplicate_count"] or 0) + 1},
                 expected_revision=batch["revision"])


def import_text(store, title, text, doc_type=None, source_channel="third_party_import",
                duplicate_handling="skip", import_batch_id=None, period_start=None,
                period_end=None, external_id=None, external_url=None,
                external_updated_at=None, fmt="markdown", title_for_infer=None):
    """把外部来源（飞书云文档等）的正文导入为原始资料。

    判重优先按 external_id（同一篇外部文档重新拉取），其次按正文 sha256。
    返回结构中的 url 字段即 external_url，便于回原文核对。
    """
    if not (text or "").strip():
        raise ValueError("外部文档没有可入库的文本内容：%s" % title)
    full_text, blocks, meta = parse_text(text, fmt=fmt)
    if not full_text.strip():
        raise ValueError("外部文档没有可入库的文本内容：%s" % title)
    content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()

    previous = None
    if external_id:
        previous = store.find_one("source_document", external_id=external_id)
    if previous is None:
        previous = store.find_one("source_document", content_hash=content_hash)
    if previous and duplicate_handling == "skip":
        if import_batch_id:
            _bump_duplicate(store, import_batch_id)
        return {"status": "duplicate", "document_id": previous["id"],
                "content_hash": content_hash, "title": previous["title"],
                "version_no": previous["version_no"],
                "fragment_count": store.count("source_fragment", {"document_id": previous["id"]})}

    infer_name = title_for_infer or title
    if period_start is None and period_end is None:
        period_start, period_end, _precision = infer_period(infer_name)
    doc_type = doc_type or infer_doc_type(infer_name)
    version_no = ((previous["version_no"] or 1) + 1
                  if (previous and duplicate_handling != "import_anyway") else 1)

    doc_id = store.insert("source_document", {
        "title": title,
        "doc_type": doc_type,
        "source_channel": source_channel,
        "period_start": period_start,
        "period_end": period_end,
        "raw_text": full_text,
        "content_hash": content_hash,
        "import_batch_id": import_batch_id,
        "processing_status": "pending",
        "duplicate_handling": duplicate_handling if previous else None,
        "summary": full_text[:200],
        "word_count": meta["word_count"],
        "language": meta["language"],
        "duplicate_of_id": previous["id"] if (previous and version_no > 1) else None,
        "version_no": version_no,
        "external_id": external_id,
        "external_url": external_url,
        "external_updated_at": external_updated_at,
        "origin": "import",
    })
    _insert_fragments(store, doc_id, blocks)
    store.update("source_document", doc_id, {"processing_status": "extracted"},
                 remark="外部来源导入完成")

    return {"status": "imported", "document_id": doc_id, "content_hash": content_hash,
            "title": title, "doc_type": doc_type, "version_no": version_no,
            "fragment_count": len(blocks), "word_count": meta["word_count"],
            "period_start": period_start, "period_end": period_end,
            "external_id": external_id, "url": external_url}


def import_path(store, path, recursive=False, batch_label=None, **kwargs):'''

REPLACEMENTS = [
    # 1) parse_file 尾部改为共用 _finish_parse，并在其前插入 parse_text
    (
        '''    full_text = sink.text()
    blocks = []
    for order, block in enumerate(sink.blocks):
        block = dict(block)
        block["order_index"] = order
        block["text_hash"] = hashlib.sha256(block["text"].encode("utf-8")).hexdigest()
        block["parse_confidence"] = 1.0
        blocks.append(block)
    meta = {
        "word_count": count_words(full_text),
        "language": detect_language(full_text),
        "char_count": len(full_text),
    }
    return full_text, blocks, meta


# --------------------------------------------------------------------------
# 文件名推断''',
        '''    return _finish_parse(sink)


# --------------------------------------------------------------------------
# 文件名推断''',
    ),
    # 2) 在 parse_file 之前插入 _finish_parse 与 parse_text
    (
        "def parse_file(path):",
        FINISH_HELPERS,
    ),
    # 3) import_file 的片段写入改为共用 _insert_fragments
    (
        '''    for block in blocks:
        store.insert("source_fragment", {
            "document_id": doc_id,
            "order_index": block["order_index"],
            "fragment_type": block["fragment_type"],
            "heading_path": block["heading_path"],
            "text": block["text"],
            "char_start": block["char_start"],
            "char_end": block["char_end"],
            "parse_confidence": block["parse_confidence"],
            "anchor_selector": block.get("anchor_selector"),
            "text_hash": block["text_hash"],
            "heading_level": block["heading_level"],
            "page_no": block["page_no"],
        }, write_audit=False)''',
        "    _insert_fragments(store, doc_id, blocks)",
    ),
    # 4) 在 import_path 之前插入 _insert_fragments / _bump_duplicate / import_text
    (
        "def import_path(store, path, recursive=False, batch_label=None, **kwargs):",
        IMPORT_HELPERS,
    ),
]


def main():
    text = io.open(TARGET, encoding="utf-8").read()
    for index, (old, new) in enumerate(REPLACEMENTS, 1):
        count = text.count(old)
        if count != 1:
            sys.stderr.write("第 %d 处补丁命中 %d 次（应为 1 次），已中止，文件未改动\n"
                             % (index, count))
            return 1
        text = text.replace(old, new, 1)
        print("✓ 第 %d 处补丁已应用" % index)
    io.open(TARGET, "w", encoding="utf-8", newline="\n").write(text)
    print("已写入 %s" % os.path.relpath(TARGET, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
