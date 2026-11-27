# -*- coding: utf-8 -*-
"""项目整理、项目介绍与成长口径的离线自检。

覆盖：规则稿只用现存事实、模型失败回落、合并保留血缘与别名、
成长接口按月统计并区分原文/推断证据。

运行：python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm import LLMError
from app.projects import ProjectCurator, clean_intro
from app.store import Store
from app.web import Api


class FailingLLM:
    config = None

    def chat(self, *args, **kwargs):
        raise LLMError("网关不可用", code="http_error")


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-test7-")
        self.db = os.path.join(self.tmp, "growth.db")
        Store.init(self.db)
        self.store = Store(self.db)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_project(self, name, **extra):
        row = {"name": name, "origin": "user", "is_fact": 1, "review_status": "confirmed"}
        row.update(extra)
        project_id = self.store.insert("project", row)
        self.store.commit()
        return project_id

    def add_item(self, title, project_id=None, occurred_at="2026-05-10",
                 is_routine=0, review_status="confirmed"):
        row = {
            "title": title, "item_type": "requirement_analysis", "content": "",
            "is_routine": is_routine, "occurred_at": occurred_at, "date_precision": "day",
            "is_follow_up_needed": 0, "origin": "user",
            "review_status": review_status, "is_fact": 1,
        }
        if project_id:
            row["project_id"] = project_id
        item_id = self.store.insert("work_item", row)
        self.store.commit()
        return item_id


class TestDraft(BaseCase):
    def test_draft_uses_only_json_facts(self):
        project_id = self.add_project("Aether 平台")
        self.add_item("完成真人素材认证", project_id, "2026-03-02")
        self.add_item("局部重绘调研", project_id, "2026-04-11")
        text = ProjectCurator(self.store).draft(self.store.get("project", project_id))
        self.assertIn("Aether 平台", text)
        self.assertIn("2026-03-02", text)
        self.assertIn("完成真人素材认证", text)

    def test_no_items_means_empty_draft(self):
        project_id = self.add_project("空项目")
        self.assertEqual("", ProjectCurator(self.store).draft(self.store.get("project", project_id)))


class TestGenerate(BaseCase):
    def test_falls_back_to_draft_when_model_fails(self):
        project_id = self.add_project("DMM SDK 安全修复")
        self.add_item("整理安全修复文档", project_id)
        curator = ProjectCurator(self.store, llm=FailingLLM())
        text = curator.generate(self.store.get("project", project_id))
        self.assertIn("DMM SDK 安全修复", text)
        self.assertIn("整理安全修复文档", text)

    def test_fabricated_numbers_fall_back_to_draft(self):
        project_id = self.add_project("预注册看板")
        self.add_item("补全 PRD 与原型", project_id)
        from app.projects import has_fabricated_numbers
        self.assertTrue(has_fabricated_numbers("进度 70%，下周上线。"))
        self.assertFalse(has_fabricated_numbers("2026-08-01 完成评审。"))

    def test_clean_intro_drops_model_meta_talk(self):
        raw = "这个项目是Aether 平台。已有成果描述未给出，做到的程度是部分上线。我负责需求梳理与验收。"
        text = clean_intro(raw, "Aether 平台")
        self.assertFalse(text.startswith("这个项目是"))
        self.assertNotIn("未给出", text)
        self.assertIn("需求梳理", text)


class TestMerge(BaseCase):
    def test_merge_moves_items_and_keeps_bloodline(self):
        keep_id = self.add_project("Aether 平台")
        drop_id = self.add_project("Aether局部重绘")
        item_id = self.add_item("局部重绘调研", drop_id)
        report = ProjectCurator(self.store).merge("Aether 平台", ["Aether局部重绘"],
                                                  note="功能不是项目")
        self.assertEqual([drop_id], report["merged"])
        item = self.store.get("work_item", item_id)
        self.assertEqual(keep_id, item["project_id"])
        keep = self.store.get("project", keep_id)
        self.assertIn("Aether局部重绘", keep["alias_names"])
        self.assertIn(drop_id, keep["merged_from_ids"])
        dropped = self.store.list("project", {"id": drop_id}, include_deleted=True, limit=1)[0]
        self.assertIsNotNone(dropped.get("deleted_at"))


class TestGrowth(BaseCase):
    def test_growth_counts_fact_and_inferred(self):
        project_id = self.add_project("Aether 平台")
        item_id = self.add_item("完成验收", project_id, "2026-05-10")
        category_id = self.store.insert("capability_category", {
            "name": "交付与质量", "origin": "system", "review_status": "confirmed",
        })
        cap_id = self.store.insert("capability", {
            "code": "DQ2", "name": "质量与验收", "definition": "定义验收标准",
            "category_id": category_id, "origin": "system",
            "review_status": "confirmed", "status": "active",
        })
        for occurred_at, is_fact in (("2026-05-10", 1), ("2026-05-12", 0)):
            self.store.insert("capability_evidence", {
                "capability_id": cap_id, "evidence_type": "performance",
                "target_type": "work_item", "target_id": item_id,
                "statement": "完成验收", "occurred_at": occurred_at, "strength": 3,
                "is_fact": is_fact, "origin": "user", "review_status": "confirmed",
            })
        self.store.commit()
        api = Api(self.db)
        data = api.growth(months=12)
        may = [m for m in data["months"] if m["month"] == "2026-05"][0]
        self.assertEqual(1, may["fact"])
        self.assertEqual(1, may["inferred"])
        self.assertEqual(2, data["totals"]["evidence"])
        self.assertEqual(1, data["totals"]["capabilities"])
        api.store.close()


if __name__ == "__main__":
    unittest.main()
