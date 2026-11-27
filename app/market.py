"""就业市场样本：把招聘平台采集到的岗位列表入库，并汇总成可对照的薪资与要求分布。

设计边界：
- 只处理「岗位列表」级别的公开信息（标题、公司、薪资、经验、学历、标签），不采集候选人简历；
- 采集器在 `collector/` 里用 Node 跑（允许第三方依赖），本模块只读 JSONL 并写库，保持 app/ 零依赖；
- 同一平台内按 `external_id` 去重，重复采集时更新样本而不是新增一行。
"""
import json
import os
import re
from datetime import datetime, timezone

UNIT = {"万": 10000, "千": 1000, "元": 1}

ROLE_FAMILY_BY_KEYWORD = [
    ("产品设计", "design"),
    ("交互", "design"),
    ("视觉", "design"),
    ("ui", "design"),
    ("运营", "operations"),
    ("测试", "qa"),
    ("开发", "engineering"),
    ("研发", "engineering"),
    ("算法", "engineering"),
    ("产品", "product"),
]


def parse_salary(text):
    """把招聘平台的薪资原文折算成元/月。

    支持「2.1-2.5万·14薪」「8千-1.5万」「1.6-3万」「30-60万/年」「200-300元/天」「面议」。
    返回 (min, max, months, period)；无法折算的返回 (None, None, months, period)。
    """
    raw = (text or "").strip()
    months = None
    m = re.search(r"[·\s]*(\d{1,2})\s*薪", raw)
    if m:
        months = int(m.group(1))
    period = "month"
    if "/年" in raw or "每年" in raw:
        period = "year"
    elif "/天" in raw or "/日" in raw:
        period = "day"
    elif "/时" in raw or "/小时" in raw:
        period = "hour"

    body = re.sub(r"[·\s]*\d{1,2}\s*薪", "", raw)
    body = body.split("/")[0]
    nums = re.findall(r"(\d+(?:\.\d+)?)\s*(万|千|元)?", body)
    if not nums:
        return None, None, months, period

    nums = nums[:2]
    # 「2.1-2.5万」这种写法只在末尾标一次单位：前一个数沿用后一个数的单位
    if len(nums) == 2 and not nums[0][1] and nums[1][1]:
        nums[0] = (nums[0][0], nums[1][1])
    values = []
    for num, unit in nums:
        values.append(float(num) * UNIT.get(unit, 1))
    if not values:
        return None, None, months, period
    lo = values[0]
    hi = values[1] if len(values) > 1 else values[0]

    if period == "year":
        lo, hi = lo / 12.0, hi / 12.0
    if period in ("day", "hour"):
        return None, None, months, period
    return int(round(lo)), int(round(hi)), months, period


def role_family_for(keyword, title=""):
    text = ("%s %s" % (keyword or "", title or "")).lower()
    for needle, family in ROLE_FAMILY_BY_KEYWORD:
        if needle.lower() in text:
            return family
    return "other"


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ingest(store, path, target_role=None, role_family=None):
    """把一份采集 JSONL 写入 job_posting；返回统计。"""
    if not os.path.exists(path):
        raise SystemExit("找不到采集文件：%s" % path)
    created, updated, skipped = 0, 0, 0
    role = store.find_one("target_role", name=target_role) if target_role else None
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            platform = row.get("platform") or "other"
            external_id = str(row.get("external_id") or "").strip()
            title = (row.get("title") or "").strip()
            if not external_id or not title:
                skipped += 1
                continue
            smin, smax, months, period = parse_salary(row.get("salary_text"))
            if smin is None and row.get("salary_min") is not None:
                smin, smax = row.get("salary_min"), row.get("salary_max")
                months = row.get("salary_months")
            family = role_family or role_family_for(row.get("keyword"), title)
            values = {
                "platform": platform,
                "external_id": external_id,
                "title": title,
                "company": row.get("company") or "",
                "city": row.get("city") or "",
                "district": row.get("district") or "",
                "salary_text": row.get("salary_text") or "",
                "salary_min": smin,
                "salary_max": smax,
                "salary_months": months,
                "experience": row.get("experience") or "",
                "degree": row.get("degree") or "",
                "jd_text": row.get("jd_text") or "",
                "tags": row.get("tags") or [],
                "industry": row.get("industry") or "",
                "company_size": row.get("company_size") or "",
                "company_type": row.get("company_type") or "",
                "url": row.get("url") or "",
                "published_at": row.get("published_at") or "",
                "fetched_at": row.get("fetched_at") or _now(),
                "keyword": row.get("keyword") or "",
                "matched_keywords": row.get("matched_keywords") or [],
                "role_family": family,
                "target_role_id": role["id"] if role else None,
            }
            existing = store.find_one("job_posting", platform=platform, external_id=external_id)
            if existing:
                patch = {k: v for k, v in values.items() if v not in (None, "")}
                store.update("job_posting", existing["id"], patch,
                             expected_revision=existing.get("revision"), actor_type="user",
                             remark="采集更新")
                updated += 1
            else:
                store.insert("job_posting", values, actor_type="user", remark="采集入库")
                created += 1
    store.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


