# -*- coding: utf-8 -*-
"""Render OCR word boxes as a coarse ASCII layout so diagrams can be read spatially."""
import sys, unicodedata
from collections import defaultdict

def char_width(ch):
    if unicodedata.east_asian_width(ch) in ('W', 'F'):
        return 2
    return 1

def render(rows, cols, path, label, x_scale):
    lines = defaultdict(list)
    with open(path, encoding='utf-8') as f:
        header = f.readline()
        for line in f:
            parts = line.rstrip('\n').split('\t')
            if len(parts) != 9:
                continue
            img, W, H, ln, x, y, w, h, text = parts
            if img != label:
                continue
            x, y, w, h = int(x), int(y), int(w), int(h)
            row = y // x_scale
            lines[row].append((x // x_scale, text))

    print(f"### {label}  grid: 1 row = {x_scale}px vertically, 1 col = {x_scale}px horizontally")
    for row in sorted(lines):
        items = sorted(lines[row])
        buf = ''
        for cx, text in items:
            col = cx
            if len(buf) > col:
                buf += ' '
                col = len(buf)
            pad = col - len(buf)
            if pad > 0:
                buf += ' ' * pad
            buf += text
        print(f"{row*x_scale:5d} | {buf}")
    print()


if __name__ == '__main__':
    tsv = sys.argv[1]
    scale = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    labels = sys.argv[3:] if len(sys.argv) > 3 else None
    if not labels:
        seen = []
        with open(tsv, encoding='utf-8') as f:
            f.readline()
            for line in f:
                p = line.split('\t')
                if p[0] not in seen:
                    seen.append(p[0])
        labels = seen
    for lab in labels:
        render(None, None, tsv, lab, scale)
