# -*- coding: utf-8 -*-
"""一次性补丁：重写 infer_period，支持「文件名没写年份」时按指定年份推断期间。

用法：python tools/oneoff/_patch_period.py
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, "app", "importers.py")

NEW_FUNC = r'''def infer_period(filename, default_year=None):
    """从文件名推断资料覆盖的时间范围，返回 (start, end, date_precision)。

    default_year 只对「没写年份」的文件名生效（例如飞书导出的「工作周报（10月10）」）：
    写成 `（10月10）` 的按该日期所在的 ISO 周算，写成 `（9月）` 的按整月算。
    文件名里出现四位年份时一律以文件名为准，不吃 default_year。
    """
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
    if default_year:
        # 「10月10」：按这一天所在的 ISO 周（周一~周日）归档，precision 记 week
        m = re.search(r"(\d{1,2})\s*月\s*([0-3]?\d)\s*[日号]?", name)
        if m and 1 <= int(m.group(1)) <= 12:
            try:
                anchor = date(int(default_year), int(m.group(1)), int(m.group(2)))
            except ValueError:
                anchor = None
            if anchor is not None:
                iso_year, iso_week, _ = anchor.isocalendar()
                start, end = week_range(iso_year, iso_week)
                return date_iso(start), date_iso(end), "week"
        # 「9月」：整月
        m = re.search(r"(\d{1,2})\s*月", name)
        if m and 1 <= int(m.group(1)) <= 12:
            start, end = month_range(int(default_year), int(m.group(1)))
            return date_iso(start), date_iso(end), "month"
    return None, None, None
'''


def main():
    src = io.open(PATH, encoding="utf-8").read()
    start = src.index("def infer_period(filename):")
    end = src.index("# --------------------------------------------------------------------------\n# 导入")
    src = src[:start] + NEW_FUNC + "\n\n" + src[end:]

    old_sig = '''def import_file(store, path, doc_type=None, source_channel="file_upload",
                duplicate_handling="skip", import_batch_id=None, title=None,
                archive_attachment=True):'''
    new_sig = '''def import_file(store, path, doc_type=None, source_channel="file_upload",
                duplicate_handling="skip", import_batch_id=None, title=None,
                archive_attachment=True, default_year=None):'''
    assert old_sig in src
    src = src.replace(old_sig, new_sig, 1)
    assert "period_start, period_end, _precision = infer_period(path)" in src
    src = src.replace("period_start, period_end, _precision = infer_period(path)",
                      "period_start, period_end, _precision = infer_period(path, default_year)", 1)

    old_tsig = '''                external_updated_at=None, fmt="markdown", title_for_infer=None):'''
    new_tsig = '''                external_updated_at=None, fmt="markdown", title_for_infer=None,
                default_year=None):'''
    assert old_tsig in src
    src = src.replace(old_tsig, new_tsig, 1)
    assert "period_start, period_end, _precision = infer_period(infer_name)" in src
    src = src.replace("period_start, period_end, _precision = infer_period(infer_name)",
                      "period_start, period_end, _precision = infer_period(infer_name, default_year)",
                      1)

    io.open(PATH, "w", encoding="utf-8", newline="\n").write(src)
    print("patched", PATH)


if __name__ == "__main__":
    main()
