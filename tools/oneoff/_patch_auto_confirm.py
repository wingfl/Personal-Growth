# -*- coding: utf-8 -*-
"""一次性补丁：提取健壮性 + 批量确认 + 期间回填命令。

1) app/llm.py：默认输出预算 16384 → 32768（推理 token 也占预算）；
2) app/extract.py：finish_reason=length 时放大预算重试一次；
3) app/extract.py：Review.confirm_batch（自动补 work_item.occurred_at）；
4) app/cli.py：import --year、ai extract --approve/--note、新命令 periods。
用法：python tools/oneoff/_patch_auto_confirm.py
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def patch(name, replacements):
    path = os.path.join(ROOT, "app", name)
    src = io.open(path, encoding="utf-8").read()
    for old, new in replacements:
        assert src.count(old) == 1, (name, old[:60], src.count(old))
        src = src.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("patched", path)


RETRY_OLD = '''            reply = self.llm.chat(messages, temperature=temperature, max_tokens=max_tokens)
            data = parse_json_reply(reply.text)
'''
RETRY_NEW = '''            reply = self.llm.chat(messages, temperature=temperature, max_tokens=max_tokens)
            try:
                data = parse_json_reply(reply.text)
            except LLMError as exc:
                # 推理型模型会把输出预算耗在推理上：被 length 截断时把预算翻倍重试一次，
                # 仍失败才按 parse_failed 记作业失败（否则每篇周报都要手工加 --max-tokens）。
                if exc.code != "parse_failed" or reply.finish_reason != "length":
                    raise
                budget = min((max_tokens or self.llm.config.max_tokens) * 2, 65536)
                reply = self.llm.chat(messages, temperature=temperature, max_tokens=budget)
                data = parse_json_reply(reply.text)
'''

BATCH_METHODS = '''    def confirm_batch(self, job_id=None, batch_id=None, note=None, fill_missing=True,
                      limit=2000, actor_type="user"):
        """批量确认待审建议，供「提取后自动入库」使用。

        能补齐的缺项先补（work_item 缺 occurred_at 时取资料期间的起点与精度），
        补不齐的跳过并带回原因，不阻断其余建议；单条失败不影响整批。
        """
        rows = self.store.list("change_proposal", {"status": "pending"}, limit=limit,
                               order_by="created_at ASC")
        if job_id:
            rows = [row for row in rows if row.get("job_id") == job_id]
        if batch_id:
            rows = [row for row in rows if row.get("batch_id") == batch_id]
        confirmed, modified, failed = [], [], []
        for row in rows:
            overrides = self._auto_overrides(row) if fill_missing else {}
            try:
                result = self.confirm(row["id"], overrides=overrides or None,
                                      note=note or "自动确认（缺项按资料期间补齐）",
                                      actor_type=actor_type)
            except ExtractError as exc:
                failed.append({"proposal_id": row["id"],
                               "entity": row.get("target_entity_type"),
                               "change_type": row.get("change_type"),
                               "reason": str(exc)})
                continue
            if result["status"] == "modified":
                modified.append(row["id"])
            else:
                confirmed.append(row["id"])
        return {"total": len(rows), "confirmed": len(confirmed), "modified": len(modified),
                "failed": failed, "confirmed_ids": confirmed, "modified_ids": modified}

    def _auto_overrides(self, proposal):
        """自动补齐建议里缺的必填项：目前只有 work_item 的事发时间。"""
        if proposal.get("change_type") != "create":
            return {}
        if proposal.get("target_entity_type") != "work_item":
            return {}
        payload = self._payload(proposal)
        if payload.get("occurred_at"):
            return {}
        period = self._job_period(proposal.get("job_id"))
        if not period.get("start"):
            return {}
        overrides = {"occurred_at": period["start"]}
        if payload.get("date_precision") in (None, "", "unknown"):
            overrides["date_precision"] = period["precision"]
        return overrides

    def _job_period(self, job_id):
        """顺着作业的 input_scope 找到资料，取它记录的期间与精度。"""
        if not job_id:
            return {}
        try:
            job = self.store.get("ai_job", job_id)
        except NotFound:
            return {}
        try:
            scope = json.loads(job.get("input_scope") or "{}")
        except ValueError:
            return {}
        document_id = scope.get("document_id")
        if not document_id:
            return {}
        try:
            doc = self.store.get("source_document", document_id)
        except NotFound:
            return {}
        start, end = doc.get("period_start"), doc.get("period_end")
        return {"start": start, "end": end,
                "precision": precision_from_period(start, end)}

    def reject(self, proposal_id, note=None, actor_type="user"):
'''

PERIODS_FUNC = '''def _periods(args):
    store = Store(args.db)
    try:
        rows = store.list("source_document", limit=10000, order_by="created_at ASC")
        filled, skipped = [], []
        for row in rows:
            if row.get("period_start") and row.get("period_end"):
                continue
            start, end, precision = infer_period(row["title"], args.year)
            if not start:
                skipped.append(row["title"])
                continue
            filled.append((row["title"], start, end, precision))
            if not args.dry_run:
                store.update("source_document", row["id"],
                             {"period_start": start, "period_end": end})
        if not args.dry_run:
            store.commit()
        for title, start, end, precision in filled:
            print("✓ %s → %s ~ %s（%s）" % (title, start, end, precision))
        print("补全 %d 篇，未识别 %d 篇%s"
              % (len(filled), len(skipped), "（预览模式，未写库）" if args.dry_run else ""))
        for title in skipped:
            print("  · 未识别：%s" % title)
    finally:
        store.close()


def _docs(args):
'''


def main():
    patch("llm.py", [(
        "DEFAULT_MAX_TOKENS = 16384",
        "# 推理型模型的输出预算包含推理 token：16384 时常出现回复被截断（finish_reason=length），\n"
        "# 默认抬到 32768；单个作业还可以在调用处覆盖。\n"
        "DEFAULT_MAX_TOKENS = 32768",
    )])
    patch("extract.py", [
        (RETRY_OLD, RETRY_NEW),
        ('    def reject(self, proposal_id, note=None, actor_type="user"):\n', BATCH_METHODS),
    ])
    patch("cli.py", [
        ("from .importers import import_path\n",
         "from .importers import import_path, infer_period\n"),
        ("""                doc_type=args.type, source_channel=args.channel,
                duplicate_handling=args.handling,
            )""",
         """                doc_type=args.type, source_channel=args.channel,
                duplicate_handling=args.handling, default_year=args.year,
            )"""),
        ('    p.add_argument("--recursive", action="store_true", help="目录递归导入")\n'
         '    p.add_argument("--label", help="导入批次名称")\n',
         '    p.add_argument("--recursive", action="store_true", help="目录递归导入")\n'
         '    p.add_argument("--label", help="导入批次名称")\n'
         '    p.add_argument("--year", type=int,\n'
         '                   help="文件名没写年份时用它推断期间（如 2026）")\n'),
        ('    q.add_argument("--dry-run", action="store_true", dest="dry_run",\n'
         '                   help="只打印将要发送的提示词，不调用模型、不写库")\n'
         '    q.set_defaults(func=_ai_extract)\n',
         '    q.add_argument("--dry-run", action="store_true", dest="dry_run",\n'
         '                   help="只打印将要发送的提示词，不调用模型、不写库")\n'
         '    q.add_argument("--approve", action="store_true",\n'
         '                   help="提取成功后立即批量确认本作业的建议")\n'
         '    q.add_argument("--note", help="批量确认时写入的审核备注")\n'
         '    q.set_defaults(func=_ai_extract)\n'),
        ("""        print("\\n下一步：python -m app.cli ai proposals 查看，"
              "python -m app.cli ai show <建议ID> 看证据，"
              "python -m app.cli ai confirm <建议ID> 写入档案")
