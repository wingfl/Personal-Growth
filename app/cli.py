# -*- coding: utf-8 -*-
"""命令行入口：建库、导入原始资料、查看与追溯。

用法示例：
    python -m app.cli init
    python -m app.cli import 资料/2024-03周报.md --type weekly_report
    python -m app.cli import 资料/ --recursive
    python -m app.cli docs
    python -m app.cli fragments <文档ID>
    python -m app.cli verify <文档ID>
    python -m app.cli audit --entity source_document
    python -m app.cli stats
"""
import argparse
import json
import os
import sys
import urllib.parse

from .archive import Archive, ArchiveError
from .backup import BackupError, create_backup, verify_backup_file
from .extract import ExtractError, Extraction, Review
from .feishu import FeishuError, resolve_feishu_config
from .feishu_auth import (DEFAULT_PORT, DEFAULT_REDIRECT_URI, DEFAULT_SCOPES,
                          CodeReceiver, FeishuAuthError, UserAuth, authorize_url,
                          clear_user_tokens, exchange_code, store_tokens, user_info)
from .feishu_import import FeishuSync, FeishuSyncError
from .importers import import_path, infer_period
from .llm import LLMClient, LLMError, dsh_home, resolve_config
from .logging import get_logger, setup_logging
from .model_meta import Model, ModelError, ValidationError
from .store import DEFAULT_DB, Conflict, Store


def _init(args):
    path = Store.init(args.db)
    print("已建库：%s" % path)
    store = Store(path)
    try:
        print("实体表 %d 张，枚举 %d 组" % (len(store.model.entities), len(store.model.enums)))
    finally:
        store.close()


def _import(args):
    store = Store(args.db)
    try:
        for target in args.paths:
            result = import_path(
                store, target, recursive=args.recursive, batch_label=args.label,
                doc_type=args.type, source_channel=args.channel,
                duplicate_handling=args.handling, default_year=args.year,
            )
            if result["status"] == "imported":
                print("✓ 导入 %s" % result["title"])
                print("  文档ID %s｜类型 %s｜版本 %s｜片段 %d｜字数 %d｜期间 %s~%s"
                      % (result["document_id"], result["doc_type"], result["version_no"],
                         result["fragment_count"], result["word_count"],
                         result["period_start"] or "未识别", result["period_end"] or "未识别"))
            elif result["status"] == "duplicate":
                print("= 已存在相同内容，跳过：%s（文档ID %s，版本 %s，片段 %d）"
                      % (result["title"], result["document_id"], result["version_no"],
                         result["fragment_count"]))
            else:
                print("批次 %s：共 %d 个文件，导入 %d，重复 %d，失败 %d"
                      % (result["batch_id"], result["file_count"], result["imported"],
                         result["duplicate"], result["failed"]))
                for item in result["results"]:
                    if item["status"] == "failed":
                        print("  ✗ %s：%s" % (os.path.basename(item["path"]), item["error"]))
                    elif item["status"] == "duplicate":
                        print("  = %s（重复，跳过）" % item["title"])
                    else:
                        print("  ✓ %s（%d 片段）" % (item["title"], item["fragment_count"]))
        store.commit()
    finally:
        store.close()


def _periods(args):
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
    store = Store(args.db)
    try:
        where = {"doc_type": args.type} if args.type else None
        rows = store.list("source_document", where=where, limit=args.limit,
                          order_by="COALESCE(period_start, '') DESC, id DESC")
        if not rows:
            print("还没有导入任何资料。先执行：python -m app.cli import <文件或目录>")
            return
        print("%-38s %-12s %-16s %6s %8s  %s" % ("文档ID", "类型", "期间", "片段", "字数", "标题"))
        for row in rows:
            fragments = store.count("source_fragment", {"document_id": row["id"]})
            period = (row["period_start"] or "")[:7] or "—"
            print("%-38s %-12s %-16s %6d %8d  %s"
                  % (row["id"], row["doc_type"], period, fragments,
                     row["word_count"] or 0, row["title"]))
    finally:
        store.close()


def _show(args):
    store = Store(args.db)
    try:
        doc = store.get("source_document", args.document_id)
        for key, value in doc.items():
            if key == "raw_text":
                value = "（%d 字符，已在库中固化）" % len(value or "")
            print("%-18s %s" % (key, value))
        print("%-18s %d" % ("片段数", store.count("source_fragment", {"document_id": doc["id"]})))
    finally:
        store.close()


def _fragments(args):
    store = Store(args.db)
    try:
        rows = store.list("source_fragment", {"document_id": args.document_id},
                          limit=args.limit, offset=args.offset, order_by="order_index ASC")
        for row in rows:
            head = row["heading_path"] or ""
            print("[%d] %s %s(%d-%d)" % (row["order_index"], row["fragment_type"],
                                         head + " " if head else "",
                                         row["char_start"], row["char_end"]))
            print("    " + (row["text"][:120] + ("…" if len(row["text"]) > 120 else "")))
    finally:
        store.close()


def _verify(args):
    """校验片段字符区间能否在正文中原样取回，以及是否被改动过。"""
    store = Store(args.db)
    try:
        doc = store.get("source_document", args.document_id)
        raw = doc["raw_text"] or ""
        rows = store.list("source_fragment", {"document_id": doc["id"]},
                          limit=100000, order_by="order_index ASC")
        bad = []
        for row in rows:
            if raw[row["char_start"]:row["char_end"]] != row["text"]:
                bad.append(row["order_index"])
        print("文档：%s" % doc["title"])
        print("片段 %d 个，字符区间校验 %s" % (len(rows), "全部一致" if not bad else "异常：%s" % bad))
        print("正文哈希 %s（%d 字符，写入后不可修改）" % (doc["content_hash"] or "", len(raw)))
    finally:
        store.close()


def _audit(args):
    store = Store(args.db)
    try:
        clauses, params = [], []
        if args.entity:
            clauses.append("entity_type = ?")
            params.append(args.entity)
        if args.id:
            clauses.append("entity_id = ?")
            params.append(args.id)
        sql = "SELECT * FROM audit_log"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        # 同一秒内按写入顺序倒序（UUIDv7 的同毫秒部分随机，不能用 id 排序）
        sql += " ORDER BY occurred_at DESC, rowid DESC LIMIT ?"
        params.append(args.limit)
        rows = store.query(sql, params)
        if not rows:
            print("暂无变更记录。")
            return
        for row in rows:
            print("%s  %-9s %-20s %s  %s"
                  % (row["occurred_at"], row["action"], row["entity_type"],
                     row["entity_id"], row["remark"] or ""))
    finally:
        store.close()


def _stats(args):
    store = Store(args.db)
    try:
        stats = store.stats()
        total = 0
        for layer_entity in sorted(stats):
            if stats[layer_entity]:
                print("%-24s %d" % (layer_entity, stats[layer_entity]))
                total += stats[layer_entity]
        print("%-24s %d" % ("合计记录", total))
    finally:
        store.close()


