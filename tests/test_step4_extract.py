# -*- coding: utf-8 -*-
"""第 4 步（AI 提取、匹配、归并、审核）的离线自检用例。

不联网：用假 transport 顶替模型网关，验证提示词组装、输出解析、建议落库、
确认/拒绝流程与审计留痕。

运行：python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.archive import Archive
from app.extract import ExtractError, Extraction, Review, parse_json_reply, render_prompt
from app.importers import import_file
from app.llm import LLMClient, LLMError, resolve_config
from app.model_meta import ModelError
from app.store import Store

WEEKLY = """# 2024年第12周 工作周报

## 一、本周工作

- 完成客户数据平台指标口径梳理，覆盖 12 个核心指标
- 与业务方确认 3 个争议口径
"""


class FakeTransport:
    """按顺序返回预置回复；元素是 dict 时序列化成 JSON 文本，是异常时抛出。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append(payload)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return {
            "model": "fake-model-1",
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180},
        }


def fake_llm(*replies):
    transport = FakeTransport(replies)
    config = resolve_config(model="fake-model", api_key="test-key",
                            base_url="http://fake.local/v1", provider="fake")
    return LLMClient(config=config, transport=transport), transport


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-test4-")
        self.db = os.path.join(self.tmp, "growth.db")
        Store.init(self.db)
        self.store = Store(self.db)
        self.arc = Archive(self.store)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def import_weekly(self):
        path = os.path.join(self.tmp, "2024年第12周周报.md")
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(WEEKLY)
        result = import_file(self.store, path)
        self.store.commit()
        doc = self.store.get("source_document", result["document_id"])
        frags = self.store.list("source_fragment", {"document_id": doc["id"]}, limit=99,
                                order_by="order_index ASC")
        return doc, frags

    def seed_prompts(self, llm=None):
        extraction = Extraction(self.store, llm=llm)
        extraction.seed_config()
        return extraction


class TestPromptHelpers(unittest.TestCase):
    def test_render_prompt_keeps_literal_json_braces(self):
        text = render_prompt('{"a": 1, "b": "{value}"}', {"value": "x"})
        self.assertEqual(text, '{"a": 1, "b": "x"}')

    def test_render_prompt_reports_missing_variable(self):
        with self.assertRaises(ExtractError):
            render_prompt("hello {missing_one}", {})

    def test_parse_json_reply_variants(self):
        self.assertEqual(parse_json_reply('{"items": []}'), {"items": []})
        self.assertEqual(parse_json_reply('```json\n{"items": []}\n```'), {"items": []})
        self.assertEqual(parse_json_reply('好的，结果如下：\n{"items": [1]}\n以上'),
                         {"items": [1]})
        with self.assertRaises(LLMError) as ctx:
            parse_json_reply("没有 JSON")
        self.assertEqual(ctx.exception.code, "parse_failed")


