# -*- coding: utf-8 -*-
"""第 5 步（能力词典、能力证据、能力画像）的离线自检用例。

不联网：用假 transport 顶替模型网关，验证词典幂等、证据只能从已确认事项派生、
引用必须逐字出自原文、确认后画像才计入。

运行：python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.capability import CapabilityMapper, capabilities, evidence, seed
from app.extract import Extraction, Review
from app.llm import LLMClient, resolve_config
from app.store import Store


class FakeTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append(payload)
        content = json.dumps(self.replies.pop(0), ensure_ascii=False)
        return {
            "model": "fake-model-1",
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }


def fake_llm(*replies):
    transport = FakeTransport(replies)
    config = resolve_config(model="fake-model", api_key="test-key",
                            base_url="http://fake.local/v1", provider="fake")
    return LLMClient(config=config, transport=transport), transport


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-test5-")
        self.db = os.path.join(self.tmp, "growth.db")
        Store.init(self.db)
        self.store = Store(self.db)
        Extraction(self.store).seed_config()
        seed(self.store)
        self.store.commit()

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_item(self, title, content="", occurred_at="2024-03-18"):
        item_id = self.store.insert("work_item", {
            "title": title,
            "item_type": "requirement_analysis",
            "content": content,
            "is_routine": 0,
            "occurred_at": occurred_at,
            "date_precision": "day",
            "is_follow_up_needed": 0,
            "origin": "user",
            "review_status": "confirmed",
            "is_fact": 1,
        })
        self.store.commit()
        return item_id


class TestSeed(BaseCase):
    def test_seed_is_idempotent(self):
        self.assertEqual(4, self.store.count("capability_category"))
        self.assertEqual(10, self.store.count("capability"))
        # 再跑一次不应新增任何行
        self.assertEqual((0, 0), seed(self.store))
        self.assertEqual(4, self.store.count("capability_category"))
        self.assertEqual(10, self.store.count("capability"))

    def test_capabilities_grouped_without_evidence(self):
        rows = capabilities(self.store)
        self.assertEqual(10, len(rows))
        self.assertTrue(all(row["evidence_count"] == 0 for row in rows))
        self.assertTrue(all(row["avg_strength"] is None for row in rows))
        self.assertEqual(4, len({row["category"] for row in rows}))


class TestMapper(BaseCase):
    def test_rejects_quote_not_in_item(self):
        item_id = self.add_item("梳理投放链路的数据口径", "和投放同学对齐了 3 个指标口径")
        llm, _ = fake_llm({"evidence": [{
            "item_id": item_id,
            "capability": "PU2",
            "evidence_type": "responsibility",
            "strength": 3,
            "statement": "负责投放链路的数据口径梳理",
            "quote": "这句话原文里根本没有",
        }]})
        mapper = CapabilityMapper(self.store, llm=llm)
        out = mapper.run()
        self.assertEqual(1, out["items"])
        self.assertEqual(0, out["proposals"])
        self.assertEqual(1, out["skipped"])
        self.assertEqual(0, self.store.count("capability_evidence"))
        job = self.store.get("ai_job", out["job_id"])
        self.assertEqual("succeeded", job["status"])

    def test_proposal_then_confirm_feeds_profile(self):
        item_id = self.add_item("梳理投放链路的数据口径", "和投放同学对齐了 3 个指标口径")
        llm, _ = fake_llm({"evidence": [{
            "item_id": item_id,
            "capability": "PU2",
            "evidence_type": "responsibility",
            "strength": 3,
            "statement": "负责投放链路的数据口径梳理，对齐 3 个指标",
            "quote": "和投放同学对齐了 3 个指标口径",
        }]})
        out = CapabilityMapper(self.store, llm=llm).run()
        self.assertEqual(1, out["proposals"])
        self.assertEqual(0, out["skipped"])

        # 建议未确认前不进入画像
        rows = capabilities(self.store)
        self.assertTrue(all(row["evidence_count"] == 0 for row in rows))

        proposal = self.store.list("change_proposal", {"job_id": out["job_id"]})[0]
        Review(self.store).confirm(proposal["id"], actor_type="user")
        self.store.commit()

        self.assertEqual(1, self.store.count("capability_evidence"))
        rows = {row["code"]: row for row in capabilities(self.store)}
        self.assertEqual(1, rows["PU2"]["evidence_count"])
        self.assertEqual(3, rows["PU2"]["avg_strength"])
        self.assertEqual(1, len(evidence(self.store, rows["PU2"]["id"])))
        # 已经有证据的事项不再重复标注
        self.assertEqual(0, len(CapabilityMapper(self.store, llm=llm)._items()))


if __name__ == "__main__":
    unittest.main()
