// 一次性探针：看 BOSS / 智联 / 猎聘 的搜索页在真实浏览器里能否渲染出岗位卡片。
const { launch, newPage, sleep } = require("./lib/browser.js");

const TARGETS = [
  {
    name: "boss",
    url: "https://www.zhipin.com/web/geek/job?query=%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86&city=101210100",
  },
  {
    name: "zhaopin",
    url: "https://sou.zhaopin.com/?jl=653&kw=%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86",
  },
  {
    name: "liepin",
    url: "https://www.liepin.com/zhaopin/?key=%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86&city=070020",
  },
];

(async () => {
const browser = await launch({ headless: true });
for (const t of TARGETS) {
  const page = await newPage(browser);
  const out = { name: t.name, url: t.url, title: "", jobs: 0, sample: [], text: "", blocked: false };
  try {
    await page.goto(t.url, { waitUntil: "domcontentloaded", timeout: 45000 });
    await sleep(6000);
    const info = await page.evaluate(() => {
      const text = (document.body?.innerText || "").slice(0, 400);
      const anchors = Array.from(document.querySelectorAll("a[href]"));
      const jobLinks = anchors.filter((a) => /job_detail|\/job\/\d+|jobs\.zhaopin|\/jobdetail/i.test(a.getAttribute("href") || ""));
      return {
        title: document.title,
        text,
        jobs: jobLinks.length,
        sample: jobLinks.slice(0, 5).map((a) => (a.innerText || "").trim().split("\n")[0]),
        blocked: /验证|安全中心|访问异常|人机|滑块|captcha/i.test(document.body?.innerText || ""),
      };
    });
    Object.assign(out, info);
  } catch (error) {
    out.error = String(error).slice(0, 200);
  }
  console.log(JSON.stringify(out, null, 2));
  await page.close();
}
await browser.close();
})();
