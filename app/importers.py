# -*- coding: utf-8 -*-
"""原始资料导入：文件 → source_document + source_fragment + attachment。

对应需求第 7 章第 2 步「原始资料存储与来源追溯」与 6.9 的资料导入：
- 正文与字符位置一并落库，原始内容写入后不可修改（模型 imm 字段）；
- 同一文件按 sha256 内容哈希识别重复，重复处理方式写入 duplicate_handling；
- 每个片段都带 heading_path 与 char_start/char_end，可精确定位回原文。
"""
import hashlib
import os
import re
import shutil
import tempfile
import zipfile
from datetime import date, datetime, timezone
from xml.etree import ElementTree

from .ids import date_iso, month_range, now_iso, quarter_range, week_range
from .pathing import attachments_dir, storage_ref
from .store import ROOT

SUPPORTED_EXTS = {".txt", ".md", ".markdown", ".docx"}
ARCHIVE_EXTS = {".zip"}

DOC_TYPE_KEYWORDS = [
    ("weekly_report", ("周报", "本周工作", "双周报")),
    ("monthly_report", ("月报", "本月工作")),
    ("work_log", ("日报", "日志", "工作记录")),
    ("requirement_doc", ("需求", "需求说明", "需求文档")),
    ("product_plan", ("方案", "规划", "计划", "蓝图")),
    ("system_record", ("系统建设", "平台建设", "系统记录", "上线")),
    ("achievement_note", ("复盘", "成果", "案例", "经验")),
    ("work_summary", ("总结", "汇报", "述职")),
    ("project_doc", ("项目",)),
    ("personal_note", ("笔记", "随手记")),
]


# --------------------------------------------------------------------------
# 文本解析
# --------------------------------------------------------------------------
class _Sink:
    """把解析出的块拼成完整正文，并记录每块在正文中的字符区间。"""

    def __init__(self):
        self._parts = []
        self._size = 0
        self.blocks = []

    def add(self, fragment_type, text, heading_path=None, heading_level=None, page_no=None):
        text = text.strip()
        if not text:
            return
        start = self._size
        self._parts.append(text)
        self._size += len(text)
        self.blocks.append({
            "fragment_type": fragment_type,
            "text": text,
            "heading_path": heading_path,
            "heading_level": heading_level,
            "char_start": start,
            "char_end": self._size,
            "page_no": page_no,
        })
        self._parts.append("\n\n")
        self._size += 2

    def text(self):
        return "".join(self._parts).rstrip("\n")


def count_words(text):
    """字数口径：中日韩字符按字计，其余按空白切分的词计。"""
    cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]", text))
    rest = re.sub(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]", " ", text)
    return cjk + len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-_.]*", rest))


def detect_language(text):
    sample = text[:4000]
    cjk = len(re.findall(r"[\u4e00-\u9fff]", sample))
    latin = len(re.findall(r"[A-Za-z]", sample))
    if cjk == 0 and latin == 0:
        return "unknown"
    return "zh-CN" if cjk >= latin * 0.2 else "en"


def _parse_markdown(text, sink):
    lines = text.splitlines()
    heading_stack, para = {}, []
    i = 0

    def heading_path():
        return " / ".join(heading_stack[k] for k in sorted(heading_stack)) or None

    def flush():
        if para:
            sink.add("paragraph", "\n".join(para), heading_path())
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush()
            lang = stripped[3:].strip()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            sink.add("code", "\n".join(buf), heading_path(), None)
            if lang:
                sink.blocks[-1]["anchor_selector"] = "code:" + lang
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            heading_stack = {k: v for k, v in heading_stack.items() if k < level}
            heading_stack[level] = title
            sink.add("heading", title, heading_path(), level)
            i += 1
            continue

        if stripped.startswith(">"):
            flush()
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            sink.add("quote", "\n".join(buf), heading_path())
            continue

        m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            flush()
            sink.add("list_item", m.group(1), heading_path())
            i += 1
            continue

        if stripped.startswith("|") and stripped.count("|") >= 2:
            flush()
            if re.fullmatch(r"\|[\s:|-]+\|?", stripped):
                i += 1
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            sink.add("table_row", " | ".join(cells), heading_path())
            i += 1
            continue

        if not stripped:
            flush()
            i += 1
            continue

        para.append(line.rstrip())
        i += 1

    flush()


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# 注意：styles.xml 里的样式名是小写的（"heading 1"），而 styleId 是 "Heading1"；
# python-docx 会把内置样式名规范成 "Heading 1"。这里两种都接受，大小写不敏感。
_HEADING_RE = re.compile(r"^(?:heading|标题)\s*(\d+)\s*$", re.IGNORECASE)
_LIST_PREFIX_RE = re.compile(r"^[\-\*\+•·]\s+")
_QUOTE_STYLES = {"quote", "intense quote", "引用"}