def _as_list(value):
    """json 字段在库里可能是字符串：统一还原成列表。"""
    if isinstance(value, list):
        return value
    if not value:
        return []
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except ValueError:
            return [value]
        return data if isinstance(data, list) else []
    return []


def _percentile(values, q):
    if not values:
        return None
    nums = sorted(values)
    if len(nums) == 1:
        return nums[0]
    pos = (len(nums) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(nums) - 1)
    frac = pos - lo
    return int(round(nums[lo] * (1 - frac) + nums[hi] * frac))


CAPABILITY_NAMES = {
    "PU1": "用户洞察", "PU2": "产品设计", "PU3": "数据分析",
    "DQ1": "项目推进", "DQ2": "质量与验收", "DQ3": "风险处理",
    "CO1": "跨团队协作", "CO2": "沟通表达",
    "CG1": "领域知识", "CG2": "复盘迁移",
}

# 要求词 → 能力：用于把岗位标题/标签/JD 正文折算成「这条岗位要什么能力」
REQUIREMENT_RULES = (
    ("PU3", ("数据分析", "数据驱动", "指标", "埋点", "abtest", "ab test", "报表", "漏斗", "sql")),
    ("PU1", ("用户研究", "用户调研", "访谈", "洞察", "用户需求", "竞品")),
    ("PU2", ("prd", "需求文档", "原型", "交互设计", "方案设计", "产品设计", "流程图", "需求分析")),
    ("DQ1", ("项目管理", "排期", "推进", "跨部门", "协同", "落地", "跟进")),
    ("DQ2", ("测试", "验收", "质量", "上线", "交付")),
    ("DQ3", ("风险", "合规", "风控", "应急")),
    ("CO1", ("跨团队", "协作", "对接", "沟通协调")),
    ("CO2", ("沟通", "表达", "汇报", "演讲", "文档")),
    ("CG1", ("行业", "领域知识", "ai", "大模型", "llm", "aigc", "算法", "商业化", "增长", "投放")),
    ("CG2", ("复盘", "方法论", "沉淀", "总结")),
)

BAND_NAMES = {"low": "中位以下", "mid": "中位到 P75", "high": "P75 以上"}


def requirements_of(row):
    """从一条岗位样本抽取能力要求（不依赖 JD 正文，正文有则一起算）。"""
    text = " ".join([
        row.get("title") or "", row.get("jd_text") or "", row.get("keyword") or "",
        " ".join(_as_list(row.get("tags"))), row.get("degree") or "", row.get("experience") or "",
    ]).lower()
    hits = []
    for code, needles in REQUIREMENT_RULES:
        for needle in needles:
            if needle.isascii():
                if re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(needle), text):
                    hits.append((code, needle))
                    break
            elif needle in text:
                hits.append((code, needle))
                break
    return hits


def _mid(row):
    if row.get("salary_min") and row.get("salary_max"):
        return (row["salary_min"] + row["salary_max"]) / 2.0
    return None


def _load(store, city=None):
    where = {"city": city} if city else None
    return store.list("job_posting", where=where, limit=5000)


def _evidence_counts(store):
    counts = {}
    for row in store.list("capability", limit=100):
        counts[row["code"]] = {"id": row["id"], "name": row["name"], "count": 0}
    for ev in store.list("capability_evidence", limit=20000):
        cap = ev.get("capability_id")
        for code, info in counts.items():
            if info["id"] == cap:
                info["count"] += 1
                break
    return counts