def _trace(args):
    """查看某个实体的来源追溯与关联（第 2 步先支持原始资料方向）。"""
    store = Store(args.db)
    try:
        rows = store.query(
            "SELECT * FROM provenance_link WHERE entity_type = ? AND entity_id = ? "
            "ORDER BY id DESC", (args.entity, args.entity_id))
        if not rows:
            print("暂无来源追溯记录（AI 建议确认或手工关联来源片段后会写入）。")
        for row in rows:
            frag = store.find_one("source_fragment", id=row["fragment_id"])
            quote = (frag or {}).get("text", "")[:80]
            print("%s → 片段 %s：%s" % (row["relation_type"], row["fragment_id"], quote))
        links = store.query(
            "SELECT * FROM entity_relation WHERE (from_type = ? AND from_id = ?) "
            "OR (to_type = ? AND to_id = ?)", (args.entity, args.entity_id,
                                               args.entity, args.entity_id))
        for link in links:
            print("关联 %s：%s/%s" % (link["relation_type"], link["to_type"] or link["from_type"],
                                     link["to_id"] or link["from_id"]))
    finally:
        store.close()


# ---- 第 3 步：项目 / 系统 / 模块 / 事项 / 主题 / 职责 -----------------

def _enum_choices(name, fallback=None):
    try:
        return Model.load().enum_values(name)
    except Exception:
        return fallback


def _fact_patch(args):
    patch = {}
    if getattr(args, "fact", None) is not None:
        patch["is_fact"] = 1 if args.fact == "true" else 0
    if getattr(args, "basis", None):
        patch["fact_basis"] = args.basis
    return patch


def _alias_json(args):
    """--alias 可重复，落库为 json 数组（模型里 alias_names 是 json 字段）。"""
    aliases = [a for a in (getattr(args, "alias", None) or []) if a]
    return json.dumps(aliases, ensure_ascii=False) if aliases else None


def _print_rows(rows, columns, empty="（没有记录）"):
    if not rows:
        print(empty)
        return
    for row in rows:
        parts = []
        for label, key in columns:
            value = row.get(key)
            parts.append("%s=%s" % (label, "-" if value in (None, "") else value))
        print("  " + "｜".join(parts))


def _project(args):
    store = Store(args.db)
    arc = Archive(store)
    try:
        if args.action == "add":
            fields = {
                "project_type": args.type, "my_role": args.role, "status": args.status,
                "start_date": args.start, "end_date": args.end,
                "background": args.background, "goal": args.goal,
                "responsibility_scope": args.scope, "contribution_summary": args.contribution,
                "outcome_summary": args.outcome, "importance_level": args.importance,
                "alias_names": _alias_json(args), "domain_id": arc.ensure_domain(args.domain),
                "is_representative": 1 if args.representative else None,
            }
            fields.update(_fact_patch(args))
            row = arc.create_project(args.name, fragments=args.fragments, **fields)
            print("✓ 已建项目档案：%s" % row["name"])
            print("  项目ID %s｜类型 %s｜角色 %s｜期间 %s~%s｜来源片段 %d｜状态 %s"
                  % (row["id"], row["project_type"] or "未填", row["my_role"] or "未填",
                     row["start_date"] or "未填", row["end_date"] or "至今",
                     len(args.fragments), store.model.enum_label("review_status", row["review_status"])))
        elif args.action == "list":
            rows = store.list("project", limit=args.limit,
                              order_by="is_representative DESC, COALESCE(start_date,'') DESC")
            _print_rows(rows, [("项目ID", "id"), ("名称", "name"), ("类型", "project_type"),
                               ("角色", "my_role"), ("期间", "start_date"),
                               ("代表", "is_representative"), ("状态", "review_status")])
        elif args.action == "show":
            row = arc._require("project", args.id)
            for key in ("name", "project_type", "status", "my_role", "start_date", "end_date",
                        "background", "goal", "responsibility_scope", "contribution_summary",
                        "outcome_summary", "importance_level", "is_representative",
                        "origin", "review_status", "is_fact", "fact_basis"):
                if row.get(key) not in (None, ""):
                    print("%-22s %s" % (key, row[key]))
            prov = arc.provenance("project", row["id"])
            print("来源片段 %d 条" % len(prov))
            for p in prov:
                print("  ←《%s》%s：%s" % (p["document_title"], p["heading_path"] or "",
                                          p["text"][:60].replace("\n", " ")))
        elif args.action == "merge":
            report = arc.merge_records("project", args.keep, args.drop, note=args.note)
            print("✓ 已归并 %d 条重复项目到 %s" % (len(report["merged"]), args.keep))
            for line in report["repointed"]:
                print("  转移引用 %s" % line)
            for line in report["dropped_links"]:
                print("  丢弃重复关联 %s" % line)
    finally:
        store.close()


def _system(args):
    store = Store(args.db)
    arc = Archive(store)
    try:
        if args.action == "add":
            fields = {
                "system_type": args.type, "status": args.status, "my_role": args.role,
                "start_date": args.start, "end_date": args.end, "system_code": args.code,
                "description": args.description, "responsibility_scope": args.scope,
                "domain_id": arc.ensure_domain(args.domain),
                "alias_names": _alias_json(args),
                "is_representative": 1 if args.representative else None,
            }
            fields.update(_fact_patch(args))
            row = arc.create_system(args.name, fragments=args.fragments, **fields)
            print("✓ 已建系统档案：%s" % row["name"])
            print("  系统ID %s｜类型 %s｜状态 %s｜期间 %s~%s"
                  % (row["id"], row["system_type"], row["status"] or "未填",
                     row["start_date"] or "未填", row["end_date"] or "至今"))
        elif args.action == "list":
            rows = store.list("business_system", limit=args.limit, order_by="name ASC")
            _print_rows(rows, [("系统ID", "id"), ("名称", "name"), ("类型", "system_type"),
                               ("状态", "status"), ("角色", "my_role"), ("代码", "system_code")])
        elif args.action == "merge":
            report = arc.merge_records("business_system", args.keep, args.drop, note=args.note)
            print("✓ 已归并 %d 条重复系统到 %s" % (len(report["merged"]), args.keep))
            for line in report["repointed"]:
                print("  转移引用 %s" % line)
    finally:
        store.close()


def _module(args):
    store = Store(args.db)
    arc = Archive(store)
    try:
        if args.action == "add":
            system_id = arc.resolve("business_system", args.system)
            parent_id = arc.resolve("function_module", args.parent) if args.parent else None
            fields = {"module_type": args.type, "my_role": args.role, "module_code": args.code,
                      "description": args.description, "start_date": args.start,
                      "alias_names": _alias_json(args)}
            fields.update(_fact_patch(args))
            row = arc.create_module(args.name, system_id, parent_id,
                                    fragments=args.fragments, **fields)
            print("✓ 已建功能模块：%s（所属系统 %s）" % (row["name"], args.system))
            print("  模块ID %s｜类型 %s｜上级模块 %s"
                  % (row["id"], row["module_type"], args.parent or "无"))
        elif args.action == "list":
            rows = [dict(r) for r in store.list("function_module", limit=args.limit,
                                                order_by="name ASC")]
            for row in rows:
                row["system_name"] = arc._label("business_system", row["system_id"])
                row["parent_name"] = arc._label("function_module", row.get("parent_module_id"))
            _print_rows(rows, [("模块ID", "id"), ("名称", "name"), ("系统", "system_name"),
                               ("上级", "parent_name"), ("类型", "module_type"), ("代码", "module_code")])
        elif args.action == "tree":
            system_id = arc.resolve("business_system", args.system)
            def walk(nodes, depth):
                for node in nodes:
                    print("  " * depth + "- %s（%s）" % (node["name"], node["module_type"]))
                    walk(node["children"], depth + 1)
            walk(arc.module_tree(system_id), 0)
    finally:
        store.close()


