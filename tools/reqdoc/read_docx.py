# -*- coding: utf-8 -*-
"""Dump a DOCX document's paragraphs and tables as plain text."""
import sys
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn


def iter_block_items(parent):
    from docx.document import Document as _Doc
    if isinstance(parent, _Doc):
        parent_elm = parent.element.body
    else:
        parent_elm = parent._tc
    for child in parent_elm.iterchildren():
        if child.tag == qn('w:p'):
            yield Paragraph(child, parent)
        elif child.tag == qn('w:tbl'):
            yield Table(child, parent)


def dump(path):
    doc = Document(path)
    lines = []
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            style = block.style.name if block.style is not None else ''
            text = block.text
            if text.strip():
                lines.append(f"[{style}] {text}")
        else:
            lines.append("=== TABLE ===")
            for row in block.rows:
                cells = [c.text.replace('\n', ' / ').strip() for c in row.cells]
                lines.append(" | ".join(cells))
            lines.append("=== END TABLE ===")
    return "\n".join(lines)


if __name__ == '__main__':
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    content = dump(src)
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"wrote {len(content)} chars to {out}")
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        print(content)
