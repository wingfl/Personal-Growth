// 登录一次：用固定浏览器配置目录打开招聘站点，人工登录后 cookie 会留在本地。
// 用法：node login.js [--profile ../data/browser-profile] [--seconds 180]
const path = require("path");
const { launch, newPage, sleep } = require("./lib/browser.js");

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

(async () => {
  const profile = arg("profile", path.join(__dirname, "..", "data", "browser-profile"));
  const seconds = Number(arg("seconds", "180"));
  const browser = await launch({ headless: false, profile });
  const page = await newPage(browser);
  await page.goto("https://www.zhipin.com/", { waitUntil: "domcontentloaded" }).catch(() => {});
  console.log("浏览器已打开，配置目录：", profile);
  console.log("请手动登录 BOSS / 智联 / 51job，登录完成后关闭浏览器窗口即可。");
  const started = Date.now();
  while (Date.now() - started < seconds * 1000) {
    await sleep(2000);
    if (browser.process() === null) break;
  }
  await browser.close().catch(() => {});
  console.log("已保存登录状态。");
})();
