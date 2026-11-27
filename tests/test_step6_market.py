import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.market import ingest, parse_salary, role_family_for, summary
from app.store import Store


class TestSalary(unittest.TestCase):
    def test_month_range(self):
        self.assertEqual(parse_salary("2.1-2.5万·14薪"), (21000, 25000, 14, "month"))

    def test_mixed_units(self):
        self.assertEqual(parse_salary("8千-1.5万"), (8000, 15000, None, "month"))

    def test_annual_to_month(self):
        lo, hi, _months, period = parse_salary("30-60万/年")
        self.assertEqual(period, "year")
        self.assertEqual((lo, hi), (25000, 50000))

    def test_daily_not_converted(self):
        self.assertEqual(parse_salary("200-300元/天"), (None, None, None, "day"))

    def test_negotiable(self):
        self.assertEqual(parse_salary("面议"), (None, None, None, "month"))


class TestRoleFamily(unittest.TestCase):
    def test_design_keyword(self):
        self.assertEqual(role_family_for("产品设计"), "design")

    def test_product_keyword(self):
        self.assertEqual(role_family_for("AI产品经理"), "product")

    def test_unknown(self):
        self.assertEqual(role_family_for("神秘岗位"), "other")


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="growth-test6-")
        db = os.path.join(self.tmp, "growth.db")
        Store.init(db)
        self.store = Store(db)
        self.path = os.path.join(self.tmp, "jobs.jsonl")
        rows = [
            {"platform": "51job", "external_id": "1", "title": "AI产品经理", "company": "A",
             "city": "杭州", "salary_text": "1-2万", "tags": ["SQL", "PRD"], "keyword": "AI产品经理"},
            {"platform": "51job", "external_id": "2", "title": "产品经理", "company": "B",
             "city": "杭州", "salary_text": "面议", "tags": ["B端"], "keyword": "产品经理"},
        ]
        with open(self.path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ingest_and_dedupe(self):
        stats = ingest(self.store, self.path)
        self.assertEqual(stats["created"], 2)
        # 同一份文件再入一次：按 platform + external_id 更新，不新增
        again = ingest(self.store, self.path)
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["updated"], 2)
        self.assertEqual(self.store.count("job_posting"), 2)

    def test_summary_percentiles(self):
        ingest(self.store, self.path)
        data = summary(self.store, city="杭州")
        self.assertEqual(data["total_postings"], 2)
        group = [g for g in data["groups"] if g["keyword"] == "AI产品经理"][0]
        # 只有一条样本时三个分位都等于区间中值，不制造虚假的分布
        self.assertEqual((group["salary_p25"], group["salary_p50"], group["salary_p75"]),
                         (15000, 15000, 15000))
        self.assertIn("SQL", [tag["tag"] for tag in group["top_tags"]])


if __name__ == "__main__":
    unittest.main()
