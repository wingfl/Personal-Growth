# -*- coding: utf-8 -*-
"""第 3 步（需求第 7 章第 3 项）：项目 / 系统 / 功能模块 / 工作事项档案。

数据流向：

    原始资料 source_document / source_fragment
        │ provenance_link（来源追溯，需求 1.4③）
        ▼
    项目 project ── 系统 business_system ── 功能模块 function_module
        │
        ▼
    工作事项 work_item（最小事实单元，能力证据的原始素材）
        │
        ├── 持续工作主题 work_theme + theme_member（跨周报月报归并，需求场景 2）
        └── 职责与贡献 role_record（带时间范围，支撑经历成长曲线）

本模块只做「录入 / 关联 / 归并 / 查询」，不做任何推断：AI 提取在后续步骤走
change_proposal，用户确认后才写入这里（需求 1.4④）。
"""
import calendar
import sqlite3
from datetime import date, timedelta

from .store import NotFound

# 多态关联表：类型列 + id 列，归并时要一起转移（否则引用会指向已软删除的记录）
POLYMORPHIC_REFS = [
    ("provenance_link", "entity_type", "entity_id"),
    ("tag_link", "entity_type", "entity_id"),
    ("theme_member", "member_type", "member_id"),
    ("entity_relation", "from_type", "from_id"),
    ("entity_relation", "to_type", "to_id"),
]


class ArchiveError(Exception):
    """档案操作错误（参数不完整、引用不存在、归并受阻等）。"""


def precision_from_period(start, end):
    """按期间跨度推断时间精度，避免把周报内容写成精确到日（需求：date_precision）。"""
    if not start:
        return "unknown"
    if not end or end == start:
        return "day"
    try:
        s, e = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return "unknown"
    span = (e - s).days + 1
    if span <= 1:
        return "day"
    if span == 7 and s.weekday() == 0:
        return "week"
    if s.year == e.year:
        if s.month == e.month and s.day == 1 and \
                e.day == calendar.monthrange(s.year, s.month)[1]:
            return "month"
        if s.month in (1, 4, 7, 10) and s.day == 1 and s.month + 2 == e.month and \
                e.day == calendar.monthrange(e.year, e.month)[1]:
            return "quarter"
        if (s.month, s.day, e.month, e.day) == (1, 1, 12, 31):
            return "year"
    return "unknown"


