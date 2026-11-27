// 深挖智联搜索页：卡片选择器、薪资是否可见、以及页面发出的数据接口。
const { launch, newPage, sleep } = require("./lib/browser.js");

(async () => {
  const browser = await launch({ headless: true });
  const page = await newPage(browser);
  const apiUrls = [];
  page.on("response", (res) => {
    const url = res.url();
    if (/api|search|position|job/i.test(url) && !/\.(js|css|png|jpg|svg|woff2?)/.test(url)) {
      apiUrls.push(`${res.status()} ${url.slice(0, 160)}`);
    }
  });
  await page.goto("https://sou.zhaopin.com/?jl=653&kw=%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86", {
    waitUntil: "domcontentloaded",
    timeout: 45000,
  });
  await sleep(8000);

  const info = await page.evaluate(() => {
    const text = (el) => (el.innerText || "").replace(/\s+/g, " ").trim();
    const candidates = [
      ".joblist-box__item",
      ".joblist-box__iteminfo",
      "[class*=joblist]",
      "[class*=job-card]",
      "[class*=position]",
    ];
    const counts = {};
    for (const sel of candidates) counts[sel] = document.querySelectorAll(sel).length;
    const cards = Array.from(document.querySelectorAll("[class*=job-card]"));
    const top = cards.filter((c) => c.className.toString().split(" ").length <= 3).slice(0, 5);
    return {
      counts,
      cards: cards.length,
      sample: top.map((c) => text(c).slice(0, 400)),
      classes: cards.slice(0, 8).map((c) => c.className.toString()),
      links: Array.from(document.querySelectorAll("a[href*=job]")).slice(0, 5).map((a) => a.getAttribute("href")),
      htmlSample: document.body.innerHTML.slice(0, 500),
    };
  });
  console.log(JSON.stringify({ ...info, apiUrls: [...new Set(apiUrls)].slice(0, 30) }, null, 2));
  await browser.close();
})();
