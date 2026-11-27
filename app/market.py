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
