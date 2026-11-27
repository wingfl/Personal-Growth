# -*- coding: utf-8 -*-
"""Inspect the inline images / drawing anchors in a DOCX, in document order."""
import sys, os, zipfile, shutil
from docx import Document
from docx.oxml.ns import qn

src = sys.argv[1]
outdir = sys.argv[2]
os.makedirs(outdir, exist_ok=True)

doc = Document(src)
body = doc.element.body
idx = 0
paras = doc.paragraphs
seq = []
for p in paras:
    blips = p._p.findall('.//' + qn('a:blip'))
    extents = p._p.findall('.//' + qn('wp:extent'))
    if blips:
        for b in blips:
            rid = b.get(qn('r:embed'))
            seq.append((p.text.strip(), rid))
        print(f"P#{idx} text={p.text.strip()!r}")
        for e in extents:
            print("   extent cx=%s cy=%s (EMU)" % (e.get('cx'), e.get('cy')))
    idx += 1

z = zipfile.ZipFile(src)
media = [n for n in z.namelist() if n.startswith('word/media/')]
print("\n--- media parts ---")
for n in media:
    info = z.getinfo(n)
    z.extract(n, outdir)
    print(f"{n}  {info.file_size} bytes -> {os.path.join(outdir, n)}")

print("\n--- rel ids referenced ---")
for text, rid in seq:
    print(rid, repr(text[:60]))