def analyze(store, city=None, salary=None):
    """薪资位置 + 分档要求频次 + 与高薪样本的能力差距。"""
    rows = _load(store, city)
    mids = sorted([_mid(r) for r in rows if _mid(r)])
    p25 = _percentile(mids, 0.25)
    p50 = _percentile(mids, 0.50)
    p75 = _percentile(mids, 0.75)

    def band_of(value):
        if not value or p50 is None:
            return None
        if value < p50:
            return "low"
        if value < p75:
            return "mid"
        return "high"

    bands = {}
    for row in rows:
        mid = _mid(row)
        key = band_of(mid)
        if not key:
            continue
        bands.setdefault(key, []).append(row)

    band_out = []
    for key in ("low", "mid", "high"):
        items = bands.get(key, [])
        if not items:
            continue
        counter = {}
        for row in items:
            for code, needle in requirements_of(row):
                counter[code] = counter.get(code, 0) + 1
        top = sorted(counter.items(), key=lambda kv: -kv[1])[:6]
        band_out.append({
            "key": key,
            "name": BAND_NAMES[key],
            "postings": len(items),
            "salary_from": {"low": None, "mid": p50, "high": p75}[key],
            "salary_to": {"low": p50, "mid": p75, "high": None}[key],
            "requirements": [
                {"code": c, "name": CAPABILITY_NAMES.get(c, c), "count": n,
                 "share": round(n * 100.0 / len(items), 1)}
                for c, n in top
            ],
        })

    evidence = _evidence_counts(store)
    high = bands.get("high", [])
    percentile = None
    if salary and mids:
        below = len([m for m in mids if m < salary])
        percentile = round(below * 100.0 / len(mids), 1)

    gaps = []
    if high:
        counter = {}
        examples = {}
        for row in high:
            for code, needle in requirements_of(row):
                counter[code] = counter.get(code, 0) + 1
                examples.setdefault(code, [])
                if row.get("title") not in examples[code]:
                    examples[code].append(row.get("title"))
        for code, n in counter.items():
            share = n * 100.0 / len(high)
            ev = evidence.get(code, {}).get("count", 0)
            gaps.append({
                "code": code,
                "name": CAPABILITY_NAMES.get(code, code),
                "high_count": n,
                "high_share": round(share, 1),
                "evidence": ev,
                "examples": [t for t in examples.get(code, []) if t][:3],
            })
        # 高薪岗位提得多、我证据少的排前面
        for item in gaps:
            coverage = min(item["evidence"], 20) / 20.0
            item["score"] = round(item["high_share"] * (1 - coverage), 1)
        gaps.sort(key=lambda x: -x["score"])

    my_band = band_of(salary)
    next_at = None
    if my_band == "low":
        next_at = p50
    elif my_band == "mid":
        next_at = p75

    return {
        "samples": len(rows),
        "salary_samples": len(mids),
        "p25": p25, "p50": p50, "p75": p75,
        "salary": salary,
        "percentile": percentile,
        "band": my_band,
        "band_name": BAND_NAMES.get(my_band) if my_band else None,
        "next_band_at": next_at,
        "to_next_band": (next_at - salary) if (next_at and salary) else None,
        "bands": band_out,
        "gaps": gaps,
        "recommendations": gaps[:2],
        "benchmarks": benchmarks(store, city=city),
    }


def benchmark_add(store, role_name, p25=None, p50=None, p75=None, city="",
                  level="", source="", source_url="", sample_size=None, as_of="", note=""):
    """录入行业报告口径的薪资分位（不是爬虫样本，来自公开报告）。"""
    row = {
        "role_name": role_name, "role_family": role_family_for(role_name, role_name),
        "city": city, "level": level,
        "p25": p25, "p50": p50, "p75": p75,
        "currency": "CNY", "period": "month",
        "source": source, "source_url": source_url,
        "sample_size": sample_size,
        "as_of": as_of or datetime.now(timezone.utc).date().isoformat(), "note": note,
    }
    existing = store.find_one("salary_benchmark", role_name=role_name, city=city, source=source)
    if existing:
        store.update("salary_benchmark", existing["id"], row, actor_type="user", remark="报告口径更新")
    else:
        store.insert("salary_benchmark", row, actor_type="user", remark="报告口径录入")
    store.commit()
    return row


def benchmarks(store, city=None):
    rows = store.list("salary_benchmark", limit=200)
    out = []
    for row in rows:
        if city and row.get("city") and row["city"] != city:
            continue
        out.append({k: row.get(k) for k in
                    ("role_name", "city", "level", "p25", "p50", "p75", "period",
                     "source", "source_url", "sample_size", "as_of", "note")})
    return out


def summary(store, city=None):
    """按岗位族 + 关键词汇总样本数、薪资分位与高频标签。"""
    where = {"city": city} if city else None
    rows = store.list("job_posting", where=where, limit=5000)
    groups = {}
    for row in rows:
        key = (row.get("role_family") or "other", row.get("keyword") or "")
        groups.setdefault(key, []).append(row)

    out = []
    for (family, keyword), items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        mids = []
        for it in items:
            if it.get("salary_min") and it.get("salary_max"):
                mids.append((it["salary_min"] + it["salary_max"]) / 2)
        tags = {}
        for it in items:
            for tag in _as_list(it.get("tags")):
                tags[tag] = tags.get(tag, 0) + 1
        top_tags = sorted(tags.items(), key=lambda kv: -kv[1])[:12]
        out.append({
            "role_family": family,
            "keyword": keyword,
            "postings": len(items),
            "salary_p25": _percentile(mids, 0.25),
            "salary_p50": _percentile(mids, 0.50),
            "salary_p75": _percentile(mids, 0.75),
            "salary_samples": len(mids),
            "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
            "companies": sorted({it.get("company") for it in items if it.get("company")})[:8],
        })
    return {
        "generated_at": _now(),
        "total_postings": len(rows),
        "cities": sorted({r.get("city") for r in rows if r.get("city")}),
        "groups": out,
    }


def ingest_cli(store, path, target_role=None):
    stats = ingest(store, path, target_role=target_role)
    print("✓ 岗位样本入库：新增 %(created)d、更新 %(updated)d、跳过 %(skipped)d" % stats)
    total = store.count("job_posting")
    print("  当前样本共 %d 条" % total)
    return stats
