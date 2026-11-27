// 极简浏览器封装：用本机 Edge（不需要下载 Chromium），带一点反自动化特征处理。
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");

const EDGE_CANDIDATES = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  "/usr/bin/microsoft-edge",
];

function findEdge() {
  for (const p of EDGE_CANDIDATES) {
    if (fs.existsSync(p)) return p;
  }
  throw new Error("找不到 Microsoft Edge，可用环境变量 EDGE_PATH 指定");
}

async function launch({ headless = true } = {}) {
  const executablePath = process.env.EDGE_PATH || findEdge();
  return puppeteer.launch({
    executablePath,
    headless: headless ? "new" : false,
    args: [
      "--no-sandbox",
      "--disable-blink-features=AutomationControlled",
      "--disable-features=IsolateOrigins,site-per-process",
      "--lang=zh-CN",
      "--window-size=1440,1000",
    ],
    defaultViewport: { width: 1440, height: 1000 },
    protocolTimeout: 120000,
  });
}

async function newPage(browser) {
  const page = await browser.newPage();
  await page.setUserAgent(
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
  );
  await page.setExtraHTTPHeaders({ "Accept-Language": "zh-CN,zh;q=0.9" });
  return page;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 写文件时自动建目录。 */
function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
  return p;
}

module.exports = { launch, newPage, sleep, ensureDir, findEdge, path };