def _docx_style_names(archive):
    """从 word/styles.xml 读出 styleId → 样式名（如 Heading 1、List Paragraph）。"""
    try:
        raw = archive.read("word/styles.xml")
    except KeyError:
        return {}
    names = {}
    for style in ElementTree.fromstring(raw).iter(W_NS + "style"):
        style_id = style.get(W_NS + "styleId")
        node = style.find(W_NS + "name")
        if style_id and node is not None:
            names[style_id] = node.get(W_NS + "val") or style_id
    return names


def _docx_paragraph_text(paragraph):
    """按出现顺序拼接段落里的文本（w:t），把 w:tab / w:br 还原成空白与换行。"""
    parts = []
    for node in paragraph.iter():
        if node.tag == W_NS + "t":
            parts.append(node.text or "")
        elif node.tag == W_NS + "tab":
            parts.append(" ")
        elif node.tag in (W_NS + "br", W_NS + "cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _docx_iter_body(body):
    """按文档顺序产出 (kind, element)；kind 为 p 或 tbl。

    w:sdt（内容控件）会包住段落/表格，这里下钻一层，避免漏内容。
    """
    for child in body:
        if child.tag == W_NS + "sdt":
            content = child.find(W_NS + "sdtContent")
            if content is not None:
                for item in _docx_iter_body(content):
                    yield item
        elif child.tag == W_NS + "p":
            yield "p", child
        elif child.tag == W_NS + "tbl":
            yield "tbl", child


def _docx_table_rows(table):
    """把 w:tbl 展开成若干行，每行是单元格文本列表（单元格内多段用空格连接）。"""
    rows = []
    for row in table.findall(W_NS + "tr"):
        cells = []
        for cell in row.findall(W_NS + "tc"):
            texts = [_docx_paragraph_text(p) for p in cell.findall(W_NS + "p")]
            cells.append(" ".join(t for t in texts if t))
        rows.append(cells)
    return rows


def _parse_docx(path, sink):
    """解析 .docx（OOXML）——只用标准库 zipfile + xml.etree。

    正文在 word/document.xml，样式名在 word/styles.xml，表格是 w:tbl/w:tr/w:tc；
    遍历顺序与段落/表格在文档里的实际顺序一致（见 ADR-0001）。
    """
    with zipfile.ZipFile(path) as archive:
        style_names = _docx_style_names(archive)
        try:
            raw = archive.read("word/document.xml")
        except KeyError:
            raise ValueError("不是有效的 .docx（缺少 word/document.xml）：%s" % path)
    root = ElementTree.fromstring(raw)
    body = root.find(W_NS + "body")
    if body is None:
        raise ValueError("不是有效的 .docx（缺少 body）：%s" % path)

    heading_stack = {}

    def heading_path():
        return " / ".join(heading_stack[k] for k in sorted(heading_stack)) or None

    for kind, element in _docx_iter_body(body):
        if kind == "p":
            text = _docx_paragraph_text(element)
            if not text:
                continue
            style_id = ""
            props = element.find(W_NS + "pPr")
            if props is not None:
                style_node = props.find(W_NS + "pStyle")
                if style_node is not None:
                    style_id = style_node.get(W_NS + "val") or ""
            style = style_names.get(style_id, style_id)
            style_key = style.strip().lower()
            match = _HEADING_RE.match(style.strip())
            if match:
                level = int(match.group(1))
                heading_stack = {k: v for k, v in heading_stack.items() if k < level}
                heading_stack[level] = text
                sink.add("heading", text, heading_path(), level)
            elif (style_key.startswith("list") or style.startswith("列表")
                  or _LIST_PREFIX_RE.match(text)):
                sink.add("list_item", _LIST_PREFIX_RE.sub("", text), heading_path())
            elif style_key in _QUOTE_STYLES:
                sink.add("quote", text, heading_path())
            else:
                sink.add("paragraph", text, heading_path())
        else:
            for cells in _docx_table_rows(element):
                if any(cells):
                    sink.add("table_row", " | ".join(cells), heading_path())


def _finish_parse(sink):
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
        for para in re.split(r"\n\s*\n", text):
            sink.add("paragraph", para)
    return _finish_parse(sink)


def parse_file(path):
    """解析文件，返回 (full_text, blocks, meta)。"""
    ext = os.path.splitext(path)[1].lower()
    sink = _Sink()
    if ext not in SUPPORTED_EXTS:
        raise ValueError("暂不支持的文件类型：%s（当前支持 %s）"
                         % (ext or "无扩展名", "、".join(sorted(SUPPORTED_EXTS))))
    if ext == ".docx":
        _parse_docx(path, sink)
    else:
        with open(path, encoding="utf-8", errors="replace") as fp:
            text = fp.read().lstrip("\ufeff")
        if ext in (".md", ".markdown"):
            _parse_markdown(text, sink)
        else:
            for para in re.split(r"\n\s*\n", text):
                sink.add("paragraph", para)
    return _finish_parse(sink)


# --------------------------------------------------------------------------
# 文件名推断
# --------------------------------------------------------------------------
def infer_doc_type(filename):
    name = os.path.basename(filename)
    for doc_type, keywords in DOC_TYPE_KEYWORDS:
        if any(kw in name for kw in keywords):
            return doc_type
    return "other"


def infer_period(filename):
    """从文件名推断资料覆盖的时间范围，返回 (start, end, date_precision)。"""
    name = os.path.basename(filename)
    m = re.search(r"(20\d{2})\s*[-_年]?\s*[Qq季]\s*([1-4])", name)
    if m:
        year, quarter = int(m.group(1)), int(m.group(2))
        start, end = quarter_range(year, quarter)
        return date_iso(start), date_iso(end), "quarter"
    m = re.search(r"(20\d{2})\s*[-_年]?\s*第?\s*(\d{1,2})\s*周", name)
    if m:
        year, week = int(m.group(1)), int(m.group(2))
        if 1 <= week <= 53:
            try:
                start, end = week_range(year, week)
                return date_iso(start), date_iso(end), "week"
            except ValueError:
                pass
    m = re.search(r"(20\d{2})\s*[-_年]\s*(\d{1,2})\s*月?", name)
    if m and 1 <= int(m.group(2)) <= 12:
        start, end = month_range(int(m.group(1)), int(m.group(2)))
        return date_iso(start), date_iso(end), "month"
    m = re.search(r"(20\d{2})", name)
    if m:
        year = int(m.group(1))
        return date_iso(date(year, 1, 1)), date_iso(date(year, 12, 31)), "year"
    return None, None, None


# --------------------------------------------------------------------------
# 导入
# --------------------------------------------------------------------------
def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


MIME_BY_EXT = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def import_file(store, path, doc_type=None, source_channel="file_upload",
                duplicate_handling="skip", import_batch_id=None, title=None,
                archive_attachment=True):
    """导入单个文件，返回结果字典。

    重复判定以 sha256 内容哈希为准；duplicate_handling 决定如何处理：
      skip（默认）/ new_version（另存新版本并指向原版本）/ import_anyway。
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    content_hash = sha256_file(path)
    ext = os.path.splitext(path)[1].lower()

    previous = store.find_one("source_document", content_hash=content_hash)
    if previous and duplicate_handling == "skip":
        if import_batch_id:
            batch = store.get("import_batch", import_batch_id)
            store.update("import_batch", import_batch_id,
                         {"duplicate_count": (batch["duplicate_count"] or 0) + 1},
                         expected_revision=batch["revision"])
        return {"status": "duplicate", "document_id": previous["id"], "content_hash": content_hash,
                "version_no": previous["version_no"], "title": previous["title"],
                "fragment_count": store.count("source_fragment", {"document_id": previous["id"]})}

    full_text, blocks, meta = parse_file(path)
    if not full_text.strip():
        raise ValueError("文件没有可入库的文本内容：%s" % path)

    period_start, period_end, _precision = infer_period(path)
    doc_type = doc_type or infer_doc_type(path)
    title = title or os.path.splitext(os.path.basename(path))[0]
    version_no = (previous["version_no"] or 1) + 1 if (previous and duplicate_handling != "import_anyway") else 1

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
        "origin": "import",
    })

    _insert_fragments(store, doc_id, blocks)

    attachment_id = None
    if archive_attachment:
        attach_dir = attachments_dir(store.db_path)
        os.makedirs(attach_dir, exist_ok=True)
        stored_name = "%s_%s" % (content_hash[:12], os.path.basename(path))
        stored_path = os.path.join(attach_dir, stored_name)
        if not os.path.exists(stored_path):
            shutil.copy2(path, stored_path)
        # 统一口径：相对数据库目录（跨盘符时退回绝对路径），见 app/pathing.py
        stored_ref = storage_ref(store.db_path, stored_path)
        attachment_id = store.insert("attachment", {
            "owner_type": "source_document",
            "owner_id": doc_id,
            "file_name": os.path.basename(path),
            "storage_path": stored_ref,
            "content_hash": content_hash,
            "mime_type": MIME_BY_EXT.get(ext),
            "file_size": os.path.getsize(path),
            "storage_backend": "local_file",
            "file_modified_at": datetime.fromtimestamp(
                os.path.getmtime(path), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "origin": "import",
        })

    store.update("source_document", doc_id,
                 {"attachment_id": attachment_id, "processing_status": "extracted"},
                 expected_revision=None, remark="导入完成")

    return {"status": "imported", "document_id": doc_id, "content_hash": content_hash,
            "title": title, "doc_type": doc_type, "version_no": version_no,
            "fragment_count": len(blocks), "word_count": meta["word_count"],
            "period_start": period_start, "period_end": period_end,
            "attachment_id": attachment_id}


def _insert_fragments(store, doc_id, blocks):
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


def extract_archive(path, dest):
    """把 zip 里的可导入文件解到 dest，返回解出的文件路径列表。

    跳过目录项、`__MACOSX/` 与隐藏文件；拒绝越界路径（zip slip）。
    """
    if not zipfile.is_zipfile(path):
        raise ValueError("不是有效的 zip 压缩包：%s" % path)
    root = os.path.realpath(dest)
    extracted = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            base = os.path.basename(name)
            if name.startswith("__MACOSX/") or base.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() not in SUPPORTED_EXTS:
                continue
            target = os.path.realpath(os.path.join(root, name))
            if target != root and not target.startswith(root + os.sep):
                raise ValueError("压缩包里有越界路径，已拒绝：%s" % info.filename)
            folder = os.path.dirname(target)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(target)
    if not extracted:
        raise ValueError("压缩包里没有可导入的文件（支持 %s）：%s"
                         % ("、".join(sorted(SUPPORTED_EXTS)), path))
    return extracted


def import_path(store, path, recursive=False, batch_label=None, **kwargs):
    """导入文件或目录（`.zip` 会先解开再按目录导入）。目录会建立一个 import_batch 并汇总计数。"""
    source_channel = kwargs.pop("source_channel", "file_upload")
    if os.path.isfile(path):
        if os.path.splitext(path)[1].lower() in ARCHIVE_EXTS:
            tmp = tempfile.mkdtemp(prefix="growth-archive-")
            try:
                extract_archive(path, tmp)
                result = import_path(store, tmp, recursive=True,
                                     batch_label=batch_label or os.path.basename(path),
                                     source_channel=source_channel, **kwargs)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            result["archive"] = os.path.basename(path)
            return result
        return import_file(store, path, source_channel=source_channel, **kwargs)

    files = []
    for base, _dirs, names in os.walk(path) if recursive else [(path, [], os.listdir(path))]:
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() in SUPPORTED_EXTS:
                files.append(os.path.join(base, name))
    if not files:
        raise ValueError("目录中没有可导入的文件（支持 %s）：%s"
                         % ("、".join(sorted(SUPPORTED_EXTS)), path))

    batch_id = store.insert("import_batch", {
        "source_channel": source_channel,
        "file_count": len(files),
        "status": "running",
        "initiated_by": "user",
        "started_at": now_iso(),
        "batch_label": batch_label or os.path.basename(os.path.abspath(path)),
        "total_size_bytes": sum(os.path.getsize(f) for f in files),
    })
    results, succeeded, failed, duplicated = [], 0, 0, 0
    for item in files:
        try:
            result = import_file(store, item, source_channel=source_channel,
                                 import_batch_id=batch_id, **kwargs)
        except Exception as exc:  # 单个文件失败不阻断整批
            failed += 1
            results.append({"status": "failed", "path": item, "error": str(exc)})
            continue
        results.append(result)
        if result["status"] == "duplicate":
            duplicated += 1
        else:
            succeeded += 1

    batch = store.get("import_batch", batch_id)
    store.update("import_batch", batch_id, {
        "success_count": succeeded,
        "failed_count": failed,
        "duplicate_count": duplicated,
        "status": "succeeded" if failed == 0 else "failed",
        "finished_at": now_iso(),
        "failure_reason": None if failed == 0 else "%d 个文件导入失败" % failed,
    }, expected_revision=batch["revision"])
    return {"status": "batch", "batch_id": batch_id, "file_count": len(files),
            "imported": succeeded, "duplicate": duplicated, "failed": failed,
            "results": results}
