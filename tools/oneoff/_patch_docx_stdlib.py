# -*- coding: utf-8 -*-
"""一次性补丁：把 .docx 解析从 python-docx 换成标准库（zipfile + xml.etree）。

原因：产品代码（app/）不得依赖第三方库（ADR-0001），而 app/importers.py 在
`_parse_docx` 里 `from docx import Document`。改为直接读 OOXML。

不可重跑：第二次运行会因为找不到旧文本而退出 1（有意为之）。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
TARGET = ROOT / "app" / "importers.py"

IMPORT_OLD = "import zipfile\nfrom datetime import date, datetime, timezone\n"
IMPORT_NEW = ("import zipfile\nfrom datetime import date, datetime, timezone\n"
              "from xml.etree import ElementTree\n")

NEW_BLOCK = '''W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HEADING_RE = re.compile(r"^(?:Heading|标题)\\s*(\\d+)\\s*$")
_LIST_PREFIX_RE = re.compile(r"^[\\-\\*\\+•·]\\s+")


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
            parts.append("\\n")
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
            match = _HEADING_RE.match(style)
            if match:
                level = int(match.group(1))
                heading_stack = {k: v for k, v in heading_stack.items() if k < level}
                heading_stack[level] = text
                sink.add("heading", text, heading_path(), level)
            elif style.startswith("List") or style.startswith("列表") or _LIST_PREFIX_RE.match(text):
                sink.add("list_item", _LIST_PREFIX_RE.sub("", text), heading_path())
            elif style in ("Quote", "Intense Quote", "引用"):
                sink.add("quote", text, heading_path())
            else:
                sink.add("paragraph", text, heading_path())
        else:
            for cells in _docx_table_rows(element):
                if any(cells):
                    sink.add("table_row", " | ".join(cells), heading_path())


'''


def main():
    text = TARGET.read_text(encoding="utf-8")
    if IMPORT_OLD not in text:
        print("✗ 未找到 import 段落（可能已打过补丁）")
        return 1
    if text.count(IMPORT_OLD) != 1:
        print("✗ import 段落在文件中出现 %d 次" % text.count(IMPORT_OLD))
        return 1
    text = text.replace(IMPORT_OLD, IMPORT_NEW)

    start = text.find("def _parse_docx(")
    end = text.find("def _finish_parse(")
    if start < 0 or end < 0 or end < start:
        print("✗ 未找到 _parse_docx 函数边界")
        return 1
    text = text[:start] + NEW_BLOCK + text[end:]

    if "from docx" in text or "import docx" in text:
        print("✗ 替换后仍存在 docx 导入")
        return 1
    TARGET.write_text(text, encoding="utf-8")
    print("✓ 已把 .docx 解析改为标准库实现（app/importers.py）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
