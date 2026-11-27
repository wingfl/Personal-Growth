# -*- coding: utf-8 -*-
"""一次性补文档：期间推断、批量确认、提取健壮性与长任务纪律。"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def patch(rel, pairs):
    path = os.path.join(ROOT, rel)
    with io.open(path, encoding="utf-8") as fp:
        text = fp.read()
    for old, new in pairs:
        count = text.count(old)
        assert count == 1, "%s 命中 %d 次：%r" % (rel, count, old[:40])
        text = text.replace(old, new)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(text)
    print("ok", rel)


patch("docs/模块与接口.md", [
    ("| `import PATH...` | `--type`、`--channel`（默认 `file_upload`）、"
     "`--handling {skip,new_version,import_anyway}`（默认 `skip`）、`--recursive`、`--label` | "
     "`app/cli.py:983`，参数 `:984-990` |",
     "| `import PATH...` | `--type`、`--channel`（默认 `file_upload`）、"
     "`--handling {skip,new_version,import_anyway}`（默认 `skip`）、`--recursive`、`--label`、"
     "`--year`（文件名没写四位年份时按该年推断期间） | `app/cli.py:1021`，参数 `:1022-1031` |\n"
     "| `periods` | `--year`（必填）、`--dry-run`（只预览不改库） | "
     "`app/cli.py:1033`，参数 `:1034-1037` |"),

    ("| `infer_period(filename) -> (start, end, precision)` | 期间与精度 | "
     "—（`app/importers.py:348`） |",
     "| `infer_period(filename, default_year=None) -> (start, end, precision)` | "
     "期间与精度；文件名没有四位年份且给了 `default_year` 时，按「N月N日」推该日所在 ISO 周、"
     "「N月」推整月 | —（`app/importers.py:349`） |"),

    ("`max_tokens` 默认 16384（`app/llm.py:23`、`:24`、`:25`、`:27`）",
     "`max_tokens` 默认 32768（`app/llm.py:23`、`:24`、`:25`、`:27`）；推理型模型会把预算花在推理上，"
     "16384 时常出现 `finish_reason=length` 截断，`run()` 遇到截断会用翻倍预算重试一次（上限 65536）"),

    ("| `review.reject(proposal_id, note=None, actor_type=\"user\") -> dict` | "
     "`{proposal_id, status: \"rejected\"}` | `ExtractError`（`app/extract.py:747`） |",
     "| `review.reject(proposal_id, note=None, actor_type=\"user\") -> dict` | "
     "`{proposal_id, status: \"rejected\"}` | `ExtractError`（`app/extract.py:747`） |\n"
     "| `review.confirm_batch(job_id=None, batch_id=None, note=None, fill_missing=True, "
     "limit=2000, actor_type=\"user\") -> dict` | `{total, confirmed, modified, failed, "
     "confirmed_ids, modified_ids}`；缺 `occurred_at` 的 `work_item` 用所属资料的期间起点补齐 | "
     "—（`app/extract.py:762`） |"),

    ("| `ai extract DOCUMENT_ID` | `--model`、`--max-fragments`、`--temperature`、`--max-tokens`、"
     "`--trigger`（默认 `manual`）、`--dry-run` | `app/cli.py:1177`，参数 `:1178-1184` |",
     "| `ai extract DOCUMENT_ID` | `--model`、`--max-fragments`、`--temperature`、"
     "`--max-tokens`（默认 32768）、`--trigger`（默认 `manual`）、`--dry-run`、"
     "`--approve`（提取后立即批量确认）、`--note` | `app/cli.py:1223`，参数 `:1224-1235` |"),

    ("期间与精度：`infer_period(filename)` 给出 `(period_start, period_end, date_precision)`"
     "（`app/importers.py:348`），AI 提取在资料没写时间时用它兜底（`app/extract.py:245-247`）。",
     "期间与精度：`infer_period(filename, default_year=None)` 给出 "
     "`(period_start, period_end, date_precision)`（`app/importers.py:349`）；文件名没有四位年份时"
     "（飞书导出的「工作周报（10月10）」这类），用 `import --year 2026` 或 `periods --year 2026` 补全。"
     "AI 提取在资料没写时间时用它兜底（`app/extract.py:245-247`）。"),
])
