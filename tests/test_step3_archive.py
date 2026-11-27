# -*- coding: utf-8 -*-
"""第 3 步（项目 / 系统 / 模块 / 事项 / 主题 / 职责）的自检用例。

运行：python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.archive import Archive, ArchiveError, precision_from_period
from app.importers import import_file
from app.model_meta import ModelError, ValidationError
from app.store import Conflict, NotFound, Store

WEEKLY = """# 2024年第12周 工作周报

## 一、本周工作

- 完成客户数据平台指标口径梳理，覆盖 12 个核心指标
- 修复数据质量校验规则 2 处误报
"""


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-test3-")
        self.db = os.path.join(self.tmp, "growth.db")
        Store.init(self.db)
        self.store = Store(self.db)
        self.arc = Archive(self.store)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(text)
        return path

    def import_weekly(self):
        """导入一份周报，返回 (document, fragments)。"""
        result = import_file(self.store, self.write("2024年第12周周报.md", WEEKLY))
        self.store.commit()
        doc = self.store.get("source_document", result["document_id"])
        frags = self.store.list("source_fragment", {"document_id": doc["id"]}, limit=99,
                                order_by="order_index ASC")
        return doc, frags


class TestPrecision(BaseCase):
    def test_precision_from_period(self):
        self.assertEqual(precision_from_period("2024-03-18", "2024-03-18"), "day")
        self.assertEqual(precision_from_period("2024-03-18", "2024-03-24"), "week")
        self.assertEqual(precision_from_period("2024-03-01", "2024-03-31"), "month")
        self.assertEqual(precision_from_period("2024-01-01", "2024-03-31"), "quarter")
        self.assertEqual(precision_from_period("2024-01-01", "2024-12-31"), "year")
        self.assertEqual(precision_from_period("2024-03-05", "2024-03-20"), "unknown")
        self.assertEqual(precision_from_period(None, None), "unknown")


class TestProjectAndSource(BaseCase):
    def test_create_project_with_fragments(self):
        doc, frags = self.import_weekly()
        row = self.arc.create_project("客户数据平台建设", fragments=[frags[0]["id"]],
                                      project_type="new_build", my_role="lead",
                                      start_date="2024-01-08", importance_level=5,
                                      is_representative=True)
        self.assertEqual(row["name"], "客户数据平台建设")
        self.assertEqual(row["origin"], "user")
        self.assertEqual(row["review_status"], "confirmed")
        self.assertEqual(row["is_fact"], 1)

        prov = self.store.list("provenance_link", {"entity_type": "project",
                                                   "entity_id": row["id"]}, limit=10)
        self.assertEqual(len(prov), 1)
        self.assertEqual(prov[0]["fragment_id"], frags[0]["id"])
        self.assertEqual(prov[0]["quote_text"], frags[0]["text"])
        # 来源追溯能反查到资料标题
        traced = self.arc.provenance("project", row["id"])
        self.assertEqual(traced[0]["document_title"], doc["title"])

    def test_link_fragment_is_idempotent(self):
        _doc, frags = self.import_weekly()
        row = self.arc.create_project("客户数据平台建设", fragments=[frags[0]["id"]])
        again = self.arc.link_fragment("project", row["id"], frags[0]["id"])
        rows = self.store.list("provenance_link", {"entity_id": row["id"]}, limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(again["id"], rows[0]["id"])

    def test_alias_roundtrip(self):
        row = self.arc.create_project("客户数据平台建设", alias_names='["指标平台", "CDP"]')
        self.assertEqual(row["alias_names"], '["指标平台", "CDP"]')

    def test_unknown_field_rejected(self):
        with self.assertRaises(ModelError):
            self.arc.create_project("客户数据平台建设", not_a_field="x")

    def test_inference_needs_basis(self):
        with self.assertRaises(ArchiveError):
            self.arc.create_project("客户数据平台建设", is_fact=0)
        row = self.arc.create_project("客户数据平台建设", is_fact=0,
                                      fact_basis="根据两份周报的措辞归纳，未在原文直接出现")
        self.assertEqual(row["is_fact"], 0)

    def test_resolve_by_name_and_missing(self):
        row = self.arc.create_project("客户数据平台建设")
        self.assertEqual(self.arc.resolve("project", "客户数据平台建设"), row["id"])
        self.assertEqual(self.arc.resolve("project", row["id"]), row["id"])
        with self.assertRaises(ArchiveError):
            self.arc.resolve("project", "不存在的项目")

    def test_immutable_field_rejected(self):
        _doc, frags = self.import_weekly()
        row = self.arc.create_project("客户数据平台建设", fragments=[frags[0]["id"]])
        prov = self.store.list("provenance_link", {"entity_id": row["id"]}, limit=1)[0]
        with self.assertRaises(ModelError):
            self.store.update("provenance_link", prov["id"], {"quote_text": "改过的原文"})

    def test_optimistic_lock(self):
        row = self.arc.create_project("客户数据平台建设")
        with self.assertRaises(Conflict):
            self.store.update("project", row["id"], {"goal": "新目标"}, expected_revision=99)


class TestModuleTree(BaseCase):
    def test_module_requires_same_system(self):
        system = self.arc.create_system("客户数据平台", system_type="platform")
        parent = self.arc.create_module("指标管理", system["id"], module_type="core")
        child = self.arc.create_module("口径定义", system["id"], parent_module_id=parent["id"],
                                       module_type="business")
        tree = self.arc.module_tree(system["id"])
        self.assertEqual(tree[0]["id"], parent["id"])
        self.assertEqual(tree[0]["children"][0]["id"], child["id"])

        other = self.arc.create_system("其他系统", system_type="tool")
        with self.assertRaises(ArchiveError):
            self.arc.create_module("跨系统子模块", other["id"], parent_module_id=parent["id"])


class TestWorkItem(BaseCase):
    def test_time_inferred_from_weekly_source(self):
        doc, frags = self.import_weekly()
        item = self.arc.create_work_item("完成指标口径梳理", "requirement_analysis",
                                         frags[0]["text"], fragments=[frags[0]["id"]])
        self.assertEqual(item["occurred_at"], doc["period_start"])
        self.assertEqual(item["date_precision"], "week")
        self.assertEqual(item["source_document_id"], doc["id"])
        self.assertEqual(item["content"], frags[0]["text"])

    def test_time_required_when_source_has_no_period(self):
        path = self.write("随手记.md", "这是一段没有时间的记录。\n")
        result = import_file(self.store, path, doc_type="personal_note")
        self.store.commit()
        frag = self.store.list("source_fragment", {"document_id": result["document_id"]},
                               limit=1)[0]
        with self.assertRaises(ArchiveError):
            self.arc.create_work_item("临时记录", "other", "内容", fragments=[frag["id"]])

    def test_explicit_date_and_precision(self):
        item = self.arc.create_work_item("复盘平台建设经验", "review", "内容",
                                         occurred_at="2024-04-02", date_precision="day")
        self.assertEqual(item["occurred_at"], "2024-04-02")
        self.assertEqual(item["date_precision"], "day")

    def test_complexity_range_checked(self):
        with self.assertRaises(ValidationError):
            self.arc.create_work_item("越界事项", "other", "内容",
                                      occurred_at="2024-04-02", complexity_level=9)


class TestTheme(BaseCase):
    def test_theme_span_from_members(self):
        theme = self.arc.create_theme("客户数据平台建设", theme_type="system_building")
        self.assertIsNone(theme["first_seen_at"])
        early = self.arc.create_work_item("2 月梳理口径", "coordination", "内容",
                                          occurred_at="2024-02-20", date_precision="day")
        late = self.arc.create_work_item("4 月复盘", "review", "内容",
                                         occurred_at="2024-04-02", date_precision="day")
        self.arc.add_theme_member(theme["id"], "work_item", early["id"],
                                  match_reason="同一主题的连续工作")
        self.arc.add_theme_member(theme["id"], "work_item", late["id"],
                                  match_reason="同一主题的连续工作")
        refreshed = self.store.get("work_theme", theme["id"])
        self.assertEqual(refreshed["first_seen_at"], "2024-02-20")
        self.assertEqual(refreshed["last_seen_at"], "2024-04-02")

        data = self.arc.theme_timeline(theme["id"])
        self.assertEqual([i["title"] for i in data["items"]], ["2 月梳理口径", "4 月复盘"])

    def test_member_idempotent(self):
        theme = self.arc.create_theme("客户数据平台建设", theme_type="system_building")
        item = self.arc.create_work_item("事项", "other", "内容",
                                         occurred_at="2024-04-02", date_precision="day")
        self.arc.add_theme_member(theme["id"], "work_item", item["id"])
        self.arc.add_theme_member(theme["id"], "work_item", item["id"])
        self.assertEqual(self.store.count("theme_member", {"theme_id": theme["id"]}), 1)

    def test_member_type_checked(self):
        theme = self.arc.create_theme("主题", theme_type="other")
        with self.assertRaises(ArchiveError):
            self.arc.add_theme_member(theme["id"], "unknown_type", theme["id"])
        with self.assertRaises(ArchiveError):
            self.arc.add_theme_member(theme["id"], "work_item", "不存在的ID")


class TestRoleRecord(BaseCase):
    def test_target_label_snapshot(self):
        project = self.arc.create_project("客户数据平台建设", project_type="new_build")
        role = self.arc.create_role_record("project", project["id"], "lead", "2024-01-08",
                                           is_ongoing=True, responsibility_scope="指标口径模块")
        self.assertEqual(role["target_label"], "客户数据平台建设")
        self.assertEqual(role["date_precision"], "month")


class TestMerge(BaseCase):
    def test_merge_moves_references_and_keeps_history(self):
        keep = self.arc.create_project("客户数据平台建设", project_type="new_build")
        dup = self.arc.create_project("客户数据平台", project_type="enhancement")
        item = self.arc.create_work_item("梳理指标口径争议", "coordination", "内容",
                                         occurred_at="2024-02-20", date_precision="day",
                                         project_id=dup["id"])
        _doc, frags = self.import_weekly()
        self.arc.link_fragment("project", dup["id"], frags[0]["id"])

        report = self.arc.merge_records("project", keep["id"], [dup["id"]],
                                        note="同一项目的两种叫法")
        self.assertEqual(report["merged"], [dup["id"]])
        self.assertIn("work_item.project_id=%s" % item["id"], report["repointed"])

        self.assertEqual(self.store.get("work_item", item["id"])["project_id"], keep["id"])
        with self.assertRaises(NotFound):
            self.store.get("project", dup["id"])
        self.assertEqual(self.store.get("project", dup["id"], include_deleted=True)["deleted_at"]
                         is not None, True)

        kept = self.store.get("project", keep["id"])
        self.assertEqual(kept["merged_from_ids"], '["%s"]' % dup["id"])
        relations = self.store.list("entity_relation", {"from_id": dup["id"]}, limit=10)
        self.assertEqual(relations[0]["relation_type"], "merged_into")
        self.assertEqual(relations[0]["to_id"], keep["id"])

        # 归并后来源仍可追溯，且条目数没有减少
        prov = self.arc.provenance("project", keep["id"])
        self.assertEqual(len(prov), 1)
        history = self.store.history("project", keep["id"])
        self.assertTrue(any(h["action"] == "merge" for h in history))

    def test_merge_requires_existing_records(self):
        keep = self.arc.create_project("客户数据平台建设")
        with self.assertRaises(ArchiveError):
            self.arc.merge_records("project", keep["id"], ["不存在的ID"])


class TestOverview(BaseCase):
    def test_overview_counts(self):
        _doc, frags = self.import_weekly()
        project = self.arc.create_project("客户数据平台建设", project_type="new_build",
                                          my_role="lead", is_representative=True,
                                          fragments=[frags[0]["id"]])
        self.arc.create_work_item("完成指标口径梳理", "requirement_analysis", "内容",
                                  occurred_at="2024-03-18", date_precision="week",
                                  project_id=project["id"])
        data = self.arc.overview()
        self.assertEqual(data["counts"]["project"], 1)
        self.assertEqual(data["counts"]["work_item"], 1)
        self.assertEqual(data["counts"]["source_fragment"], 4)  # 2 个标题 + 2 个列表项
        self.assertEqual(data["representative_projects"][0]["name"], "客户数据平台建设")
        self.assertEqual(data["item_span"]["first"], "2024-03-18")

    def test_trace_returns_everything(self):
        _doc, frags = self.import_weekly()
        project = self.arc.create_project("客户数据平台建设", fragments=[frags[0]["id"]])
        data = self.arc.trace("project", project["id"])
        self.assertEqual(data["record"]["name"], "客户数据平台建设")
        self.assertEqual(len(data["provenance"]), 1)
        self.assertTrue(data["history"])


if __name__ == "__main__":
    unittest.main()