def _item(args):
    store = Store(args.db)
    arc = Archive(store)
    try:
        if args.action == "add":
            content = args.content
            if not content and args.fragments:
                content = store.get("source_fragment", args.fragments[0])["text"]
            if not content:
                raise ArchiveError(
                    "请用 --content 说明这项做了什么，或用 --from 关联来源片段自动取原文")
            fields = {
                "my_role": args.role, "complexity_level": args.complexity,
                "is_routine": 1 if args.routine else None,
                "problem_background": args.background, "process": args.process,
                "result": args.result, "effort_hours": args.hours,
                "complexity_basis": args.complexity_basis,
                "project_id": arc.resolve("project", args.project),
                "system_id": arc.resolve("business_system", args.system),
                "module_id": arc.resolve("function_module", args.module),
                "domain_id": arc.ensure_domain(args.domain),
            }
            fields.update(_fact_patch(args))
            row = arc.create_work_item(args.title, args.type, content,
                                       occurred_at=args.date, date_precision=args.precision,
                                       fragments=args.fragments, **fields)
            print("✓ 已记录工作事项：%s" % row["title"])
            print("  事项ID %s｜类型 %s｜时间 %s（精度 %s）｜角色 %s｜来源片段 %d"
                  % (row["id"], row["item_type"], row["occurred_at"], row["date_precision"],
                     row["my_role"] or "未填", len(args.fragments)))
        elif args.action == "list":
            for row in arc.timeline(limit=args.limit, project_id=arc.resolve("project", args.project)
                                    if args.project else None):
                print("  %s｜%s｜%s｜项目=%s｜角色=%s%s"
                      % (row["occurred_at"], row["title"], row["item_type"],
                         row["project"] or "-", row["my_role"] or "-",
                         "｜例行" if row["is_routine"] else ""))
        elif args.action == "show":
            row = arc._require("work_item", args.id)
            for key in ("title", "item_type", "occurred_at", "date_precision", "my_role",
                        "is_routine", "complexity_level", "content", "problem_background",
                        "process", "result", "effort_hours", "complexity_basis",
                        "origin", "review_status", "is_fact", "fact_basis"):
                if row.get(key) not in (None, ""):
                    print("%-20s %s" % (key, row[key]))
            print("%-20s %s" % ("项目", arc._label("project", row["project_id"])))
            print("%-20s %s" % ("系统", arc._label("business_system", row["system_id"])))
            print("%-20s %s" % ("模块", arc._label("function_module", row["module_id"])))
            prov = arc.provenance("work_item", row["id"])
            print("来源片段 %d 条" % len(prov))
            for p in prov:
                print("  ←《%s》%s：%s" % (p["document_title"], p["heading_path"] or "",
                                          p["text"][:60].replace("\n", " ")))
    finally:
        store.close()


def _theme(args):
    store = Store(args.db)
    arc = Archive(store)
    theme_id = args.theme_id or args.name  # show/member 时主题ID写在第 2 个位置参数上
    try:
        if args.action == "add":
            fields = {"theme_type": args.type, "description": args.description,
                      "status": args.status,
                      "project_id": arc.resolve("project", args.project),
                      "domain_id": arc.ensure_domain(args.domain)}
            fields.update(_fact_patch(args))
            row = arc.create_theme(args.name, fragments=args.fragments, **fields)
            print("✓ 已建持续工作主题：%s" % row["name"])
            print("  主题ID %s｜类型 %s｜状态 %s" % (row["id"], row["theme_type"], row["status"]))
        elif args.action == "list":
            rows = store.list("work_theme", limit=args.limit, order_by="name ASC")
            _print_rows(rows, [("主题ID", "id"), ("名称", "name"), ("类型", "theme_type"),
                               ("首次", "first_seen_at"), ("最近", "last_seen_at"),
                               ("状态", "status")])
        elif args.action == "member":
            added = 0
            for item_id in args.item or []:
                arc.add_theme_member(theme_id, "work_item", arc.resolve("work_item", item_id))
                added += 1
            for case_id in args.case or []:
                arc.add_theme_member(theme_id, "achievement_case", case_id)
                added += 1
            for doc_id in args.doc or []:
                arc.add_theme_member(theme_id, "source_document",
                                     arc.resolve("source_document", doc_id))
                added += 1
            print("✓ 已加入 %d 个主题成员" % added)
        elif args.action == "show":
            data = arc.theme_timeline(theme_id)
            theme = data["theme"]
            print("%s（%s）｜首次 %s｜最近 %s"
                  % (theme["name"], theme["theme_type"], theme["first_seen_at"] or "-",
                     theme["last_seen_at"] or "-"))
            if data["items"]:
                print("工作事项时间线：")
                for item in data["items"]:
                    print("  %s｜%s｜%s" % (item["occurred_at"], item["title"], item["item_type"]))
            for case in data["cases"]:
                print("  成果案例：%s" % case.get("title"))
            for doc in data["documents"]:
                print("  原始资料：%s（%s）" % (doc["title"], doc["doc_type"]))
        elif args.action == "merge":
            report = arc.merge_records("work_theme", args.keep, args.drop, note=args.note)
            print("✓ 已归并 %d 条重复主题到 %s" % (len(report["merged"]), args.keep))
            for line in report["dropped_links"]:
                print("  丢弃重复关联 %s" % line)
    finally:
        store.close()


def _role(args):
    store = Store(args.db)
    arc = Archive(store)
    try:
        if args.action == "add":
            target_type = {"project": "project", "system": "business_system",
                           "module": "function_module"}[args.target]
            target_id = arc.resolve(target_type, args.target_id)
            fields = {"responsibility_scope": args.scope, "end_date": args.end,
                      "contribution_description": args.contribution,
                      "role_change_reason": args.reason,
                      "is_ongoing": 1 if args.ongoing else None,
                      "is_primary_role": 1 if args.primary else None}
            row = arc.create_role_record(target_type, target_id, args.role,
                                         args.start, **fields)
            print("✓ 已记录职责：%s 担任 %s" % (row["target_label"], row["role"]))
            print("  记录ID %s｜期间 %s~%s" % (row["id"], row["start_date"], row["end_date"] or "至今"))
        elif args.action == "list":
            rows = store.list("role_record", limit=args.limit, order_by="start_date DESC")
            _print_rows(rows, [("记录ID", "id"), ("对象", "target_label"), ("角色", "role"),
                               ("开始", "start_date"), ("结束", "end_date"),
                               ("主职", "is_primary_role")])
    finally:
        store.close()