class Archive:
    """档案服务层：封装第 3 步全部录入与查询动作。"""

    def __init__(self, store):
        self.store = store
        self.model = store.model

    # ---- 内部工具 ---------------------------------------------------
    def _require(self, entity, rid):
        try:
            return self.store.get(entity, rid)
        except NotFound:
            raise ArchiveError("找不到 %s 记录：%s" % (entity, rid))

    @staticmethod
    def _clean(values):
        return {k: v for k, v in values.items() if v is not None}

    def _insert(self, entity, values, fragments=(), field_name=None, proposal_id=None,
                job_id=None, actor_type=None, remark=None, commit=True):
        """写一条记录，并把来源片段登记进 provenance_link。

        commit=False 时只落盘不提交，供上层把多次写入组合成一个事务
        （AI 建议确认时的写入与同批次回填必须同生共死）。
        """
        # 服务层代表用户手工录入；AI 提取写入会显式传 origin=ai_agent（第 4 步起）
        values.setdefault("origin", "user")
        if values.get("is_fact") in (0, False) and not values.get("fact_basis"):
            raise ArchiveError(
                "标记为推断（is_fact=false）时必须写明事实依据 fact_basis（数据规则 B6）")
        rid = self.store.insert(entity, self._clean(values), actor_type=actor_type,
                                proposal_id=proposal_id, job_id=job_id, remark=remark)
        self.link_fragments(entity, rid, fragments, field_name=field_name, commit=False)
        record = self.store.get(entity, rid)
        # 冗余字段 source_document_id：仅当来源片段同属一份资料时回填
        if fragments and "source_document_id" in self.model.fields(entity):
            docs = {self._fragment_doc(f)[1]["id"] for f in fragments}
            if len(docs) == 1 and not record.get("source_document_id"):
                self.store.update(entity, rid, {"source_document_id": docs.pop()})
                record = self.store.get(entity, rid)
        if commit:
            self.store.commit()
        return record

    # ---- 引用解析 ---------------------------------------------------
    def resolve(self, entity, value, fields=("name", "title", "code")):
        """把「id 或名称」解析成实体 id；名称查不到时报错，不静默新建。"""
        if not value:
            return None
        try:
            self.store.get(entity, value)
            return value
        except NotFound:
            pass
        for fname in fields:
            if fname not in self.model.fields(entity):
                continue
            row = self.store.find_one(entity, **{fname: value})
            if row:
                return row["id"]
        raise ArchiveError("找不到 %s：%s（可用 list 子命令查看已有记录）" % (entity, value))

    def ensure_domain(self, name):
        """工作领域是弱分类（取舍十二）：名称不存在时按需新建，不阻断录入。"""
        if not name:
            return None
        row = self.store.find_one("work_domain", name=name)
        if row:
            return row["id"]
        rid = self.store.insert("work_domain", {"name": name, "origin": "user"})
        self.store.commit()
        return rid

    def _fragment_doc(self, fragment_id):
        frag = self._require("source_fragment", fragment_id)
        doc = self._require("source_document", frag["document_id"])
        return frag, doc

    # ---- 来源追溯 ---------------------------------------------------
    def link_fragment(self, entity_type, entity_id, fragment_id,
                      relation_type="primary_source", field_name=None,
                      match_method="manual", origin="user", commit=True):
        """把实体（或它的某个字段）指回原始资料片段；重复关联不会产生第二条。"""
        self.model.entity(entity_type)
        self._require(entity_type, entity_id)
        frag, _doc = self._fragment_doc(fragment_id)
        existing = self.store.find_one(
            "provenance_link", entity_type=entity_type, entity_id=entity_id,
            fragment_id=fragment_id, relation_type=relation_type, field_name=field_name)
        if existing:
            return existing
        rid = self.store.insert("provenance_link", {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field_name": field_name,
            "fragment_id": fragment_id,
            "relation_type": relation_type,
            "quote_text": frag["text"],
            "match_method": match_method,
            "origin": origin,
        })
        if commit:
            self.store.commit()
        return self.store.get("provenance_link", rid)

    def link_fragments(self, entity_type, entity_id, fragment_ids, relation_type="primary_source",
                       field_name=None, commit=True):
        return [self.link_fragment(entity_type, entity_id, f, relation_type, field_name,
                                   commit=commit)
                for f in (fragment_ids or [])]

    def provenance(self, entity_type, entity_id):
        """某条档案记录的全部来源片段（含资料标题与原文）。"""
        rows = self.store.list("provenance_link",
                               {"entity_type": entity_type, "entity_id": entity_id},
                               limit=1000, order_by="created_at ASC")
        out = []
        for link in rows:
            frag = self.store.get("source_fragment", link["fragment_id"])
            doc = self.store.get("source_document", frag["document_id"])
            out.append({
                "link": link,
                "fragment_id": frag["id"],
                "fragment_type": frag["fragment_type"],
                "heading_path": frag["heading_path"],
                "text": frag["text"],
                "quote_text": link["quote_text"],
                "relation_type": link["relation_type"],
                "document_id": doc["id"],
                "document_title": doc["title"],
                "document_type": doc["doc_type"],
                "period_start": doc["period_start"],
                "period_end": doc["period_end"],
            })
        return out

    # ---- 录入：项目 / 系统 / 模块 ------------------------------------
    def create_project(self, name, fragments=(), **fields):
        fields["name"] = name
        return self._insert("project", fields, fragments)

    def create_system(self, name, fragments=(), **fields):
        fields["name"] = name
        return self._insert("business_system", fields, fragments)

    def create_module(self, name, system_id, parent_module_id=None, fragments=(), **fields):
        self._require("business_system", system_id)
        if parent_module_id:
            parent = self._require("function_module", parent_module_id)
            if parent["system_id"] != system_id:
                raise ArchiveError("父模块属于其他系统，功能模块不能跨系统挂载")
        fields.update({"name": name, "system_id": system_id})
        if parent_module_id:
            fields["parent_module_id"] = parent_module_id
        return self._insert("function_module", fields, fragments)

    # ---- 录入：工作事项 ---------------------------------------------
    def _resolve_item_time(self, occurred_at, date_precision, fragments, doc=None):
        if occurred_at:
            if date_precision:
                return occurred_at, date_precision
            if doc and doc.get("period_start") == occurred_at:
                return occurred_at, precision_from_period(doc["period_start"], doc["period_end"])
            return occurred_at, "day"
        if doc and (doc.get("period_start") or doc.get("source_created_at")):
            start = doc.get("period_start") or (doc.get("source_created_at") or "")[:10]
            return start, date_precision or precision_from_period(
                doc.get("period_start"), doc.get("period_end"))
        raise ArchiveError(
            "缺少事项时间：请用 --date 指定，或先用 --from 关联一份带期间的来源片段")

    def create_work_item(self, title, item_type, content, occurred_at=None,
                         date_precision=None, fragments=(), **fields):
        doc = self._fragment_doc(fragments[0])[1] if fragments else None
        occurred_str, precision = self._resolve_item_time(
            occurred_at, date_precision, fragments, doc)
        fields.update({
            "title": title, "item_type": item_type, "content": content,
            "occurred_at": occurred_str, "date_precision": precision,
        })
        for ref_field, entity in (("project_id", "project"), ("system_id", "business_system"),
                                  ("module_id", "function_module"), ("domain_id", "work_domain")):
            if fields.get(ref_field):
                self._require(entity, fields[ref_field])
        return self._insert("work_item", fields, fragments)

    # ---- 录入：持续工作主题 -----------------------------------------
    def create_theme(self, name, fragments=(), **fields):
        fields["name"] = name
        return self._insert("work_theme", fields, fragments)

    def add_theme_member(self, theme_id, member_type, member_id, relation_type="primary",
                         evidence_fragment_id=None, **fields):
        self._require("work_theme", theme_id)
        allowed = self.model.enum_values("theme_member_type")
        if member_type not in allowed:
            raise ArchiveError("主题成员类型只能是：%s" % "、".join(allowed))
        self._require(member_type, member_id)
        if evidence_fragment_id:
            self._require("source_fragment", evidence_fragment_id)
        existing = self.store.find_one("theme_member", theme_id=theme_id,
                                       member_type=member_type, member_id=member_id)
        if existing:
            return existing
        rid = self.store.insert("theme_member", self._clean({
            **fields,
            "theme_id": theme_id, "member_type": member_type, "member_id": member_id,
            "relation_type": relation_type, "evidence_fragment_id": evidence_fragment_id,
            "origin": fields.get("origin", "user"),
        }))
        self.refresh_theme_span(theme_id)
        self.store.commit()
        return self.store.get("theme_member", rid)

    def refresh_theme_span(self, theme_id):
        """主题的首次/最近出现时间由成员时间聚合，不手工填写。"""
        members = self.store.list("theme_member", {"theme_id": theme_id}, limit=100000)
        dates = []
        for m in members:
            if m["member_type"] == "work_item":
                item = self.store.get("work_item", m["member_id"])
                dates.append(item["occurred_at"])
            elif m["member_type"] == "achievement_case":
                case = self.store.get("achievement_case", m["member_id"])
                if case.get("occurred_at"):
                    dates.append(case["occurred_at"])
            else:
                doc = self.store.get("source_document", m["member_id"])
                if doc.get("period_start"):
                    dates.append(doc["period_start"])
        if not dates:
            return None
        return self.store.update("work_theme", theme_id,
                                 {"first_seen_at": min(dates), "last_seen_at": max(dates)})

    # ---- 录入：职责与贡献 -------------------------------------------
    def create_role_record(self, target_type, target_id, role, start_date, **fields):
        target = self._require(target_type, target_id)
        fields.update({"target_type": target_type, "target_id": target_id,
                       "role": role, "start_date": start_date})
        fields.setdefault("target_label", target.get("name") or target.get("title"))
        return self._insert("role_record", fields)

    # ---- 归并（同名重复建档）----------------------------------------
    def _referencing_fields(self, entity):
        """模型里所有指向该实体的字段，用于归并时转移引用。"""
        out = []
        for other in self.model.entities:
            for fname, spec in self.model.fields(other).items():
                if spec.get("ref") == entity:
                    out.append((other, fname, None, None))
        for other, type_field, id_field in POLYMORPHIC_REFS:
            out.append((other, id_field, type_field, entity))
        return out

    def _unique_with(self, entity, field_name):
        return any(field_name in ut for ut in (self.model.entity(entity).get("unique_together") or []))

    def _move_rows(self, other, field, ref_id, new_id, type_field, type_value, report):
        where = {field: ref_id}
        if type_field:
            where[type_field] = type_value
        for row in self.store.list(other, where, limit=100000):
            try:
                self.store.update(other, row["id"], {field: new_id})
                report["repointed"].append("%s.%s=%s" % (other, field, row["id"]))
            except sqlite3.IntegrityError:
                if not self._unique_with(other, field):
                    raise ArchiveError(
                        "合并中止：%s 的引用 %s 无法转移（%s）" % (other, row["id"], field))
                # 关联表上的重复关联：并过去会撞唯一约束，视为重复关联丢弃
                self.store.soft_delete(other, row["id"],
                                       remark="归并去重：%s → %s" % (ref_id, new_id))
                report["dropped_links"].append("%s.%s=%s" % (other, field, row["id"]))

    def merge_records(self, entity, keep_id, drop_ids, note=None, commit=True):
        """把重复记录并入保留记录：转移引用 → 记血缘 → 软删除重复项。

        返回处理报告；中途出错回滚，不留半成品。
        """
        keep = self._require(entity, keep_id)
        drop_ids = [d for d in drop_ids if d and d != keep_id]
        if not drop_ids:
            raise ArchiveError("请给出要并入的重复记录 id（不能与保留记录相同）")
        report = {"entity": entity, "kept": keep_id, "merged": [],
                  "repointed": [], "dropped_links": []}
        fields = self.model.fields(entity)
        try:
            for drop_id in drop_ids:
                self._require(entity, drop_id)
                for other, field, type_field, type_value in self._referencing_fields(entity):
                    self._move_rows(other, field, drop_id, keep_id,
                                    type_field, type_value, report)
                self.store.insert("entity_relation", {
                    "from_type": entity, "from_id": drop_id,
                    "to_type": entity, "to_id": keep_id,
                    "relation_type": "merged_into",
                    "basis_text": note or "同名/重复记录归并",
                    "origin": "user",
                })
                self.store.soft_delete(entity, drop_id, remark="归并到 %s" % keep_id)
                report["merged"].append(drop_id)

            patch = {}
            if "merged_from_ids" in fields:
                patch["merged_from_ids"] = list(keep.get("merged_from_ids") or []) + drop_ids
            if note and "consolidation_note" in fields:
                patch["consolidation_note"] = note
            if patch:
                self.store.update(entity, keep_id, patch)
            self.store.log_action(entity, keep_id, "merge",
                                  before={"merged_from_ids": keep.get("merged_from_ids")},
                                  after=patch, remark=note)
            if commit:
                self.store.commit()
        except Exception:
            self.store.rollback()
            raise
        return report

    # ---- 查询 -------------------------------------------------------
    def module_tree(self, system_id):
        modules = self.store.list("function_module", {"system_id": system_id},
                                  limit=100000, order_by="name ASC")
        by_id = {m["id"]: dict(m, children=[]) for m in modules}
        roots = []
        for m in by_id.values():
            parent = by_id.get(m.get("parent_module_id"))
            (parent["children"] if parent else roots).append(m)
        return roots

    def timeline(self, limit=20, project_id=None, system_id=None, since=None):
        where = {}
        if project_id:
            where["project_id"] = project_id
        if system_id:
            where["system_id"] = system_id
        rows = self.store.list("work_item", where or None, limit=100000,
                               order_by="occurred_at DESC, id DESC")
        if since:
            rows = [r for r in rows if r["occurred_at"] >= since]
        out = []
        for item in rows[:limit]:
            out.append({
                "id": item["id"], "title": item["title"], "item_type": item["item_type"],
                "occurred_at": item["occurred_at"], "date_precision": item["date_precision"],
                "my_role": item["my_role"], "is_routine": item["is_routine"],
                "project": self._label("project", item.get("project_id")),
                "system": self._label("business_system", item.get("system_id")),
                "review_status": item["review_status"],
            })
        return out

    def _label(self, entity, rid):
        if not rid:
            return None
        try:
            row = self.store.get(entity, rid)
        except NotFound:
            return None
        return row.get("name") or row.get("title")

    def theme_timeline(self, theme_id):
        """主题下的完整时间线 + 来源资料（需求：查看主题下的工作时间线与原始资料）。"""
        theme = self._require("work_theme", theme_id)
        members = self.store.list("theme_member", {"theme_id": theme_id}, limit=100000)
        items, cases, docs = [], [], []
        for m in members:
            if m["member_type"] == "work_item":
                items.append(dict(self.store.get("work_item", m["member_id"]),
                                  relation_type=m["relation_type"]))
            elif m["member_type"] == "achievement_case":
                cases.append(dict(self.store.get("achievement_case", m["member_id"]),
                                  relation_type=m["relation_type"]))
            else:
                docs.append(dict(self.store.get("source_document", m["member_id"]),
                                 relation_type=m["relation_type"]))
        items.sort(key=lambda x: x["occurred_at"])
        return {"theme": theme, "items": items, "cases": cases, "documents": docs}

    def domain_distribution(self):
        rows = self.store.query(
            "SELECT d.name AS domain, COUNT(i.id) AS items "
            "FROM work_item i LEFT JOIN work_domain d ON d.id = i.domain_id "
            "WHERE i.deleted_at IS NULL GROUP BY d.name ORDER BY items DESC")
        return rows

    def overview(self):
        """成长总览的最小实现：数量、代表项目、近期事项、待审核建议。"""
        items = self.store.list("work_item", limit=100000, order_by="occurred_at DESC")
        return {
            "counts": {
                "project": self.store.count("project"),
                "business_system": self.store.count("business_system"),
                "function_module": self.store.count("function_module"),
                "work_item": self.store.count("work_item"),
                "work_theme": self.store.count("work_theme"),
                "role_record": self.store.count("role_record"),
                "source_document": self.store.count("source_document"),
                "source_fragment": self.store.count("source_fragment"),
            },
            "representative_projects": [
                {"id": p["id"], "name": p["name"], "project_type": p["project_type"],
                 "status": p["status"], "my_role": p["my_role"]}
                for p in self.store.list("project", {"is_representative": 1}, limit=20,
                                         order_by="importance_level DESC, start_date DESC")
            ],
            "recent_items": self.timeline(limit=8),
            "domains": self.domain_distribution(),
            "pending_reviews": self.store.count("change_proposal", {"status": "pending"}),
            "item_span": {
                "first": items[-1]["occurred_at"] if items else None,
                "last": items[0]["occurred_at"] if items else None,
            },
        }

    def trace(self, entity, rid):
        """一条档案记录的全部依据：来源片段 + 实体关联 + 变更历史。"""
        record = self._require(entity, rid)
        relations = []
        for rel in self.store.list("entity_relation", {"from_type": entity, "from_id": rid},
                                   limit=1000) :
            relations.append({"direction": "out", "relation_type": rel["relation_type"],
                              "other_type": rel["to_type"], "other_id": rel["to_id"],
                              "other_label": self._label(rel["to_type"], rel["to_id"])})
        for rel in self.store.list("entity_relation", {"to_type": entity, "to_id": rid},
                                   limit=1000):
            relations.append({"direction": "in", "relation_type": rel["relation_type"],
                              "other_type": rel["from_type"], "other_id": rel["from_id"],
                              "other_label": self._label(rel["from_type"], rel["from_id"])})
        return {
            "entity": entity,
            "record": record,
            "provenance": self.provenance(entity, rid),
            "relations": relations,
            "history": self.store.history(entity, rid),
        }
