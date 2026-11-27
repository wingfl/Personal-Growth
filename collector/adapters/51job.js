// 51job（前程无忧）列表采集适配器。
// 说明：直接请求 API 会被阿里云 WAF 拦；先在浏览器里打开搜索页通过 WAF，再在页面上下文里 fetch，
// 这样拿到的是结构化 JSON（含薪资/经验/学历/技能标签）。详情页有滑块验证，不采集详情正文。
// 重要：整个采集过程复用同一个页面（同一 WAF 会话），每个关键词重新开页会拿到 0 条。
const { newPage, sleep } = require("../lib/browser");
const { parseSalary } = require("../lib/salary");

const SEARCH_URL = "https://we.51job.com/pc/search";
const API_BASE = "https://we.51job.com/api/job/search-pc";

function buildQuery({ keyword, cityCode, page, pageSize }) {
  return new URLSearchParams({
    api_key: "51job",
    timestamp: String(Date.now()),
    keyword,
    searchType: "2",
    function: "",
    industry: "",
    jobArea: cityCode,
    jobArea2: "",
    landmark: "",
    metro: "",
    salary: "",
    workYear: "",
    degree: "",
    companyType: "",
    companySize: "",
    jobType: "",
    issueDate: "",
    sortType: "0",
    pageNum: String(page),
    requestId: "",
    pageSize: String(pageSize),
    source: "1",
    accountId: "",
    pageCode: "sou|sou|soulb",
  }).toString();
}

function normalize(item, keyword) {
  const salary = parseSalary(item.provideSalaryString);
  const area = (item.jobAreaString || "").split("·");
  return {
    platform: "51job",
    external_id: String(item.jobId),
    title: item.jobName || "",
    company: item.companyName || "",
    city: area[0] || "",
    district: area[1] || "",
    salary_text: salary.text,
    salary_min: salary.min,
    salary_max: salary.max,
    salary_months: salary.months,
    experience: item.workYearString || "",
    degree: item.degreeString || "",
    tags: Array.isArray(item.jobTags) ? item.jobTags : [],
    industry: item.companyIndustryType1Str || item.industryType1Str || "",
    company_size: item.companySizeString || "",
    company_type: item.companyTypeString || "",
    url: item.jobHref || "",
    published_at: item.issueDateString || "",
    keyword,
  };
}

async function openSession(browser, { keyword, cityCode }) {
  const page = await newPage(browser);
  const url = `${SEARCH_URL}?keyword=${encodeURIComponent(keyword)}&jobArea=${cityCode}`;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
  await sleep(3500);
  return page;
}

async function queryPage(page, { keyword, cityCode, pageNo, pageSize }) {
  const q = buildQuery({ keyword, cityCode, page: pageNo, pageSize });
  let last = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const payload = await Promise.race([
      page.evaluate(async (u) => {
      try {
        const r = await fetch(u, { credentials: "include", headers: { accept: "application/json" } });
        const text = await r.text();
        if (!r.ok) return { error: `HTTP ${r.status}`, body: text.slice(0, 200) };
        try {
          return { data: JSON.parse(text) };
        } catch (e) {
          return { error: "not-json", body: text.slice(0, 200) };
        }
      } catch (e) {
        return { error: String(e).slice(0, 200) };
      }
      }, `${API_BASE}?${q}`),
      sleep(30000).then(() => ({ error: "timeout" })),
    ]);
    last = payload;
    const body = payload && payload.data && payload.data.resultbody && payload.data.resultbody.job;
    if (body) return body;
    await sleep(2000 * attempt);
  }
  return null;
}

/**
 * 复用同一个 page 采一个关键词。
 * @param {object} page 由 openSession 返回
 */
async function collectKeyword(page, { keyword, cityCode, pages = 5, pageSize = 50, delayMs = 1800, log = () => {} }) {
  const items = [];
  let total = null;
  let usedPages = 0;
  for (let p = 1; p <= pages; p += 1) {
    let body = null;
    try {
      body = await queryPage(page, { keyword, cityCode, pageNo: p, pageSize });
    } catch (err) {
      log(`  page ${p}: 请求异常（${String(err).slice(0, 80)}）`);
      break;
    }
    if (!body) {
      log(`  page ${p}: 无数据（WAF/接口异常）`);
      break;
    }
    if (total == null && typeof body.totalCount === "number") total = body.totalCount;
    const batch = Array.isArray(body.items) ? body.items : [];
    for (const it of batch) items.push(normalize(it, keyword));
    usedPages = p;
    log(`  page ${p}: ${batch.length} 条（累计 ${items.length}/${total ?? "?"}）`);
    if (batch.length < pageSize) break;
    await sleep(delayMs);
  }
  return { items, total, pages: usedPages };
}

module.exports = { openSession, collectKeyword, normalize, buildQuery, queryPage };