def _goal(args):
    store = Store(args.db)
    arc = Archive(store)
    try:
        if args.action == "add":
            values = {
                "name": args.name,
                "goal_type": args.type or "capability",
                "status": args.status or "active",
                "start_date": args.start,
                "end_date": args.end,
                "date_precision": args.precision or "month",
                "progress_percent": args.progress if args.progress is not None else 0,
                "success_criteria": args.criteria,
                "measurement_note": args.measure,
                "progress_note": args.note,
                "description": args.description,
                "related_project_id": arc.resolve("project", args.project) if args.project else None,
                "related_domain_id": arc.resolve("work_domain", args.domain) if args.domain else None,
            }
            values = {k: v for k, v in values.items() if v is not None}
            values.setdefault("origin", "user")
            row_id = store.insert("growth_goal", values, actor_type="user")
            row = store.get("growth_goal", row_id)
            print("✓ 已建立成长目标：%s（%s）" % (row["name"], row["goal_type"]))
            print("  目标ID %s｜%s~%s｜进度 %s%%" % (row["id"], row["start_date"],
                                                    row["end_date"] or "长期", row["progress_percent"]))
        elif args.action == "list":
            rows = store.list("growth_goal", limit=args.limit,
                              order_by="status ASC, end_date ASC")
            _print_rows(rows, [("目标ID", "id"), ("目标", "name"), ("类型", "goal_type"),
                               ("状态", "status"), ("进度", "progress_percent"),
                               ("开始", "start_date"), ("目标日期", "end_date")])
            active = [r for r in rows if r["status"] in ("proposed", "active")]
            if active:
                avg = sum(int(r["progress_percent"] or 0) for r in active) // len(active)
                print("\n进行中 %d 个，平均进度 %d%%" % (len(active), avg))
        elif args.action == "show":
            row = store.get("growth_goal", arc.resolve("growth_goal", args.goal_id))
            for key in ("id", "name", "goal_type", "status", "progress_percent", "start_date",
                        "end_date", "success_criteria", "measurement_note", "progress_note"):
                if row.get(key) not in (None, ""):
                    print("%-16s %s" % (key, row[key]))
        elif args.action == "update":
            goal_id = arc.resolve("growth_goal", args.goal_id)
            row = store.get("growth_goal", goal_id)
            patch = {}
            if args.progress is not None:
                patch["progress_percent"] = args.progress
            if args.status:
                patch["status"] = args.status
            if args.note:
                patch["progress_note"] = args.note
            if args.criteria:
                patch["success_criteria"] = args.criteria
            if args.end:
                patch["end_date"] = args.end
            if patch.get("status") == "achieved":
                patch["progress_percent"] = 100
            if patch.get("status") == "abandoned" and not (args.note or row.get("progress_note")):
                raise SystemExit("放弃目标需要写 --note 说明原因")
            if not patch:
                raise SystemExit("没有要更新的字段（用 --progress / --status / --note）")
            store.update("growth_goal", goal_id, patch, expected_revision=row.get("revision"),
                         actor_type="user")
            print("✓ 已更新目标 %s：%s" % (args.goal_id, ", ".join(sorted(patch))))
        store.commit()
    finally:
        store.close()


def _profile(args):
    store = Store(args.db)
    try:
        rows = store.list("user_profile", limit=1)
        row = rows[0] if rows else None
        if args.action == "show" or not args.set:
            if not row:
                print("还没有本人档案。用 profile set --name 你的称呼 --title 产品经理 建立一条。")
                return
            for key in ("display_name", "current_title", "current_company", "industry",
                        "work_start_date", "target_position", "location_city", "summary"):
                if row.get(key) not in (None, ""):
                    print("%-16s %s" % (key, row[key]))
            return
        patch = {}
        mapping = {"name": "display_name", "title": "current_title", "company": "current_company",
                   "industry": "industry", "summary": "summary", "target": "target_position",
                   "city": "location_city", "start": "work_start_date"}
        for attr, field in mapping.items():
            value = getattr(args, attr)
            if value is not None:
                patch[field] = value
        if not patch:
            raise SystemExit("没有要写入的字段")
        if row:
            store.update("user_profile", row["id"], patch, expected_revision=row.get("revision"),
                         actor_type="user", remark="更新本人档案")
            print("✓ 已更新本人档案：%s" % ", ".join(sorted(patch)))
        else:
            patch.setdefault("display_name", "我")
            patch.setdefault("origin", "user")
            rid = store.insert("user_profile", patch, actor_type="user")
            print("✓ 已建立本人档案 %s" % rid)
        store.commit()
    finally:
        store.close()


def _link(args):
    store = Store(args.db)
    arc = Archive(store)
    try:
        links = arc.link_fragments(args.entity, args.id, args.fragments,
                                   relation_type=args.relation)
        print("✓ 已登记 %d 条来源追溯" % len(links))
        for link in links:
            frag = store.get("source_fragment", link["fragment_id"])
            doc = store.get("source_document", frag["document_id"])
            print("  ←《%s》%s：%s" % (doc["title"], frag["heading_path"] or "",
                                      frag["text"][:60].replace("\n", " ")))
    finally:
        store.close()


def _overview(args):
    store = Store(args.db)
    arc = Archive(store)
    try:
        data = arc.overview()
        print("== 档案总览 ==")
        labels = {"project": "项目", "business_system": "系统", "function_module": "功能模块",
                  "work_item": "工作事项", "work_theme": "持续主题", "role_record": "职责记录",
                  "source_document": "原始资料", "source_fragment": "来源片段"}
        print("  " + "｜".join("%s %d" % (labels[k], v) for k, v in data["counts"].items()))
        span = data["item_span"]
        print("  事项时间范围：%s ~ %s" % (span["first"] or "暂无", span["last"] or "暂无"))
        if data["representative_projects"]:
            print("代表项目：")
            for p in data["representative_projects"]:
                print("  %s（%s，%s）" % (p["name"], p["project_type"] or "类型未填",
                                          p["my_role"] or "角色未填"))
        if data["recent_items"]:
            print("近期事项：")
            for item in data["recent_items"]:
                print("  %s｜%s｜%s" % (item["occurred_at"], item["title"],
                                        item["project"] or "未关联项目"))
        if data["domains"]:
            print("领域分布：")
            for d in data["domains"]:
                print("  %s：%d 项" % (d["domain"] or "未分领域", d["items"]))
        if data["pending_reviews"]:
            print("待审核的 AI 建议：%d 条" % data["pending_reviews"])
    finally:
        store.close()


def _ai_seed(args):
    store = Store(args.db)
    try:
        result = Extraction(store).seed_config()
        for item in result["prompt_templates"]:
            print("%s 提示词模板「%s」v%s（%s）"
                  % ("✓ 更新" if item["action"] == "updated" else "✓ 新建",
                     item["name"], item["version"], item["file"]))
        for item in result["workflows"]:
            print("%s 工作流「%s」" % ("✓ 更新" if item["action"] == "updated" else "✓ 新建",
                                      item["name"]))
        if not result["prompt_templates"]:
            print("prompts/ 目录下没有 .json 提示词文件")
    finally:
        store.close()


def _ai_check(args):
    cfg = resolve_config(model=args.model)
    print("网关：%s" % cfg.base_url)
    print("模型：%s（provider %s）" % (cfg.model, cfg.provider))
    print("密钥：%s（来源：%s）" % (cfg.masked_key() or "未找到", cfg.key_source or "-"))
    if not cfg.has_key:
        raise ExtractError(
            "未找到可用的模型密钥。请设置 NEORIGIN_API_KEY，或在 %s 的 refs 段登记，"
            "或设置 GROWTH_LLM_API_KEY。" % os.path.join(dsh_home(), ".credentials.yaml"))
    client = LLMClient(cfg)
    reply = client.health_check()
    usage = reply.usage_summary()
    print("连通性：正常，模型回复「%s」" % reply.text.strip())
    print("  用时 %d ms｜token 输入 %s / 输出 %s（其中推理 %s）/ 合计 %s"
          % (reply.duration_ms, usage["input"], usage["output"],
             usage["reasoning_output"], usage["total"]))


