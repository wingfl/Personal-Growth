# -*- coding: utf-8 -*-
"""一次性补丁：给 app/cli.py 增加 `feishu` 子命令组（检查/知识库/扫描/拉取）。

同时给 app/feishu_import.py 的 FeishuSync 增加「缺凭据直接报错」的守卫。
每处替换断言恰好命中一次。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "app", "cli.py")
SYNC = os.path.join(ROOT, "app", "feishu_import.py")

HANDLERS = '''def _split_keywords(value):
    if not value:
        return None
    parts = [p.strip() for p in value.replace("，", ",").split(",")]
    return [p for p in parts if p] or None


def _feishu_nodes(sync, args):
    wiki = args.source in ("wiki", "both")
    drive = args.source in ("drive", "both")
    return sync.scan(wiki=wiki, drive=drive, drive_folder=args.folder,
                     drive_depth=args.depth, keywords=_split_keywords(args.match),
                     limit=args.limit)


def _feishu_check(args):
    store = Store(args.db)
    try:
        sync = FeishuSync(store, keywords=_split_keywords(args.match))
        report = sync.check()
        print("应用：%s（凭据来源：%s）" % (report["app_id"], report["key_source"] or "-"))
        print("接口：%s" % report["base_url"])
        print("应用令牌：%s" % ("正常" if report["token_ok"] else "失败"))
        print("可见知识库：%s" % ("%d 个" % report["spaces"]
                                 if report["spaces"] is not None else "不可读"))
        print("云盘根目录：%s" % ("可读" if report["drive_ok"] else "不可读"))
        if report["problems"]:
            print("还需要处理：")
            for item in report["problems"]:
                print("  · %s" % item)
            return
        print("权限齐备，可以扫描资料：python -m app.cli feishu scan")
    finally:
        store.close()


def _feishu_spaces(args):
    store = Store(args.db)
    try:
        sync = FeishuSync(store)
        spaces = sync.client.wiki_spaces()
        if not spaces:
            print("应用看不到任何知识库。请在知识库「设置 → 成员管理」里把本应用加为成员。")
            return
        for space in spaces:
            print("%s  %s" % (space.get("space_id"), space.get("name")))
    finally:
        store.close()


def _feishu_scan(args):
    store = Store(args.db)
    try:
        sync = FeishuSync(store, keywords=_split_keywords(args.match))
        nodes = _feishu_nodes(sync, args)
        if not nodes:
            print("没有匹配的资料（关键词：%s）。"
                  % "、".join(sync.keywords))
            print("提示：先跑 python -m app.cli feishu check 看权限，"
                  "python -m app.cli feishu spaces 看知识库。")
            return
        print("匹配到 %d 篇资料：" % len(nodes))
        for item in nodes:
            flag = "" if item["obj_type"] in ("docx", "doc", "sheet") else "  [%s]" % (
                item.get("note") or "内容不可读")
            print("  [%s/%s] %s%s" % (item["source"], item["obj_type"], item["title"], flag))
            if item.get("space"):
                print("        知识库：%s" % item["space"])
            if item.get("url"):
                print("        链接：%s" % item["url"])
            print("        token：%s｜最后修改：%s"
                  % (item["token"], item.get("updated_at") or "-"))
        print("\\n下一步：python -m app.cli feishu pull%s"
              % ("" if args.source == "wiki" else " --source %s" % args.source))
    finally:
        store.close()


def _feishu_pull(args):
    store = Store(args.db)
    try:
        sync = FeishuSync(store, keywords=_split_keywords(args.match))
        nodes = _feishu_nodes(sync, args)
        result = sync.pull(nodes, doc_type=args.type, duplicate_handling=args.handling,
                           batch_label=args.label, dry_run=args.dry_run)
        if args.dry_run:
            print("== 试运行：只读取正文，不写库 ==")
            for item in result["results"]:
                print("  %s｜%s｜%s 字" % (item["status"], item["title"], item.get("chars")))
            return
        print("批次：%s" % result["batch_id"])
        print("共 %d 篇：新增 %d｜重复跳过 %d｜失败 %d｜跳过 %d"
              % (result["total"], result["imported"], result["duplicate"],
                 result["failed"], result["skipped"]))
        for item in result["results"]:
            if item["status"] == "imported":
                print("  ✓ %s｜%s｜%d 个片段｜期间 %s ~ %s"
                      % (item["title"], item["document_id"], item["fragment_count"],
                         item.get("period_start") or "-", item.get("period_end") or "-"))
            elif item["status"] == "duplicate":
                print("  = 已存在，跳过：%s（%s）" % (item["title"], item["document_id"]))
            else:
                print("  ! %s：%s" % (item["title"], item.get("error") or item.get("note")))
        if result["imported"]:
            print("\\n下一步：python -m app.cli docs 查看资料，"
                  "python -m app.cli ai extract <资料ID> 让模型提取工作事项")
    finally:
        store.close()


'''

FEISHU_PARSER = '''    p = sub.add_parser("feishu", help="飞书资料同步（知识库 / 云盘里的周报月报）")
    fs = p.add_subparsers(dest="action", required=True)

    q = fs.add_parser("check", help="检查应用凭据、权限与可见范围")
    q.add_argument("--match", help="只看名称含这些关键词的资料（逗号分隔，默认 周报,月报）")
    q.set_defaults(func=_feishu_check)

    q = fs.add_parser("spaces", help="列出应用可见的知识库")
    q.set_defaults(func=_feishu_spaces)

    q = fs.add_parser("scan", help="扫描匹配的资料（不写库）")
    q.add_argument("--source", default="wiki", choices=["wiki", "drive", "both"],
                   help="从知识库还是云盘扫描（默认 wiki）")
    q.add_argument("--folder", help="云盘文件夹 token（默认根目录）")
    q.add_argument("--depth", type=int, default=3, help="云盘递归层数（默认 3）")
    q.add_argument("--match", help="名称关键词，逗号分隔（默认 周报,月报）")
    q.add_argument("--limit", type=int, default=500, help="最多扫描多少条")
    q.set_defaults(func=_feishu_scan)

    q = fs.add_parser("pull", help="把匹配的资料导入原始资料库")
    q.add_argument("--source", default="wiki", choices=["wiki", "drive", "both"])
    q.add_argument("--folder", help="云盘文件夹 token（默认根目录）")
    q.add_argument("--depth", type=int, default=3)
    q.add_argument("--match", help="名称关键词，逗号分隔（默认 周报,月报）")
    q.add_argument("--limit", type=int, default=500)
    q.add_argument("--type", help="强制资料类型（默认按标题推断）")
    q.add_argument("--handling", default="skip",
                   choices=["skip", "new_version", "import_anyway"],
                   help="同一篇文档再次拉取时的处理方式（默认 skip）")
    q.add_argument("--label", help="导入批次名称")
    q.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="只读正文，不写库")
    q.set_defaults(func=_feishu_pull)

    return parser'''


def patch(path, replacements, label):
    text = io.open(path, encoding="utf-8").read()
    for index, (old, new) in enumerate(replacements, 1):
        count = text.count(old)
        if count != 1:
            sys.stderr.write("%s 第 %d 处补丁命中 %d 次（应为 1），已中止\n"
                             % (label, index, count))
            return False
        text = text.replace(old, new, 1)
        print("✓ %s 第 %d 处补丁已应用" % (label, index))
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)
    return True


def main():
    ok = patch(CLI, [
        (
            "from .extract import ExtractError, Extraction, Review\n",
            "from .extract import ExtractError, Extraction, Review\n"
            "from .feishu import FeishuError, resolve_feishu_config\n"
            "from .feishu_import import FeishuSync, FeishuSyncError\n",
        ),
        (
            "def build_parser():",
            HANDLERS + "def build_parser():",
        ),
        (
            '''    q = ai.add_parser("reject", help="拒绝建议（不写入档案）")
    q.add_argument("proposal", help="建议 ID")
    q.add_argument("--note", help="拒绝原因")
    q.set_defaults(func=_ai_reject)
    return parser''',
            '''    q = ai.add_parser("reject", help="拒绝建议（不写入档案）")
    q.add_argument("proposal", help="建议 ID")
    q.add_argument("--note", help="拒绝原因")
    q.set_defaults(func=_ai_reject)

''' + FEISHU_PARSER,
        ),
        (
            "    except (ArchiveError, ExtractError, LLMError, ModelError, ValidationError, Conflict,\n",
            "    except (ArchiveError, ExtractError, LLMError, ModelError, ValidationError, Conflict,\n"
            "            FeishuError, FeishuSyncError,\n",
        ),
    ], "cli.py")
    if not ok:
        return 1

    ok = patch(SYNC, [
        (
            '''        self.keywords = tuple(keywords) if keywords else DEFAULT_KEYWORDS''',
            '''        self.keywords = tuple(keywords) if keywords else DEFAULT_KEYWORDS
        if not self.config.has_key:
            raise FeishuSyncError(
                "未找到飞书应用凭据。请设置 FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量，"
                "或写入 ~/.dsh/.credentials.yaml 的 refs 段，或放在 config/feishu.json。")''',
        ),
    ], "feishu_import.py")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