""",
         """        if not args.approve:
            print("\\n下一步：python -m app.cli ai proposals 查看，"
                  "python -m app.cli ai show <建议ID> 看证据，"
                  "python -m app.cli ai confirm <建议ID> 写入档案")
            return
        outcome = Review(store).confirm_batch(job_id=result["job_id"], note=args.note)
        print("\\n== 自动确认 ==")
        print("  待处理 %d 条：直接确认 %d，补齐后确认 %d，未通过 %d"
              % (outcome["total"], outcome["confirmed"], outcome["modified"],
                 len(outcome["failed"])))
        for item in outcome["failed"][:20]:
            print("  ✗ %s（%s）：%s" % (item["proposal_id"], item["entity"], item["reason"]))
"""),
        ("def _docs(args):\n", PERIODS_FUNC),
        ('    p = sub.add_parser("docs", help="列出已导入的原始资料")\n',
         '    p = sub.add_parser("periods", help="按年份补全已导入资料的期间（文件名没写年份时用）")\n'
         '    p.add_argument("--year", type=int, required=True, help="用于推断的年份，如 2026")\n'
         '    p.add_argument("--dry-run", action="store_true", dest="dry_run",\n'
         '                   help="只预览补全结果，不写库")\n'
         '    p.set_defaults(func=_periods)\n'
         '\n'
         '    p = sub.add_parser("docs", help="列出已导入的原始资料")\n'),
    ])


if __name__ == "__main__":
    main()