class TestExtraction(BaseCase):
    def setUp(self):
        super().setUp()
        self.doc, self.frags = self.import_weekly()
        # 已有档案：一个同名项目、一个系统
        self.project = self.store.insert("project", {"name": "客户数据平台建设",
                                                     "origin": "user", "status": "active"})
        self.system = self.store.insert("business_system", {"name": "客户数据平台",
                                                            "origin": "user"})
        self.store.commit()
        self.f1 = self.frags[1]["id"]
        self.f2 = self.frags[3]["id"]

    def reply(self, **overrides):
        data = {
            "items": [
                {"title": "整理指标口径", "item_type": "requirement_analysis",
                 "content": "覆盖 12 个核心指标", "date_precision": "week",
                 "project": "客户数据平台建设", "system": "客户数据平台",
                 "my_role": "lead", "is_fact": True,
                 "deliverables": "指标定义模板；12 个核心指标定义",
                 "evidence": [{"fragment_id": self.f1,
                               "quote": "完成客户数据平台指标口径梳理，覆盖 12 个核心指标"}]},
                {"title": "新建项目下的事项", "item_type": "development",
                 "content": "为新建项目做的事情", "occurred_at": "2024-05-06",
                 "date_precision": "day", "project": "新建项目A",
                 "evidence": [{"fragment_id": self.f2, "quote": "与业务方确认 3 个争议口径"}]},
            ],
            "new_projects": [{"name": "新建项目A", "project_type": "new_build",
                              "status": "active",
                              "evidence": [{"fragment_id": self.f2,
                                            "quote": "与业务方确认 3 个争议口径"}]}],
            "link_existing": [{"entity": "business_system", "name": "客户数据平台",
                               "reason": "本资料就是它的建设记录",
                               "evidence": [{"fragment_id": self.f1,
                                             "quote": "完成客户数据平台指标口径梳理，覆盖 12 个核心指标"}]}],
            "notes": "示例说明",
        }
        data.update(overrides)
        return data

    def run_extract(self, reply=None):
        llm, transport = fake_llm(reply if reply is not None else self.reply())
        extraction = self.seed_prompts(llm)
        result = extraction.run(self.doc["id"], max_tokens=2048)
        return extraction, result, transport

    # ---- 提取 -------------------------------------------------------
    def test_run_creates_proposals_and_job(self):
        extraction, result, transport = self.run_extract()
        self.assertEqual(result["proposal_count"], 4)     # 2 事项 + 1 新项目 + 1 补来源
        job = extraction.job(result["job_id"])
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["proposal_count"], 4)
        self.assertEqual(job["input_fragment_count"], len(self.frags))
        self.assertTrue(json.loads(job["token_usage"])["total"] == 180)
        self.assertEqual(job["model_name"], "fake-model")
        # 送进模型的提示词里包含资料标题与片段 id
        prompt = json.dumps(transport.calls[0], ensure_ascii=False)
        self.assertIn(self.doc["title"], prompt)
        self.assertIn(self.f1, prompt)

    def test_existing_project_is_reused_not_duplicated(self):
        extraction, result, _ = self.run_extract()
        proposals = {self.store.get("change_proposal", pid)["diff_summary"]: pid
                     for pid in result["proposal_ids"]}
        payloads = [Review(self.store, extraction=extraction).show(pid)["payload"]
                    for pid in result["proposal_ids"]]
        item = [p for p in payloads if p.get("title") == "整理指标口径"][0]
        self.assertEqual(item["project_id"], self.project)
        self.assertEqual(item["system_id"], self.system)
        self.assertEqual(self.store.count("project"), 1)   # 没有重复建项目

    def test_json_string_field_is_coerced_to_array(self):
        extraction, result, _ = self.run_extract()
        review = Review(self.store, extraction=extraction)
        item = [review.show(pid)["payload"] for pid in result["proposal_ids"]
                if review.show(pid)["payload"].get("title") == "整理指标口径"][0]
        self.assertEqual(item["deliverables"], ["指标定义模板", "12 个核心指标定义"])

    def test_link_existing_creates_link_proposal(self):
        extraction, result, _ = self.run_extract()
        review = Review(self.store, extraction=extraction)
        links = [review.show(pid) for pid in result["proposal_ids"]
                 if review.show(pid)["proposal"]["change_type"] == "link"]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["proposal"]["target_entity_type"], "business_system")
        self.assertEqual(links[0]["proposal"]["target_entity_id"], self.system)
        self.assertEqual(links[0]["payload"]["fragment_ids"], [self.f1])
        self.assertTrue(links[0]["evidences"])

    def test_same_batch_project_is_relinked_after_confirm(self):
        extraction, result, _ = self.run_extract()
        review = Review(self.store, extraction=extraction)
        project_proposal = next(pid for pid in result["proposal_ids"]
                                if review.show(pid)["proposal"]["target_entity_type"] == "project"
                                and review.show(pid)["proposal"]["change_type"] == "create")
        item_proposal = next(pid for pid in result["proposal_ids"]
                             if review.show(pid)["payload"].get("title") == "新建项目下的事项")
        # 确认前：事项建议里还没有外键，理由里带着「待关联」标记
        before = self.store.get("change_proposal", item_proposal)
        self.assertIn("待关联 project:新建项目A", before["reason"])
        outcome = review.confirm(project_proposal)
        after = self.store.get("change_proposal", item_proposal)
        payload = json.loads(after["proposed_payload"])
        self.assertEqual(payload["project_id"], outcome["applied_entity_id"])
        self.assertIn("已关联 project:新建项目A", after["reason"])
        self.assertEqual(outcome["relinked"], [item_proposal])

    def test_job_marked_failed_when_model_errors(self):
        llm, _ = fake_llm(LLMError("被限流", code="rate_limited"))
        extraction = self.seed_prompts(llm)
        with self.assertRaises(ExtractError):
            extraction.run(self.doc["id"])
        jobs = extraction.jobs()
        self.assertEqual(jobs[0]["status"], "failed")
        self.assertEqual(jobs[0]["error_code"], "rate_limited")
        self.assertEqual(self.store.count("change_proposal"), 0)

    def test_job_marked_failed_when_reply_is_not_json(self):
        llm, _ = fake_llm("这不是 JSON")
        extraction = self.seed_prompts(llm)
        with self.assertRaises(ExtractError):
            extraction.run(self.doc["id"])
        self.assertEqual(extraction.jobs()[0]["error_code"], "parse_failed")

    def test_missing_template_is_reported(self):
        extraction = Extraction(self.store, llm=fake_llm({})[0])
        with self.assertRaises(ExtractError) as ctx:
            extraction.run(self.doc["id"])
        self.assertIn("ai seed", str(ctx.exception))

    def test_dry_run_does_not_write_anything(self):
        extraction = self.seed_prompts(fake_llm(self.reply())[0])
        result = extraction.run(self.doc["id"], dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.store.count("ai_job"), 0)
        self.assertEqual(self.store.count("change_proposal"), 0)

    # ---- 审核 -------------------------------------------------------
    def test_confirm_create_writes_archive_with_audit(self):
        extraction, result, _ = self.run_extract()
        review = Review(self.store, extraction=extraction)
        item_proposal = next(pid for pid in result["proposal_ids"]
                             if review.show(pid)["payload"].get("title") == "整理指标口径")
        # 模型没给 occurred_at：引擎按资料期间（2024-03-18~24，week）预填，理由里写明出处
        proposal = self.store.get("change_proposal", item_proposal)
        payload = json.loads(proposal["proposed_payload"])
        self.assertEqual(payload["occurred_at"], "2024-03-18")
        self.assertEqual(payload["date_precision"], "week")
        self.assertIn("时间取自资料期间", proposal["reason"])
        outcome = review.confirm(item_proposal, note="人工核对过")
        self.assertEqual(outcome["status"], "confirmed")
        item = self.store.get("work_item", outcome["applied_entity_id"])
        self.assertEqual(item["origin"], "ai_agent")
        self.assertEqual(item["review_status"], "confirmed")
        self.assertEqual(item["occurred_at"], "2024-03-18")
        self.assertEqual(item["project_id"], self.project)
        self.assertEqual(item["source_document_id"], self.doc["id"])
        # 来源追溯落到片段上
        links = self.store.list("provenance_link", {"entity_type": "work_item",
                                                    "entity_id": item["id"]}, limit=10)
        self.assertEqual([l["fragment_id"] for l in links], [self.f1])
        self.assertEqual(links[0]["origin"], "ai_agent")
        # 建议本身与审计都留痕
        proposal = self.store.get("change_proposal", item_proposal)
        self.assertEqual(proposal["status"], "confirmed")
        self.assertEqual(proposal["applied_entity_id"], item["id"])
        history = self.store.history("work_item", item["id"])
        self.assertEqual(history[0]["proposal_id"], item_proposal)

    def test_confirm_requires_required_fields(self):
        reply = self.reply()
        reply["items"][0].pop("content")          # 正文没法由引擎推导，必须由模型给出
        extraction, result, _ = self.run_extract(reply)
        review = Review(self.store, extraction=extraction)
        item_proposal = next(pid for pid in result["proposal_ids"]
                             if review.show(pid)["payload"].get("title") == "整理指标口径")
        self.assertTrue(any("content" in r for r in review.show(item_proposal)["requirements"]))
        with self.assertRaises(ExtractError) as ctx:
            review.confirm(item_proposal)
        self.assertIn("content", str(ctx.exception))
        self.assertEqual(self.store.count("work_item"), 0)

    def test_confirm_with_override_is_modified(self):
        reply = self.reply()
        reply["items"][0].pop("date_precision", None)
        extraction, result, _ = self.run_extract(reply)
        review = Review(self.store, extraction=extraction)
        item_proposal = next(pid for pid in result["proposal_ids"]
                             if review.show(pid)["payload"].get("title") == "整理指标口径")
        outcome = review.confirm(item_proposal, overrides={"occurred_at": "2024-03-20",
                                                          "date_precision": "day"})
        self.assertEqual(outcome["status"], "modified")
        proposal = self.store.get("change_proposal", item_proposal)
        self.assertEqual(proposal["status"], "modified")
        self.assertEqual(json.loads(proposal["final_payload"])["occurred_at"], "2024-03-20")
        item = self.store.get("work_item", outcome["applied_entity_id"])
        self.assertEqual(item["occurred_at"], "2024-03-20")

    def test_confirm_link_adds_provenance_to_existing_record(self):
        extraction, result, _ = self.run_extract()
        review = Review(self.store, extraction=extraction)
        link_proposal = next(pid for pid in result["proposal_ids"]
                             if review.show(pid)["proposal"]["change_type"] == "link")
        review.confirm(link_proposal)
        links = self.store.list("provenance_link", {"entity_type": "business_system",
                                                    "entity_id": self.system}, limit=10)
        self.assertEqual([l["fragment_id"] for l in links], [self.f1])
        self.assertEqual(self.store.count("business_system"), 1)

    def test_reject_leaves_archive_untouched(self):
        extraction, result, _ = self.run_extract()
        review = Review(self.store, extraction=extraction)
        outcome = review.reject(result["proposal_ids"][0], note="不需要")
        self.assertEqual(outcome["status"], "rejected")
        self.assertEqual(self.store.count("work_item"), 0)
        self.assertEqual(self.store.count("project"), 1)
        proposal = self.store.get("change_proposal", result["proposal_ids"][0])
        self.assertEqual(proposal["reviewer_note"], "不需要")

    def test_double_review_is_refused(self):
        extraction, result, _ = self.run_extract()
        review = Review(self.store, extraction=extraction)
        review.reject(result["proposal_ids"][0])
        with self.assertRaises(ExtractError):
            review.confirm(result["proposal_ids"][0])

    def test_review_list_filters_by_status_and_job(self):
        extraction, result, _ = self.run_extract()
        review = Review(self.store, extraction=extraction)
        self.assertEqual(len(review.list(status="pending")), 4)
        self.assertEqual(len(review.list(status="pending", job_id=result["job_id"])), 4)
        review.reject(result["proposal_ids"][0])
        self.assertEqual(len(review.list(status="pending")), 3)
        self.assertEqual(len(review.list(status="rejected")), 1)
        self.assertEqual(len(review.list()), 4)

    def test_show_skips_field_requirements_for_link(self):
        extraction, result, _ = self.run_extract()
        review = Review(self.store, extraction=extraction)
        link_proposal = next(pid for pid in result["proposal_ids"]
                             if review.show(pid)["proposal"]["change_type"] == "link")
        self.assertEqual(review.show(link_proposal)["requirements"], [])


class TestImmSemantics(BaseCase):
    def test_imm_field_can_be_filled_once_then_locked(self):
        rid = self.store.insert("source_document", {
            "title": "t", "doc_type": "weekly_report", "source_channel": "manual_input",
            "raw_text": "正文", "origin": "user"})
        self.store.commit()
        # 首次写入允许（作业结束时补记一次性结果）
        self.store.update("source_document", rid, {"summary": "摘要"})
        self.store.update("source_document", rid, {"word_count": 12})
        self.store.commit()
        # 已经写下值的不可修改字段：一律拒绝
        with self.assertRaises(ModelError):
            self.store.update("source_document", rid, {"raw_text": "改过的正文"})
        # 摘要属于规则 A2 的白名单（可由系统或 AI 重新生成），可以继续更新
        self.store.update("source_document", rid, {"summary": "换个摘要"})
        self.store.commit()
        self.assertEqual(self.store.get("source_document", rid)["summary"], "换个摘要")
        self.assertEqual(self.store.get("source_document", rid)["raw_text"], "正文")


if __name__ == "__main__":
    unittest.main()
