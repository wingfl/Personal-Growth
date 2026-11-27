// BOSS 直聘适配器：需要先在 login.js 打开的窗口里通过安全验证/登录，cookie 留在浏览器配置目录。
const { sleep } = require("../lib/browser");

const CITY_CODES = { 杭州: "101210100", 北京: "101010100", 上海: "101020100", 广州: "101280100", 深圳: "101280600" };

function searchUrl(keyword, cityCode) {
  return `https://www.zhipin.com/web/geek/job?query=${encodeURIComponent(keyword)}&city=${cityCode}`;
}

function normalize(raw, keyword) {
  const area = (raw.area || "").split("·").map((s) => s.trim()).filter(Boolean);
  return {
    platform: "boss",
    external_id: raw.id,
    title: raw.title,
    company: raw.company,
    city: area[0] || "",
    district: area[1] || "",
    salary_text: raw.salary,
    salary_min: null,
    salary_max: null,
    salary_months: null,
    experience: raw.experience,
    degree: raw.degree,
    tags: raw.tags,
    industry: raw.industry,
    company_size: raw.size,
    company_type: raw.stage,
    url: `https://www.zhipin.com/job_detail/${raw.id}.html`,
    published_at: null,
    fetched_at: new Date().toISOString(),
    keyword,
    jd_text: null,
  };
}

async function openSession(browser, { keyword, cityCode }) {
  const page = await browser.newPage();
  await page.setUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36 Edg/158.0.0.0");
  await page.setExtraHTTPHeaders({ "Accept-Language": "zh-CN,zh;q=0.9" });
  await page.goto(searchUrl(keyword, cityCode), { waitUntil: "domcontentloaded", timeout: 45000 });
  await sleep(5000);
  const title = await page.title();
  if (/安全验证|验证/.test(title)) {
    throw new Error("BOSS 要求安全验证：先运行 node login.js，在打开的窗口里点一次验证/登录");
  }
  return page;
}

async function parseCards(page) {
  return page.evaluate(() => {
    const text = (el) => (el ? el.innerText.replace(/\s+/g, " ").trim() : "");
    return Array.from(document.querySelectorAll(".job-card-wrapper")).map((card) => {
      const link = card.querySelector('a[href*="job_detail"]');
      const href = link ? link.getAttribute("href") : "";
      const id = (href.match(/job_detail\/([^.?/]+)/) || [])[1] || href;
      const tags = Array.from(card.querySelectorAll(".tag-list li, .job-card-left .job-info .tag-list span")).map(text).filter(Boolean);
      const companyTags = Array.from(card.querySelectorAll(".company-tag-list li")).map(text).filter(Boolean);
      return {
        id,
        title: text(card.querySelector(".job-name")),
        salary: text(card.querySelector(".salary")),
        area: text(card.querySelector(".job-area")),
        tags,
        company: text(card.querySelector(".company-name")),
        industry: companyTags[0] || "",
        stage: companyTags[1] || "",
        size: companyTags[2] || "",
        experience: (text(card.querySelector(".job-info .tag-list")) || tags[0] || "").slice(0, 20),
        degree: tags[1] || "",
      };
    });
  });
}

async function collectKeyword(page, { keyword, cityCode, pages = 3, delayMs = 2500, log = () => {} }) {
  const items = new Map();
  let total = null;
  let used = 0;
  for (let p = 1; p <= pages; p += 1) {
    const rows = await parseCards(page);
    if (p === 1) total = rows.length ? rows.length : 0;
    for (const row of rows) {
      if (!row.title || !row.id) continue;
      items.set(row.id, normalize(row, keyword));
    }
    used += 1;
    log(`  第 ${p} 页：${rows.length} 条，累计 ${items.size}`);
    if (p === pages) break;
    const next = await page.$(".options-pages a:last-child, .ui-icon-arrow-right");
    if (!next) break;
    await next.click().catch(() => {});
    await sleep(delayMs + 1200);
    const title = await page.title();
    if (/安全验证/.test(title)) {
      log("  翻页时触发安全验证，停止该方向");
      break;
    }
  }
  return { total, pages: used, items: Array.from(items.values()) };
}

module.exports = { openSession, collectKeyword, CITY_CODES };