def _ai_extract(args):
    store = Store(args.db)
    try:
        result = Extraction(store).run(
            args.document, model=args.model, max_fragments=args.max_fragments,
            temperature=args.temperature, max_tokens=args.max_tokens,
            trigger_type=args.trigger, dry_run=args.dry_run)
        if result.get("dry_run"):
            print("== 提示词预览（未调用模型，未写入任何记录）==")
            for message in result["messages"]:
                print("\n---- %s ----\n%s" % (message["role"], message["content"]))
            return
        usage = result["usage"]
        print("✓ AI 作业完成：%s" % result["job_id"])
        print("  模型 %s｜用时 %d ms｜产出待审核建议 %d 条"
              % (result["model"], result["duration_ms"], result["proposal_count"]))
        print("  token 输入 %s / 输出 %s（其中推理 %s）/ 合计 %s"
              % (usage["input"], usage["output"], usage["reasoning_output"], usage["total"]))
        print("  覆盖片段 %d/%d" % (result["coverage"]["used"], result["coverage"]["total"]))
        if result.get("notes"):
            print("  模型说明：%s" % result["notes"])
        for pid in result["proposal_ids"]:
            row = store.get("change_proposal", pid)
            print("  · %s｜%s｜%s" % (pid, row["target_entity_type"], row["diff_summary"]))
        if not args.approve:
            print("\n下一步：python -m app.cli ai proposals 查看，"
                  "python -m app.cli ai show <建议ID> 看证据，"
                  "python -m app.cli ai confirm <建议ID> 写入档案")
            return
        outcome = Review(store).confirm_batch(job_id=result["job_id"], note=args.note)
        print("\n== 自动确认 ==")
        print("  待处理 %d 条：直接确认 %d，补齐后确认 %d，未通过 %d"
              % (outcome["total"], outcome["confirmed"], outcome["modified"],
                 len(outcome["failed"])))
        for item in outcome["failed"][:20]:
            print("  ✗ %s（%s）：%s" % (item["proposal_id"], item["entity"], item["reason"]))
    finally:
        store.close()


def _ai_cleanup(args):
    store = Store(args.db)
    try:
        fixed = Extraction(store).cleanup_stale_jobs(note=args.note)
        if not fixed:
            print("没有中断的作业（running / queued）")
            return
        print("✓ 已把 %d 条中断作业标记为 failed：" % len(fixed))
        for job_id in fixed:
            print("  %s" % job_id)
        print("  说明：作业记录只作历史留痕，不会自动重跑；需要重跑请重新执行 ai extract。")
    finally:
        store.close()


def _ai_jobs(args):
    store = Store(args.db)
    try:
        rows = Extraction(store).jobs(args.limit)
        if not rows:
            print("还没有 AI 作业记录")
            return
        for row in rows:
            print("%s｜%s｜%s｜建议 %s 条｜片段 %s｜%s ms"
                  % (row["id"], row["status"], row["model_name"] or "-",
                     row.get("proposal_count") or 0, row.get("input_fragment_count") or 0,
                     row.get("duration_ms") or 0))
            if row.get("result_summary"):
                print("    %s" % row["result_summary"])
            if row["status"] == "failed":
                print("    失败：%s %s" % (row.get("error_code") or "-", row.get("error_message") or ""))
    finally:
        store.close()


def _ai_proposals(args):
    store = Store(args.db)
    try:
        rows = Review(store).list(status=args.status, job_id=args.job, limit=args.limit)
        if not rows:
            print("没有符合条件的建议（状态：%s）" % args.status)
            return
        for row in rows:
            target = row.get("target_entity_id")
            print("%s｜%s｜%s%s" % (row["id"], row["status"], row["change_type"],
                                   "（%s）" % row["target_entity_type"]))
            print("    %s" % row["diff_summary"])
            if target:
                print("    目标记录：%s" % target)
    finally:
        store.close()


def _ai_show(args):
    store = Store(args.db)
    try:
        data = Review(store).show(args.proposal)
        proposal = data["proposal"]
        print("== 建议 %s ==" % proposal["id"])
        print("  动作：%s → %s｜状态：%s｜作业：%s"
              % (proposal["change_type"], proposal["target_entity_type"],
                 proposal["status"], proposal.get("job_id") or "-"))
        print("  摘要：%s" % proposal["diff_summary"])
        if proposal.get("reason"):
            print("  理由：%s" % proposal["reason"])
        if data["target"]:
            name = data["target"].get("name") or data["target"].get("title")
            print("  目标记录：%s（%s）" % (name, proposal["target_entity_id"]))
        print("\n-- 建议写入的字段 --")
        for key, value in data["payload"].items():
            print("  %s = %s" % (key, json.dumps(value, ensure_ascii=False)
                                 if not isinstance(value, str) else value))
        if data["requirements"]:
            print("\n-- 确认前还缺的必填项 --")
            for problem in data["requirements"]:
                print("  ! %s" % problem)
        print("\n-- 证据（原文出处）--")
        if not data["evidences"]:
            print("  （模型没有给出证据，确认前请自行核对内容）")
        for ev in data["evidences"]:
            print("  《%s》%s" % (ev.get("document_title") or "-", ev.get("heading_path") or ""))
            print("    「%s」" % (ev["quote"] or "").replace("\n", " "))
            print("    片段 %s" % ev["fragment_id"])
    finally:
        store.close()


def _parse_sets(pairs):
    """把 --set 字段=值 解析成字典：值先尝试 JSON（数字/布尔/数组），失败则当字符串。"""
    overrides = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ExtractError("--set 的格式是 字段=值，收到：%s" % pair)
        key, raw = pair.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        overrides[key] = value
    return overrides


def _ai_confirm(args):
    store = Store(args.db)
    try:
        result = Review(store).confirm(args.proposal, overrides=_parse_sets(args.sets),
                                       note=args.note)
        print("✓ 已%s建议 %s，写入 %s 记录 %s"
              % ("改后确认" if result["status"] == "modified" else "确认",
                 result["proposal_id"], result["entity"], result["applied_entity_id"]))
        for pid in result["relinked"]:
            print("  ↳ 同批次建议 %s 的外键已回填" % pid)
        print("  查看结果：python -m app.cli trace %s %s"
              % (result["entity"], result["applied_entity_id"]))
    finally:
        store.close()


def _ai_reject(args):
    store = Store(args.db)
    try:
        result = Review(store).reject(args.proposal, note=args.note)
        print("✓ 已拒绝建议 %s（没有写入任何档案）" % result["proposal_id"])
    finally:
        store.close()


