# -*- coding: utf-8 -*-
"""对全部原始资料逐篇做 AI 提取并自动确认入库（一次性数据作业）。

顺序执行而非并发：SQLite 单写者，且「先确认再提取下一篇」能让下一篇的
同名项目/系统自动转成「补来源」建议，避免跨篇重复建档。
用法：python tools/oneoff/_extract_all.py [--db data/growth.db] [--limit N] [--dry]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.extract import ExtractError, Extraction, Review  # noqa: E402
from app.store import Store  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/growth.db")
    parser.add_argument("--limit", type=int, help="只处理前 N 篇（按期间排序）")
    parser.add_argument("--max-tokens", type=int, default=32768, dest="max_tokens")
    parser.add_argument("--dry", action="store_true", help="只列出处理清单")
    parser.add_argument("--title", help="只处理标题包含该片段的资料")
    parser.add_argument("--only-missing", action="store_true", dest="only_missing",
                        help="跳过已有成功提取作业的资料")
    args = parser.parse_args()

    store = Store(args.db)
    try:
        docs = store.list("source_document", limit=500, order_by="period_start ASC")
        if args.only_missing:
            done = set()
            for job in store.list("ai_job", {"status": "succeeded"}, limit=2000):
                try:
                    done.add(json.loads(job.get("input_scope") or "{}").get("document_id"))
                except ValueError:
                    pass
            docs = [doc for doc in docs if doc["id"] not in done]
        if args.title:
            docs = [doc for doc in docs if args.title in doc["title"]]
        if args.limit:
            docs = docs[:args.limit]
        print("共 %d 篇资料待提取" % len(docs), flush=True)
        if args.dry:
            for doc in docs:
                print("  %s  %s ~ %s" % (doc["title"], doc["period_start"], doc["period_end"]))
            return 0
        extraction = Extraction(store)
        review = Review(store, extraction=extraction)
        totals = {"proposals": 0, "confirmed": 0, "modified": 0, "failed": 0}
        for index, doc in enumerate(docs, 1):
            started = time.time()
            print("[%d/%d] %s（%s ~ %s）..."
                  % (index, len(docs), doc["title"], doc["period_start"], doc["period_end"]),
                  flush=True)
            try:
                result = extraction.run(doc["id"], max_tokens=args.max_tokens)
            except ExtractError as exc:
                print("  ✗ 提取失败：%s" % exc, flush=True)
                totals["failed"] += 1
                continue
            outcome = review.confirm_batch(job_id=result["job_id"])
            totals["proposals"] += result["proposal_count"]
            totals["confirmed"] += outcome["confirmed"]
            totals["modified"] += outcome["modified"]
            totals["failed"] += len(outcome["failed"])
            print("  ✓ 建议 %d｜直接确认 %d｜补齐确认 %d｜未通过 %d｜%.1fs"
                  % (result["proposal_count"], outcome["confirmed"], outcome["modified"],
                     len(outcome["failed"]), time.time() - started), flush=True)
            for item in outcome["failed"][:5]:
                print("    ✗ %s：%s" % (item["entity"], item["reason"]), flush=True)
        print("完成：建议 %d，确认 %d，补齐 %d，失败 %d"
              % (totals["proposals"], totals["confirmed"], totals["modified"],
                 totals["failed"]), flush=True)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
