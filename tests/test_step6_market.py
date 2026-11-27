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

class _StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "t.db")
        Store.init(self.db_path)
        self.store = Store(self.db_path)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestMarketAnalysis(_StoreCase):
    def _seed(self):
        rows = [
            {"platform": "51job", "external_id": "a", "title": "AI产品经理", "city": "杭州",
             "salary_text": "1.5-2万", "salary_min": 15000, "salary_max": 20000, "tags": ["数据分析", "PRD"], "keyword": "AI产品经理",
             "fetched_at": "2026-11-27T00:00:00Z"},
            {"platform": "51job", "external_id": "b", "title": "产品经理", "city": "杭州",
             "salary_text": "1-1.2万", "salary_min": 10000, "salary_max": 12000, "tags": ["用户调研"], "keyword": "产品经理",
             "fetched_at": "2026-11-27T00:00:00Z"},
            {"platform": "51job", "external_id": "c", "title": "高级产品经理", "city": "杭州",
             "salary_text": "2.5-3万", "salary_min": 25000, "salary_max": 30000, "tags": ["数据分析", "跨团队协作"], "keyword": "产品经理",
             "fetched_at": "2026-11-27T00:00:00Z"},
        ]
        for row in rows:
            self.store.insert("job_posting", row, actor_type="user", remark="test")
        self.store.commit()

    def test_analyze_position_and_gaps(self):
        from app.market import analyze
        self._seed()
        data = analyze(self.store, city="杭州", salary=12000)
        self.assertEqual(data["samples"], 3)
        self.assertIsNotNone(data["p50"])
        self.assertIn(data["band"], ("low", "mid", "high"))
        self.assertTrue(data["gaps"])
        self.assertLessEqual(len(data["recommendations"]), 2)
        for gap in data["gaps"]:
            self.assertGreaterEqual(gap["high_share"], 0)

    def test_requirement_extraction(self):
        from app.market import requirements_of
        codes = [c for c, _ in requirements_of({"title": "AI产品经理", "tags": ["数据分析"], "jd_text": "负责 PRD 与跨团队协作"})]
        self.assertIn("PU3", codes)
        self.assertIn("PU2", codes)
        self.assertIn("CO1", codes)

    def test_benchmark_add_is_idempotent(self):
        from app.market import benchmark_add, benchmarks
        benchmark_add(self.store, "产品经理", p50=20000, source="报告A")
        benchmark_add(self.store, "产品经理", p50=22000, source="报告A")
        rows = benchmarks(self.store)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["p50"], 22000)


class TestPortable(_StoreCase):
    def test_export_import_round_trip(self):
        import os, tempfile
        from app import portable
        zip_path = os.path.join(tempfile.mkdtemp(), "a.zip")
        target = os.path.join(tempfile.mkdtemp(), "b.db")
        size = portable.export_db(self.db_path, zip_path)
        self.assertGreater(size, 0)
        manifest = portable.import_db(zip_path, target)
        self.assertEqual(manifest["format"], "growth-archive/1")
        self.assertTrue(os.path.exists(target))