def _split_keywords(value):
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
        sync = FeishuSync(store, keywords=_split_keywords(args.match), auth=args.auth)
        report = sync.check()
        print("应用：%s（凭据来源：%s）" % (report["app_id"], report["key_source"] or "-"))
        print("接口：%s" % report["base_url"])
        print("身份：%s（用户授权：%s）" % (report["auth_mode"], report["user_auth"]))
        print("令牌：%s" % ("正常" if report["token_ok"] else "失败"))
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
        sync = FeishuSync(store, auth=args.auth)
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
        sync = FeishuSync(store, keywords=_split_keywords(args.match), auth=args.auth)
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
        print("\n下一步：python -m app.cli feishu pull%s"
              % ("" if args.source == "wiki" else " --source %s" % args.source))
    finally:
        store.close()


def _feishu_pull(args):
    store = Store(args.db)
    try:
        sync = FeishuSync(store, keywords=_split_keywords(args.match), auth=args.auth)
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
            print("\n下一步：python -m app.cli docs 查看资料，"
                  "python -m app.cli ai extract <资料ID> 让模型提取工作事项")
    finally:
        store.close()


def _feishu_auth(args):
    cfg = resolve_feishu_config()
    redirect = args.redirect_uri or DEFAULT_REDIRECT_URI
    scope = args.scope or list(DEFAULT_SCOPES)
    if args.code:
        tokens = exchange_code(cfg, args.code, redirect_uri=redirect)
        backup = store_tokens(tokens, scope=" ".join(scope))
        print("✓ 授权成功，令牌已保存到凭据文件（备份：%s）" % backup)
        _print_whoami(cfg, tokens["access_token"])
        return
    url = authorize_url(cfg, redirect_uri=redirect, scope=scope, state=args.state)
    print("应用：%s（凭据来源：%s）" % (cfg.masked_app_id(), cfg.key_source or "-"))
    print("重定向地址：%s" % redirect)
    print("请求的权限：%s" % " ".join(scope))
    print("\n在浏览器打开下面的链接并同意授权：\n%s\n" % url)
    if args.no_wait:
        print("同意后浏览器会跳到重定向地址，把地址栏里的 code 参数复制回来执行：")
        print("  python -m app.cli feishu auth --code <code>")
        return
    port = args.port or DEFAULT_PORT
    path = urllib.parse.urlparse(redirect).path or "/callback"
    print("等待授权回调（%s:%d%s，最多 %d 秒）…" % ("127.0.0.1", port, path, args.timeout))
    receiver = CodeReceiver(port=port, path=path, expected_state=args.state)
    code = receiver.wait(timeout=args.timeout)
    tokens = exchange_code(cfg, code, redirect_uri=redirect)
    backup = store_tokens(tokens, scope=" ".join(scope))
    print("✓ 授权成功，令牌已保存到凭据文件（备份：%s）" % backup)
    _print_whoami(cfg, tokens["access_token"])


def _print_whoami(cfg, access_token):
    try:
        info = user_info(cfg, access_token)
    except FeishuAuthError as exc:
        print("  （读取当前身份失败：%s）" % exc)
        return
    print("  当前身份：%s（open_id %s）" % (info.get("name"), info.get("open_id")))
    if info.get("email"):
        print("  邮箱：%s" % info["email"])


def _feishu_whoami(args):
    cfg = resolve_feishu_config()
    auth = UserAuth(cfg)
    print("用户授权：%s" % auth.describe())
    if not auth.has_token:
        return
    _print_whoami(cfg, auth.token())


def _feishu_logout(args):
    backup = clear_user_tokens()
    print("已清除本机保存的飞书用户令牌（备份：%s）" % backup)
    print("应用凭据（FEISHU_APP_ID / FEISHU_APP_SECRET）未改动。")


