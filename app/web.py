# -*- coding: utf-8 -*-
"""本地只读 Web 界面：静态页 + JSON API。

形态：`python -m app.web --db data/growth.db --port 8765`
- 只监听 127.0.0.1，单用户本地使用，不做登录；
- 只提供 GET 接口，写操作仍在 CLI（`ai confirm` 等）；
- 只用标准库（http.server / json / datetime），产品代码仍零第三方依赖。

接口清单见 docs/UI设计方案.md 第 8.3 节。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .ids import now_iso
from .store import Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIST = os.path.join(ROOT, "web", "dist")


def _week_start(value):
    """把 'YYYY-MM-DD...' 归到所在 ISO 周的周一；无法解析返回 None。"""
    if not value:
        return None
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
    return day - timedelta(days=day.weekday())


def _month_key(value):
    if not value:
        return None
    return str(value)[:7]


class Api:
    """只读查询层：把库里的行聚合成页面需要的形状。"""

    def __init__(self, db_path):
        self.db_path = db_path
        # SQLite 连接不能跨线程使用：每个请求线程各开一个（本地单用户，代价可忽略）
        self._local = threading.local()

    @property
    def store(self):
        store = getattr(self._local, "store", None)
        if store is None:
            store = Store(self.db_path)
            self._local.store = store
        return store

    # ---- 基础 --------------------------------------------------------
    def health(self):
        counts = {}
        for entity in ("work_item", "project", "business_system", "function_module",
                       "source_document", "source_fragment", "change_proposal",
                       "capability_evidence", "growth_snapshot"):
            counts[entity] = self.store.count(entity)
        return {"ok": True, "db": self.store.db_path,
                "generated_at": now_iso(), "counts": counts}

    def _project_map(self):
        rows = self.store.list("project", limit=10000)
        return {row["id"]: row for row in rows}

    def _items(self, where=None, limit=10000):
        return self.store.list("work_item", where or {}, limit=limit,
                               order_by="occurred_at DESC")

    @staticmethod
    def _item_card(item, projects):
        project = projects.get(item.get("project_id")) if item.get("project_id") else None
        return {"id": item["id"], "title": item["title"],
                "occurred_at": item.get("occurred_at"),
                "date_precision": item.get("date_precision"),
                "item_type": item.get("item_type"),
                "is_routine": bool(item.get("is_routine")),
                "is_follow_up_needed": bool(item.get("is_follow_up_needed")),
                "project_id": item.get("project_id"),
                "project_name": project["name"] if project else None}

    # ---- 首页 --------------------------------------------------------
    def summary(self, weeks=12):
        projects = self._project_map()
        items = self._items()
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        buckets = {}
        for item in items:
            start = _week_start(item.get("occurred_at"))
            if start is None:
                continue
            buckets[start] = buckets.get(start, 0) + 1
        series = []
        for offset in range(weeks - 1, -1, -1):
            start = this_monday - timedelta(weeks=offset)
            series.append({"week_start": start.isoformat(),
                           "label": start.strftime("%m/%d"),
                           "count": buckets.get(start, 0)})

        def total(begin, end):
            return sum(point["count"] for point in series[begin:end])

        current, previous = total(-4, None), total(-8, -4)
        delta = None if previous == 0 else round((current - previous) / previous * 100, 1)

        active = [p for p in projects.values()
                  if p.get("status") in ("active", "in_progress", "planning")]
        by_project = {}
        latest_activity = {}
        for item in items:
            pid = item.get("project_id")
            if pid:
                by_project[pid] = by_project.get(pid, 0) + 1
                occurred = item.get("occurred_at") or ""
                if occurred > latest_activity.get(pid, ""):
                    latest_activity[pid] = occurred
        active_cards = sorted(
            ({"id": p["id"], "name": p["name"], "status": p.get("status"),
              "role": p.get("my_role"), "goal": p.get("goal"),
              "updated_at": p.get("updated_at"), "item_count": by_project.get(p["id"], 0),
              "last_activity": latest_activity.get(p["id"])}
             for p in active),
            key=lambda row: (row["last_activity"] or "", row["updated_at"] or ""), reverse=True)

        missing_domain = [item for item in items if not item.get("domain_id")]
        missing_goal = [p for p in active if not (p.get("goal") or "").strip()]
        pending = self.store.count("change_proposal", {"status": "pending"})

        return {
            "generated_at": now_iso(),
            "counts": {
                "items": len(items),
                "projects": len(projects),
                "active_projects": len(active),
                "documents": self.store.count("source_document"),
                "fragments": self.store.count("source_fragment"),
                "proposals": self.store.count("change_proposal"),
            },
            "trend": {"weeks": series, "current_4w": current,
                      "previous_4w": previous, "delta_pct": delta},
            "recent_items": [self._item_card(item, projects) for item in items[:12]],
            "active_projects": active_cards[:6],
            "todos": {"pending_proposals": pending,
                      "items_missing_domain": len(missing_domain),
                      "projects_missing_goal": len(missing_goal)},
            "stages": [],
        }

    # ---- 列表页 ------------------------------------------------------
    def items(self, params):
        projects = self._project_map()
        where = {}
        if params.get("type"):
            where["item_type"] = params["type"]
        if params.get("project_id"):
            where["project_id"] = params["project_id"]
        rows = self.store.list("work_item", where, limit=10000,
                               order_by="occurred_at DESC")
        start = params.get("from")
        end = params.get("to")
        query = (params.get("q") or "").strip().lower()
        if start:
            rows = [row for row in rows
                    if (row.get("occurred_at") or "")[:10] >= start]
        if end:
            rows = [row for row in rows
                    if (row.get("occurred_at") or "")[:10] <= end]
        if query:
            rows = [row for row in rows if query in (row.get("title") or "").lower()]
        total = len(rows)
        offset = max(int(params.get("offset") or 0), 0)
        limit = min(max(int(params.get("limit") or 50), 1), 200)
        page = rows[offset:offset + limit]
        return {"total": total, "offset": offset, "limit": limit,
                "items": [self._item_card(row, projects) for row in page]}

    def projects(self):
        projects = self._project_map()
        counts, latest = {}, {}
        for item in self._items():
            pid = item.get("project_id")
            if not pid:
                continue
            counts[pid] = counts.get(pid, 0) + 1
            occurred = item.get("occurred_at") or ""
            if occurred > latest.get(pid, ""):
                latest[pid] = occurred
        cards = []
        for row in projects.values():
            cards.append({"id": row["id"], "name": row["name"],
                          "status": row.get("status"), "project_type": row.get("project_type"),
                          "my_role": row.get("my_role"), "goal": row.get("goal"),
                          "start_date": row.get("start_date"), "end_date": row.get("end_date"),
                          "item_count": counts.get(row["id"], 0),
                          "last_activity": latest.get(row["id"])})
        cards.sort(key=lambda row: (row["item_count"], row["last_activity"] or ""), reverse=True)
        return {"total": len(cards), "items": cards}

    def project(self, project_id):
        row = self.store.get("project", project_id)
        item_rows = self.store.list("work_item", {"project_id": project_id},
                                    limit=2000, order_by="occurred_at DESC")
        by_type = {}
        for item in item_rows:
            key = item.get("item_type") or "unknown"
            by_type[key] = by_type.get(key, 0) + 1
        domains = self.store.list("work_domain", limit=200)
        domain_names = {d["id"]: d["name"] for d in domains}
        return {"project": row,
                "items": [dict(item, domain_name=domain_names.get(item.get("domain_id")))
                          for item in item_rows[:100]],
                "item_count": len(item_rows),
                "by_type": sorted(({"key": k, "count": v} for k, v in by_type.items()),
                                  key=lambda row: row["count"], reverse=True)}

    def documents(self, params):
        limit = min(max(int(params.get("limit") or 50), 1), 200)
        offset = max(int(params.get("offset") or 0), 0)
        docs = self.store.list("source_document", limit=limit, offset=offset,
                               order_by="period_start DESC, created_at DESC")
        total = self.store.count("source_document")
        cards = []
        for doc in docs:
            proposals = self.store.query(
                "SELECT status, COUNT(*) AS n FROM change_proposal "
                "WHERE target_entity_type IN ('work_item','project','business_system',"
                "'function_module','work_domain') AND id IN ("
                "  SELECT proposal_id FROM proposal_evidence WHERE fragment_id IN ("
                "    SELECT id FROM source_fragment WHERE document_id = ?)) "
                "GROUP BY status", (doc["id"],))
            cards.append({"id": doc["id"], "title": doc["title"],
                          "doc_type": doc.get("doc_type"),
                          "period_start": doc.get("period_start"),
                          "period_end": doc.get("period_end"),
                          "fragment_count": self.store.count(
                              "source_fragment", {"document_id": doc["id"]}),
                          "proposal_counts": {row["status"]: row["n"] for row in proposals}})
        return {"total": total, "offset": offset, "limit": limit, "items": cards}

    # ---- 数据分析 ----------------------------------------------------
    def trend(self, params):
        weeks = min(max(int(params.get("weeks") or 26), 4), 104)
        buckets = {}
        for item in self._items():
            start = _week_start(item.get("occurred_at"))
            if start:
                buckets[start] = buckets.get(start, 0) + 1
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        series = []
        for offset in range(weeks - 1, -1, -1):
            start = this_monday - timedelta(weeks=offset)
            series.append({"week_start": start.isoformat(),
                           "label": start.strftime("%m/%d"),
                           "count": buckets.get(start, 0)})
        return {"weeks": series, "total": len(self._items())}

    def mix(self):
        items = self._items()
        domains = {d["id"]: d["name"] for d in self.store.list("work_domain", limit=200)}
        by_type, by_domain = {}, {}
        for item in items:
            by_type[item.get("item_type") or "unknown"] = \
                by_type.get(item.get("item_type") or "unknown", 0) + 1
            key = domains.get(item.get("domain_id")) or "未标注领域"
            by_domain[key] = by_domain.get(key, 0) + 1
        return {"total": len(items),
                "by_type": sorted(({"key": k, "count": v} for k, v in by_type.items()),
                                  key=lambda row: row["count"], reverse=True),
                "by_domain": sorted(({"key": k, "count": v} for k, v in by_domain.items()),
                                    key=lambda row: row["count"], reverse=True)}

    def heatmap(self, weeks=26):
        """按 ISO 周 × 星期聚合，画「哪几周断更了」。"""
        buckets = {}
        for item in self._items():
            start = _week_start(item.get("occurred_at"))
            if not start:
                continue
            weekday = date.fromisoformat(str(item["occurred_at"])[:10]).weekday()
            buckets[(start.isoformat(), weekday)] = buckets.get((start.isoformat(), weekday), 0) + 1
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        cells, max_count = [], 0
        for offset in range(int(weeks) - 1, -1, -1):
            start = this_monday - timedelta(weeks=offset)
            for weekday in range(7):
                count = buckets.get((start.isoformat(), weekday), 0)
                max_count = max(max_count, count)
                cells.append({"week_start": start.isoformat(),
                              "weekday": weekday, "count": count})
        return {"weeks": int(weeks), "max": max_count, "cells": cells}

    # ---- 复盘 / 建议 -------------------------------------------------
    def proposals(self, params):
        status = params.get("status") or "pending"
        rows = self.store.list("change_proposal", {"status": status}, limit=200,
                               order_by="created_at DESC")
        return {"total": self.store.count("change_proposal", {"status": status}),
                "items": [{"id": row["id"], "change_type": row["change_type"],
                           "entity": row["target_entity_type"],
                           "summary": row.get("diff_summary"),
                           "created_at": row.get("created_at"),
                           "job_id": row.get("job_id")} for row in rows]}

    def _goal_cards(self):
        """成长目标实体：进度、剩余天数、关联对象名。"""
        projects = self._project_map()
        today = date.today()
        out = []
        for row in self.store.list("growth_goal", limit=200,
                                   order_by="status ASC, end_date ASC"):
            end = row.get("end_date")
            days_left = None
            if end:
                try:
                    days_left = (date.fromisoformat(end[:10]) - today).days
                except ValueError:
                    days_left = None
            proj = projects.get(row.get("related_project_id") or "")
            out.append({
                "id": row["id"], "name": row["name"], "goal_type": row["goal_type"],
                "status": row["status"], "progress_percent": int(row["progress_percent"] or 0),
                "start_date": row.get("start_date"), "end_date": end,
                "days_left": days_left, "success_criteria": row.get("success_criteria"),
                "measurement_note": row.get("measurement_note"),
                "progress_note": row.get("progress_note"),
                "project_name": proj["name"] if proj else None,
            })
        return out

    def profile(self):
        rows = self.store.list("user_profile", limit=1)
        if not rows:
            return {"exists": False}
        row = rows[0]
        # 前端按 company/city 命名取用，这里做一次显式改名，避免直接暴露列名
        mapping = {
            "display_name": "display_name", "current_title": "current_title",
            "current_company": "company", "industry": "industry",
            "work_start_date": "work_start_date", "target_position": "target_position",
            "location_city": "city", "summary": "summary",
        }
        return {"exists": True, **{out: row.get(col) for col, out in mapping.items()}}

    def goals(self):
        """成长目标：已持久化的目标 + 从真实数据算出的「该补什么」建议。

        - 能力证据缺项（capability_evidence.is_supplement_needed）
        - 事项没标领域（无法做领域分布）
        - 进行中项目没写目标（无法判断方向）
        - 只有一件事的项目（可能是碎片工作，需要合并或忽略）
        """
        suggestions = []
        items = self._items()
        projects = self._project_map()
        missing_domain = [item for item in items if not item.get("domain_id")]
        if missing_domain:
            suggestions.append({
                "id": "domain-gap", "kind": "data", "severity": "medium",
                "title": "还有 %d 条事项没有标注工作领域" % len(missing_domain),
                "rationale": "领域是成长分析的分组维度；缺了它，领域分布与阶段对比都不完整。",
                "action": "在成长档案里逐条补领域，或后续用 AI 归类",
                "count": len(missing_domain)})
        no_goal = [p for p in projects.values()
                   if p.get("status") in ("active", "in_progress", "planning")
                   and not (p.get("goal") or "").strip()]
        if no_goal:
            suggestions.append({
                "id": "goal-gap", "kind": "data", "severity": "medium",
                "title": "%d 个进行中项目没有写目标" % len(no_goal),
                "rationale": "项目目标是判断「这件事是否值得做」的依据，也是阶段复盘的输入。",
                "action": "打开项目详情补充 goal 字段",
                "count": len(no_goal)})
        thin = [p for p in projects.values() if p.get("item_count") == 0]
        thin_projects = [p for p in projects.values()
                         if sum(1 for item in items if item.get("project_id") == p["id"]) == 1]
        if thin_projects:
            suggestions.append({
                "id": "thin-projects", "kind": "insight", "severity": "low",
                "title": "%d 个项目只有一条事项记录" % len(thin_projects),
                "rationale": "单条记录的项目可能是一次性杂事，考虑合并到相邻项目或标为不纳入统计。",
                "action": "在项目页做合并或归档",
                "count": len(thin_projects)})
        gaps = self.store.query(
            "SELECT capability_id, COUNT(*) AS n FROM capability_evidence "
            "WHERE is_supplement_needed = 1 GROUP BY capability_id")
        if gaps:
            suggestions.append({
                "id": "capability-gap", "kind": "growth", "severity": "high",
                "title": "%d 项能力证据待补" % len(gaps),
                "rationale": "能力判断需要工作证据支撑，缺证据的能力不能写进画像与材料。",
                "action": "为每项能力补充对应事项与成果",
                "count": len(gaps)})
        if not self.store.count("capability"):
            suggestions.append({
                "id": "capability-empty", "kind": "growth", "severity": "high",
                "title": "能力词典还没有建立",
                "rationale": "第 5 步（能力词典与能力证据）尚未实现，当前无法生成能力雷达与成长目标。",
                "action": "完成第 5 步后，这里会自动出现「补齐某项能力」的具体目标",
                "count": 0})
        return {"generated_at": now_iso(), "goals": self._goal_cards(),
                "suggestions": suggestions, "persisted": True,
                "note": "goals 是可跟踪的成长目标（有周期、达成标准与进度）；"
                        "suggestions 是按真实数据算出的补全建议，确认后再转成目标。"}


class Handler(BaseHTTPRequestHandler):
    server_version = "GrowthUI/0.1"

    def log_message(self, fmt, *args):  # 安静：只把 5xx 打到 stderr
        if args and str(args[1]).startswith("5"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---- 响应工具 ----------------------------------------------------
    def _send(self, status, body, content_type="application/json; charset=utf-8",
              extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status=200):
        self._send(status, payload)

    def _static(self, path):
        dist = self.server.dist
        rel = path.lstrip("/") or "index.html"
        target = os.path.normpath(os.path.join(dist, unquote(rel)))
        if not target.startswith(os.path.abspath(dist)):
            return self._json({"error": "forbidden"}, 403)
        if os.path.isdir(target):
            target = os.path.join(target, "index.html")
        if not os.path.exists(target):
            # SPA 路由回退：/archive 这类路径交给前端路由
            target = os.path.join(dist, "index.html")
            if not os.path.exists(target):
                return self._json({"error": "界面还没构建：先在 web/ 执行 npm run build"}, 404)
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(target, "rb") as fp:
            body = fp.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- 路由 --------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        api = self.server.api
        try:
            if path == "/api/health":
                return self._json(api.health())
            if path == "/api/summary":
                return self._json(api.summary())
            if path == "/api/items":
                return self._json(api.items(params))
            if path == "/api/projects":
                return self._json(api.projects())
            if path.startswith("/api/projects/"):
                return self._json(api.project(path.rsplit("/", 1)[-1]))
            if path == "/api/documents":
                return self._json(api.documents(params))
            if path == "/api/insights/trend":
                return self._json(api.trend(params))
            if path == "/api/insights/mix":
                return self._json(api.mix())
            if path == "/api/insights/heatmap":
                return self._json(api.heatmap(int(params.get("weeks") or 26)))
            if path == "/api/proposals":
                return self._json(api.proposals(params))
            if path == "/api/goals":
                return self._json(api.goals())
            if path == "/api/profile":
                return self._json(api.profile())
            if path.startswith("/api/"):
                return self._json({"error": "not found", "path": path}, 404)
            return self._static(path)
        except FileNotFoundError as exc:
            return self._json({"error": "not found", "detail": str(exc)}, 404)
        except Exception as exc:  # noqa: BLE001 - 单用户本地服务，返回可读错误更重要
            return self._json({"error": "internal_error", "detail": str(exc)}, 500)


def make_server(db_path, port=8765, host="127.0.0.1", dist=DEFAULT_DIST):
    """建好但还没启动的服务；给 serve() 与一键启动脚本复用。"""
    server = ThreadingHTTPServer((host, port), Handler)
    server.api = Api(db_path)
    server.dist = os.path.abspath(dist)
    return server


def serve(db_path, host="127.0.0.1", port=8765, dist=DEFAULT_DIST):
    server = make_server(db_path, port, host, dist)
    print("个人成长档案界面：http://%s:%d/（Ctrl+C 停止）" % (host, port))
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m app.web",
        description="启动本地只读界面（127.0.0.1，单用户）")
    parser.add_argument("--db", default="data/growth.db", help="数据库路径")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认只监听本机）")
    parser.add_argument("--port", type=int, default=8765, help="端口")
    parser.add_argument("--dist", default=DEFAULT_DIST, help="前端构建产物目录")
    args = parser.parse_args(argv)
    if not os.path.exists(args.db):
        print("找不到数据库：%s（先执行 python -m app.cli init）" % args.db, file=sys.stderr)
        return 2
    serve(args.db, args.host, args.port, args.dist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
