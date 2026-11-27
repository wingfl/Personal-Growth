const puppeteer = require("puppeteer-core");
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
(async () => {
  const b = await puppeteer.launch({ executablePath: EDGE, headless: "new", args: ["--no-sandbox","--disable-blink-features=AutomationControlled","--lang=zh-CN"] });
  const p = await b.newPage();
  await p.setUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36");
  await p.goto("https://we.51job.com/pc/search?keyword=AI%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86&jobArea=080200", { waitUntil: "domcontentloaded", timeout: 45000 });
  await new Promise(r => setTimeout(r, 2500));
  const out = await p.evaluate(async () => {
    const q = new URLSearchParams({ api_key:"51job", timestamp:String(Date.now()), keyword:"AI产品经理", searchType:"2", jobArea:"080200", pageNum:"1", pageSize:"50", source:"1", pageCode:"sou|sou|soulb", sortType:"0" });
    const r = await fetch("https://we.51job.com/api/job/search-pc?" + q.toString(), { credentials:"include" });
    const d = await r.json();
    const items = d.resultbody.job.items;
    return { total: d.resultbody.job.totalCount, n: items.length,
      sample: items.slice(0,4).map(i => ({ id:i.jobId, name:i.jobName, area:i.jobAreaString, sal:i.provideSalaryString, yr:i.workYearString, deg:i.degreeString, href:i.jobHref||null, keys: Object.keys(i).filter(k=>/href|url/i.test(k)) })) };
  });
  console.log(JSON.stringify(out, null, 1).slice(0, 2500));
  await b.close();
})();