def _backup(args):
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


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="个人成长档案系统命令行")
    parser.add_argument("--db", default=DEFAULT_DB, help="数据库文件路径（默认 data/growth.db）")
    parser.add_argument("--log-dir", dest="log_dir",
                        help="日志目录（默认 data/logs）")
    parser.add_argument("--verbose", action="store_true", help="日志输出到标准错误"
                        "并把级别降到 DEBUG")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="按 schema/schema.sql 建库")
    p.set_defaults(func=_init)

    p = sub.add_parser("import", help="导入原始资料（文件、目录或 .zip）")
    p.add_argument("paths", nargs="+")
    p.add_argument("--type", help="资料类型（document_type 枚举，默认按文件名推断）")
    p.add_argument("--channel", default="file_upload", help="来源渠道（默认 file_upload）")
    p.add_argument("--handling", default="skip", choices=["skip", "new_version", "import_anyway"],
                   help="内容重复时的处理方式（默认 skip）")
    p.add_argument("--recursive", action="store_true", help="目录递归导入")
    p.add_argument("--label", help="导入批次名称")
    p.add_argument("--year", type=int,
                   help="文件名没写年份时用它推断期间（如 2026）")
    p.set_defaults(func=_import)

    p = sub.add_parser("periods", help="按年份补全已导入资料的期间（文件名没写年份时用）")
    p.add_argument("--year", type=int, required=True, help="用于推断的年份，如 2026")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="只预览补全结果，不写库")
    p.set_defaults(func=_periods)

    p = sub.add_parser("docs", help="列出已导入的原始资料")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--type", help="只看某类资料")
    p.set_defaults(func=_docs)

    p = sub.add_parser("show", help="查看一份资料的字段")
    p.add_argument("document_id")
    p.set_defaults(func=_show)

    p = sub.add_parser("fragments", help="查看资料的来源片段")
    p.add_argument("document_id")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p.set_defaults(func=_fragments)

    p = sub.add_parser("verify", help="校验片段字符区间与正文是否仍然一致")
    p.add_argument("document_id")
    p.set_defaults(func=_verify)

    p = sub.add_parser("audit", help="查看变更历史")
    p.add_argument("--entity")
    p.add_argument("--id")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=_audit)

    p = sub.add_parser("stats", help="各实体记录数")
    p.set_defaults(func=_stats)

    p = sub.add_parser("trace", help="查看来源追溯与关联")
    p.add_argument("entity")
    p.add_argument("entity_id")
    p.set_defaults(func=_trace)

    # ---- 第 3 步：项目 / 系统 / 模块 / 事项 / 主题 / 职责 --------------
    def add_fragments(parser):
        parser.add_argument("--from", dest="fragments", action="append", default=[],
                            metavar="片段ID", help="关联来源片段，可重复")
        parser.add_argument("--fact", choices=["true", "false"],
                            help="这条是事实还是推断（默认事实）")
        parser.add_argument("--basis", help="判定为推断时的事实依据（is_fact=false 必填）")

    p = sub.add_parser("project", help="项目档案")
    p.add_argument("action", choices=["add", "list", "show", "merge"])
    p.add_argument("name", nargs="?", help="add：项目名称")
    p.add_argument("--id", help="show：项目ID")
    p.add_argument("--keep", help="merge：保留哪条")
    p.add_argument("--drop", nargs="+", help="merge：要并入的重复记录")
    p.add_argument("--note", help="merge：归并依据说明")
    p.add_argument("--type", choices=_enum_choices("project_type"), help="项目类型")
    p.add_argument("--role", choices=_enum_choices("role_type"), help="个人角色")
    p.add_argument("--status", choices=_enum_choices("project_status"), default=None)
    p.add_argument("--start", help="参与起始（YYYY-MM-DD）")
    p.add_argument("--end", help="参与结束，留空表示仍在参与")
    p.add_argument("--domain", help="工作领域名称（不存在时自动新建，弱分类）")
    p.add_argument("--importance", type=int, help="重要度 1~5，用于挑选代表性项目")
    p.add_argument("--representative", action="store_true", help="标记为代表性项目")
    p.add_argument("--alias", action="append", help="历史叫法，可重复")
    p.add_argument("--background", help="业务背景")
    p.add_argument("--goal", help="目标与预期收益")
    p.add_argument("--scope", help="个人负责的部分")
    p.add_argument("--contribution", help="实际贡献")
    p.add_argument("--outcome", help="项目层面结果")
    p.add_argument("--limit", type=int, default=50)
    add_fragments(p)
    p.set_defaults(func=_project)

    p = sub.add_parser("system", help="系统 / 产品档案")
    p.add_argument("action", choices=["add", "list", "merge"])
    p.add_argument("name", nargs="?", help="add：系统名称")
    p.add_argument("--keep", help="merge：保留哪条")
    p.add_argument("--drop", nargs="+", help="merge：要并入的重复记录")
    p.add_argument("--note", help="merge：归并依据说明")
    p.add_argument("--type", choices=_enum_choices("system_type"), help="系统类型")
    p.add_argument("--status", choices=_enum_choices("system_status"))
    p.add_argument("--role", choices=_enum_choices("role_type"))
    p.add_argument("--code", help="内部代号或系统编号")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--domain")
    p.add_argument("--alias", action="append")
    p.add_argument("--description")
    p.add_argument("--scope", help="个人负责的部分")
    p.add_argument("--representative", action="store_true")
    p.add_argument("--limit", type=int, default=50)
    add_fragments(p)
    p.set_defaults(func=_system)

    p = sub.add_parser("module", help="功能模块档案")
    p.add_argument("action", choices=["add", "list", "tree"])
    p.add_argument("name", nargs="?", help="add：模块名称")
    p.add_argument("--system", help="所属系统（ID 或名称）")
    p.add_argument("--parent", help="上级模块（ID 或名称）")
    p.add_argument("--type", choices=_enum_choices("module_type"))
    p.add_argument("--role", choices=_enum_choices("role_type"))
    p.add_argument("--code")
    p.add_argument("--alias", action="append")
    p.add_argument("--description")
    p.add_argument("--start")
    p.add_argument("--limit", type=int, default=100)
    add_fragments(p)
    p.set_defaults(func=_module)

    p = sub.add_parser("item", help="工作事项档案")
    p.add_argument("action", choices=["add", "list", "show"])
    p.add_argument("title", nargs="?", help="add：一句话概括")
    p.add_argument("--id", help="show：事项ID")
    p.add_argument("--type", choices=_enum_choices("work_item_type"), help="事项性质")
    p.add_argument("--content", help="具体做了什么（缺省时取来源片段原文）")
    p.add_argument("--date", help="发生时间（YYYY-MM-DD）；缺省时取来源资料的期间")
    p.add_argument("--precision", choices=_enum_choices("date_precision"),
                   help="时间精度，周报来源的事项标 week 或 month")
    p.add_argument("--role", choices=_enum_choices("role_type"))
    p.add_argument("--project", help="关联项目（ID 或名称）")
    p.add_argument("--system", help="关联系统（ID 或名称）")
    p.add_argument("--module", help="关联功能模块（ID 或名称）")
    p.add_argument("--domain")
    p.add_argument("--complexity", type=int, help="复杂度 1~5")
    p.add_argument("--complexity-basis", dest="complexity_basis", help="复杂度判定依据")
    p.add_argument("--routine", action="store_true", help="例行事务单独标记")
    p.add_argument("--hours", type=float, help="个人投入工时（小时）")
    p.add_argument("--background", help="为什么要做")
    p.add_argument("--process", help="如何做的")
    p.add_argument("--result", help="做完的结果")
    p.add_argument("--limit", type=int, default=30)
    add_fragments(p)
    p.set_defaults(func=_item)

    p = sub.add_parser("theme", help="持续工作主题（跨周报月报归并）")
    p.add_argument("action", choices=["add", "list", "show", "member", "merge"])
    p.add_argument("name", nargs="?", help="add：主题名称")
    p.add_argument("theme_id", nargs="?", help="show/member/merge 的主题ID")
    p.add_argument("--keep", help="merge：保留哪条")
    p.add_argument("--drop", nargs="+", help="merge：要并入的重复记录")
    p.add_argument("--note", help="merge：归并依据说明")
    p.add_argument("--type", choices=_enum_choices("theme_type"))
    p.add_argument("--status", choices=_enum_choices("theme_status"))
    p.add_argument("--project", help="关联项目（ID 或名称）")
    p.add_argument("--domain")
    p.add_argument("--description")
    p.add_argument("--item", action="append", metavar="事项ID", help="member：加入工作事项")
    p.add_argument("--case", action="append", metavar="成果ID", help="member：加入成果案例")
    p.add_argument("--doc", action="append", metavar="资料ID", help="member：加入原始资料")
    p.add_argument("--limit", type=int, default=50)
    add_fragments(p)
    p.set_defaults(func=_theme)

    p = sub.add_parser("role", help="职责与贡献记录")
    p.add_argument("action", choices=["add", "list"])
    p.add_argument("target", nargs="?", choices=["project", "system", "module"],
                   help="add：职责所属对象类型")
    p.add_argument("target_id", nargs="?", help="add：对象 ID 或名称")
    p.add_argument("--role", choices=_enum_choices("role_type"))
    p.add_argument("--start", help="职责开始时间（YYYY-MM-DD）")
    p.add_argument("--end", help="职责结束时间，留空表示仍在担任")
    p.add_argument("--scope", help="职责范围")
    p.add_argument("--contribution", help="贡献说明")
    p.add_argument("--reason", help="职责变化原因")
    p.add_argument("--ongoing", action="store_true")
    p.add_argument("--primary", action="store_true", help="是否主职")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=_role)

    p = sub.add_parser("goal", help="成长目标：可跟踪、可验收的个人目标")
    p.add_argument("action", choices=["add", "list", "show", "update"])
    p.add_argument("name", nargs="?", help="add：目标名称")
    p.add_argument("goal_id", nargs="?", help="show/update：目标 ID 或名称")
    p.add_argument("--type", choices=_enum_choices("goal_type"), help="目标类型（默认 capability）")
    p.add_argument("--status", choices=_enum_choices("goal_status"), help="目标状态")
    p.add_argument("--start", help="开始日期（YYYY-MM-DD，必填）")
    p.add_argument("--end", help="目标日期（留空表示长期）")
    p.add_argument("--precision", choices=_enum_choices("date_precision"), help="时间精度（默认 month）")
    p.add_argument("--progress", type=int, help="进度 0~100")
    p.add_argument("--criteria", help="达成标准（可判定的完成条件）")
    p.add_argument("--measure", help="衡量方式（用什么证据判断进度）")
    p.add_argument("--note", help="进展说明；放弃目标时必填")
    p.add_argument("--description", help="目标说明（为什么定它、差距在哪）")
    p.add_argument("--project", help="关联项目（ID 或名称）")
    p.add_argument("--domain", help="关联工作领域（ID 或名称）")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=_goal)

    p = sub.add_parser("profile", help="本人档案（当前职位、行业、简介）")
    p.add_argument("action", choices=["show", "set"], nargs="?", default="show")
    p.add_argument("--name", help="姓名或称呼")
    p.add_argument("--title", help="当前职位，如 产品经理")
    p.add_argument("--company", help="当前公司")
    p.add_argument("--industry", help="所属行业")
    p.add_argument("--summary", help="个人简介（自述，不由 AI 代写）")
    p.add_argument("--target", help="目标岗位")
    p.add_argument("--city", help="常驻城市")
    p.add_argument("--start", help="参加工作日期（YYYY-MM-DD）")
    p.add_argument("--set", action="store_true", help="写入（不带则只查看）")
    p.set_defaults(func=_profile)

    p = sub.add_parser("link", help="把来源片段关联到任意档案记录")
    p.add_argument("entity")
    p.add_argument("id")
    p.add_argument("--from", dest="fragments", action="append", default=[], required=True,
                   metavar="片段ID")
    p.add_argument("--relation", default="primary_source",
                   choices=_enum_choices("provenance_relation"))
    p.set_defaults(func=_link)

    p = sub.add_parser("overview", help="成长总览（数量、代表项目、近期事项、领域分布）")
    p.set_defaults(func=_overview)

    p = sub.add_parser("ai", help="AI 提取与建议审核（第 4 步，需要模型网关）")
    ai = p.add_subparsers(dest="action", required=True)

    q = ai.add_parser("seed", help="把 prompts/*.json 写入提示词模板与 Agent 工作流")
    q.set_defaults(func=_ai_seed)

    q = ai.add_parser("check", help="检查模型网关配置与连通性")
    q.add_argument("--model", help="覆盖模型 id（默认读配置）")
    q.set_defaults(func=_ai_check)

    q = ai.add_parser("extract", help="对一份原始资料做提取，产出一批待审核建议")
    q.add_argument("document", help="资料 ID（python -m app.cli docs 查看）")
    q.add_argument("--model", help="覆盖模型 id")
    q.add_argument("--max-fragments", type=int, dest="max_fragments", help="只送前 N 个片段")
    q.add_argument("--temperature", type=float)
    q.add_argument("--max-tokens", type=int, dest="max_tokens")
    q.add_argument("--trigger", default="manual", help="触发方式（默认 manual）")
    q.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="只打印将要发送的提示词，不调用模型、不写库")
    q.add_argument("--approve", action="store_true",
                   help="提取成功后立即批量确认本作业的建议")
    q.add_argument("--note", help="批量确认时写入的审核备注")
    q.set_defaults(func=_ai_extract)

    q = ai.add_parser("jobs", help="查看 AI 作业记录")
    q.add_argument("--limit", type=int, default=20)
    q.set_defaults(func=_ai_jobs)

    q = ai.add_parser("cleanup", help="把中断的作业（running/queued）标记为 failed")
    q.add_argument("--note", help="写进 error_message 的说明")
    q.set_defaults(func=_ai_cleanup)

    q = ai.add_parser("proposals", help="查看待审核建议")
    q.add_argument("--status", default="pending",
                   help="pending / confirmed / modified / rejected / superseded / expired / all")
    q.add_argument("--job", help="只看某个作业产出的建议")
    q.add_argument("--limit", type=int, default=50)
    q.set_defaults(func=_ai_proposals)

    q = ai.add_parser("show", help="查看一条建议的完整内容与证据")
    q.add_argument("proposal", help="建议 ID")
    q.set_defaults(func=_ai_show)

    q = ai.add_parser("confirm", help="确认建议并写入正式档案")
    q.add_argument("proposal", help="建议 ID")
    q.add_argument("--set", action="append", dest="sets", metavar="字段=值",
                   help="修改建议内容后再确认（可重复）")
    q.add_argument("--note", help="审核备注")
    q.set_defaults(func=_ai_confirm)

    q = ai.add_parser("reject", help="拒绝建议（不写入档案）")
    q.add_argument("proposal", help="建议 ID")
    q.add_argument("--note", help="拒绝原因")
    q.set_defaults(func=_ai_reject)

    p = sub.add_parser("feishu", help="飞书资料同步（知识库 / 云盘里的周报月报）")
    fs = p.add_subparsers(dest="action", required=True)

    q = fs.add_parser("check", help="检查凭据、权限与可见范围")
    q.add_argument("--match", help="只看名称含这些关键词的资料（逗号分隔，默认 周报,月报）")
    q.add_argument("--auth", default="auto", choices=["auto", "user", "tenant"],
                   help="用哪种身份调用飞书（默认 auto：有用户授权就用用户身份）")
    q.set_defaults(func=_feishu_check)

    q = fs.add_parser("spaces", help="列出当前身份可见的知识库")
    q.add_argument("--auth", default="auto", choices=["auto", "user", "tenant"])
    q.set_defaults(func=_feishu_spaces)

    q = fs.add_parser("scan", help="扫描匹配的资料（不写库）")
    q.add_argument("--source", default="wiki", choices=["wiki", "drive", "both"],
                   help="从知识库还是云盘扫描（默认 wiki）")
    q.add_argument("--folder", help="云盘文件夹 token（默认根目录）")
    q.add_argument("--depth", type=int, default=3, help="云盘递归层数（默认 3）")
    q.add_argument("--match", help="名称关键词，逗号分隔（默认 周报,月报）")
    q.add_argument("--limit", type=int, default=500, help="最多扫描多少条")
    q.add_argument("--auth", default="auto", choices=["auto", "user", "tenant"])
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
    q.add_argument("--auth", default="auto", choices=["auto", "user", "tenant"])
    q.set_defaults(func=_feishu_pull)

    q = fs.add_parser("auth", help="用飞书账号授权，换取用户身份令牌（读「我的空间」）")
    q.add_argument("--redirect-uri", dest="redirect_uri",
                   help="重定向地址（默认 %s，需与开放平台配置一致）" % DEFAULT_REDIRECT_URI)
    q.add_argument("--scope", action="append",
                   help="权限点，可重复；默认 drive/wiki/docx/sheets 只读 + offline_access")
    q.add_argument("--state", default="growth-archive", help="防重放校验串")
    q.add_argument("--port", type=int, help="本地回调端口（默认 8765）")
    q.add_argument("--timeout", type=int, default=300, help="等待回调的秒数（默认 300）")
    q.add_argument("--no-wait", action="store_true", dest="no_wait",
                   help="只打印授权链接，稍后用 --code 手动换取令牌")
    q.add_argument("--code", help="已拿到的授权码（与 --no-wait 配合）")
    q.set_defaults(func=_feishu_auth)

    q = fs.add_parser("whoami", help="查看当前用户授权身份与有效期")
    q.set_defaults(func=_feishu_whoami)

    q = fs.add_parser("logout", help="清除本机保存的飞书用户令牌")
    q.set_defaults(func=_feishu_logout)

    bk = sub.add_parser("backup", help="备份数据库与附件、校验备份文件")
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

    return parser


def main(argv=None):
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
    except Exception as exc:  # 未预期异常也要留痕，但不把 traceback 直接甩给用户
        log.exception("未预期异常：%s", exc)
        print("内部错误：%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        print("详细堆栈已写入日志（默认 data/logs/app.log）", file=sys.stderr)
        return 3
    log.info("命令完成：%s", args.command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
