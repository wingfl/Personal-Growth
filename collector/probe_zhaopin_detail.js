// 探针：智联岗位详情页是否给薪资与 JD 正文。
const { launch, newPage, sleep } = require("./lib/browser.js");

(async () => {
  const browser = await launch({ headless: true });
  const page = await newPage(browser);
  const url = "https://www.zhaopin.com/jobdetail/CCL1486834490J41053156402.htm";
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
  await sleep(6000);
  const info = await page.evaluate(() => {
    const text = (document.body?.innerText || "").replace(/\n{2,}/g, "\n");
    return {
      title: document.title,
      url: location.href,
      head: text.slice(0, 600),
      hasSalary: /\d+\s*[-~]\s*\d+\s*[万千]|元\/月|K·|薪/.test(text),
      hasLogin: /登录|注册/.test(text),
      bodyLen: text.length,
    };
  });
  console.log(JSON.stringify(info, null, 2));
  await browser.close();
})();
