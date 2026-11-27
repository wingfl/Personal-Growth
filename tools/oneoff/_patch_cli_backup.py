# -*- coding: utf-8 -*-
"""一次性补丁：给 CLI 接入 backup 命令组与统一日志。

不可重跑（断言式补丁，改完即失效）。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
TARGET = ROOT / "app" / "cli.py"

IMPORT_OLD = "from .archive import Archive, ArchiveError\n"
IMPORT_NEW = ("from .archive import Archive, ArchiveError\n"
              "from .backup import BackupError, create_backup, verify_backup_file\n")

HANDLER = '''def _backup(args):
    action = args.action
    if action == "create":
        with Store(args.db) as store:
            report = create_backup(store, out_dir=args.out,
                                   include_attachments=not args.no_attachments,
                                   label=args.label, note=args.note)
        print("✓ 已备份：%s" % report["path"])
        print("  记录数 %d｜大小 %.1f KB｜耗时 %d ms｜校验和 %s"
              % (report["record_count"], report["size_bytes"] / 1024.0,
                 report["duration_ms"], report["checksum"][:16]))
        attachments = report.get("attachments")
        if attachments:
            print("  附件 %d 个（%.1f KB）→ %s"
                  % (attachments["files"], attachments["bytes"] / 1024.0, attachments["path"]))
        elif args.no_attachments:
            print("  附件：已按 --no-attachments 跳过")
        else:
            print("  附件：无（数据库同目录没有 attachments/）")
        print("  自检：%s" % ("通过" if report["verification"]["ok"] else "未通过"))
        print("  备份记录 ID：%s" % report["backup_record_id"])
        return

    if action == "verify":
        report = verify_backup_file(args.path)
        print("备份文件：%s" % args.path)
        print("  大小 %.1f KB｜表 %d 张｜记录 %d 条"
              % (report["size_bytes"] / 1024.0, report["tables"], report["rows"]))
        if report["checksum"]:
            print("  校验和 %s" % report["checksum"])
        if report["ok"]:
            print("✓ 校验通过：完整性、表结构与模型一致")
        else:
            print("✗ 校验未通过：")
            for problem in report["problems"]:
                print("    - %s" % problem)
            raise BackupError("备份文件校验未通过")
        return

    with Store(args.db) as store:
        rows = store.query(
            "SELECT * FROM backup_record WHERE operation_type='backup' AND deleted_at IS NULL "
            "ORDER BY created_at DESC LIMIT ?", (args.limit,))
    if not rows:
        print("暂无备份记录")
        return
    print("最近 %d 次备份：" % len(rows))
    for row in rows:
        scope = row.get("scope")
        attachments = ""
        if isinstance(scope, dict) and scope.get("attachment_files") is not None:
            attachments = "｜附件 %s 个" % scope["attachment_files"]
        print("  %s｜%s｜%s 条｜%.1f KB｜%s%s"
              % (row["created_at"], row["status"], row["record_count"],
                 (row["size_bytes"] or 0) / 1024.0, row["file_path"] or "-", attachments))


'''

PARSER_ANCHOR = "    return parser\n"
PARSER_BLOCK = '''    bk = sub.add_parser("backup", help="备份数据库与附件、校验备份文件")
    bks = bk.add_subparsers(dest="action", required=True)

    q = bks.add_parser("create", help="做一次热备份（VACUUM INTO + 附件拷贝）并留档")
    q.add_argument("--out", help="输出目录（默认 项目根目录/backup）")
    q.add_argument("--no-attachments", action="store_true", dest="no_attachments",
                   help="不拷贝附件目录")
    q.add_argument("--label", help="文件名后缀标签（如 演练、迁移前）")
    q.add_argument("--note", help="备注，写进备份记录的 scope.note")
    q.set_defaults(func=_backup)

    q = bks.add_parser("verify", help="校验一个备份文件：完整性、表结构、可读性")
    q.add_argument("path")
    q.set_defaults(func=_backup)

    q = bks.add_parser("list", help="列出最近的备份记录")
    q.add_argument("--limit", type=int, default=20)
    q.set_defaults(func=_backup)

'''

MAIN_OLD = '''def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (ArchiveError, ExtractError, LLMError, ModelError, ValidationError, Conflict,
            FeishuError, FeishuSyncError, FeishuAuthError,
            ValueError, FileNotFoundError) as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2
    return 0
'''

MAIN_NEW = '''def main(argv=None):
    args = build_parser().parse_args(argv)
    setup_logging(log_dir=args.log_dir, level="DEBUG" if args.verbose else "INFO")
    log = get_logger("cli")
    log.info("命令：%s", " ".join(sys.argv[1:]) if argv is None else " ".join(argv))
    try:
        args.func(args)
    except (ArchiveError, BackupError, ExtractError, LLMError, ModelError, ValidationError,
            Conflict, FeishuError, FeishuSyncError, FeishuAuthError,
            ValueError, FileNotFoundError) as exc:
        log.warning("命令失败：%s: %s", type(exc).__name__, exc)
        print("错误：%s" % exc, file=sys.stderr)
        return 2
    except Exception as exc:  # 未预期异常也要留痕，便于事后诊断
        log.exception("未预期异常：%s", exc)
        raise
    log.info("命令完成：%s", args.command)
    return 0
'''

OPTIONS_OLD = ('    parser.add_argument("--db", default=DEFAULT_DB, help="数据库文件路径（默认 data/growth.db）")\n')
OPTIONS_NEW = ('    parser.add_argument("--db", default=DEFAULT_DB, help="数据库文件路径（默认 data/growth.db）")\n'
               '    parser.add_argument("--log-dir", dest="log_dir",\n'
               '                        help="日志目录（默认 data/logs）")\n'
               '    parser.add_argument("--verbose", action="store_true", help="日志输出到标准错误"\n'
               '                        "并把级别降到 DEBUG")\n')


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit("✗ %s：预期命中 1 次，实际 %d 次" % (label, count))
    return text.replace(old, new)


def main():
    text = TARGET.read_text(encoding="utf-8")
    text = replace_once(text, IMPORT_OLD, IMPORT_NEW, "import 段")
    text = replace_once(text, "from .llm import LLMClient, LLMError, dsh_home, resolve_config\n",
                        "from .llm import LLMClient, LLMError, dsh_home, resolve_config\n"
                        "from .logging import get_logger, setup_logging\n", "logging import")
    text = replace_once(text, OPTIONS_OLD, OPTIONS_NEW, "全局参数")
    if "def _backup(args):" in text:
        raise SystemExit("✗ _backup 已存在")
    text = replace_once(text, "def build_parser():\n", HANDLER + "def build_parser():\n", "_backup 插入")
    text = replace_once(text, PARSER_ANCHOR, PARSER_BLOCK + PARSER_ANCHOR, "backup 子命令")
    text = replace_once(text, MAIN_OLD, MAIN_NEW, "main 改写")
    TARGET.write_text(text, encoding="utf-8")
    print("✓ app/cli.py 已接入 backup 命令组与统一日志")
    return 0


if __name__ == "__main__":
    sys.exit(main())
