// 招聘市场采集器入口：按目标方向 + 城市，每周拉一次岗位列表，落成 JSONL 供 app 侧 ingest。
// 用法：
//   node run.js --city 杭州 --city-code 080200 --roles "AI产品经理,产品设计,产品经理" --pages 3
//   node run.js --dry-run            # 只跑 1 页验证链路
const fs = require("fs");
const path = require("path");
const { launch } = require("./lib/browser");
const { openSession, collectKeyword } = require("./adapters/51job");

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (!a.startsWith("--")) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith("--")) {
      out[key] = next;
      i += 1;
    } else {
      out[key] = true;
    }
  }
  return out;
}

function weekTag(d = new Date()) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((t - yearStart) / 86400000 + 1) / 7);
  return `${t.getUTCFullYear()}W${String(week).padStart(2, "0")}`;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const city = args.city || "杭州";
  const cityCode = args["city-code"] || "080200";
  const roles = (args.roles || "AI产品经理,产品设计,产品经理").split(",").map((s) => s.trim()).filter(Boolean);
  const pages = Number(args.pages || 3);
  const pageSize = Number(args["page-size"] || 50);
  const delayMs = Number(args.delay || 2500);
  const dryRun = Boolean(args["dry-run"]);
  const outDir = path.resolve(__dirname, "..", "data", "market", "raw", weekTag());
  fs.mkdirSync(outDir, { recursive: true });

  const log = (msg) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${msg}`);
  log(`采集开始：${roles.join(" / ")} @ ${city}（${cityCode}），每方向 ${dryRun ? 1 : pages} 页`);

  const browser = await launch({ headless: true });
  const byId = new Map();
  const meta = { week: weekTag(), city, city_code: cityCode, roles, pages: dryRun ? 1 : pages, started_at: new Date().toISOString(), sources: {} };

  let session = await openSession(browser, { keyword: roles[0], cityCode });
  try {
    for (const role of roles) {
      log(`方向：${role}`);
      let res;
      try {
        res = await collectKeyword(session, { keyword: role, cityCode, pages: dryRun ? 1 : pages, pageSize, delayMs, log });
      } catch (err) {
        log(`  方向失败：${String(err).slice(0, 120)}`);
        meta.sources[role] = { total: null, pages: 0, fetched: 0, error: String(err).slice(0, 200) };
        continue;
      }
      if (res.total === 0) {
        // 偶尔会碰上会话失效：换一个新页面再试（旧页面不再复用）
        log("  该方向返回 0 条，重开会话后重试一次");
        const old = session;
        session = await openSession(browser, { keyword: role, cityCode });
        await old.close().catch(() => {});
        res = await collectKeyword(session, { keyword: role, cityCode, pages: dryRun ? 1 : pages, pageSize, delayMs, log });
      }
      meta.sources[role] = { total: res.total, pages: res.pages, fetched: res.items.length };
      for (const item of res.items) {
        const key = `${item.platform}:${item.external_id}`;
        if (byId.has(key)) {
          byId.get(key).matched_keywords.push(role);
        } else {
          byId.set(key, { ...item, matched_keywords: [role] });
        }
      }
      await new Promise((r) => setTimeout(r, 2500));
    }
  } finally {
    await session.close().catch(() => {});
    await browser.close();
  }

  let items = Array.from(byId.values());
  // 从最新发布开始用：先按发布日期倒序，必要时只保留最近 N 天
  items.sort((a, b) => String(b.published_at || "").localeCompare(String(a.published_at || "")));
  if (sinceDays > 0) {
    const floor = new Date(Date.now() - sinceDays * 86400000).toISOString().slice(0, 10);
    const before = items.length;
    items = items.filter((x) => !x.published_at || x.published_at >= floor);
    log(`按 ${sinceDays} 天过滤：${before} → ${items.length} 条`);
  }
  const stamp = new Date().toISOString().slice(0, 10);
  const outFile = path.join(outDir, `51job-${city}-${stamp}.jsonl`);
  fs.writeFileSync(outFile, items.map((x) => JSON.stringify(x)).join("\n") + (items.length ? "\n" : ""), "utf8");
  meta.finished_at = new Date().toISOString();
  meta.total_unique = items.length;
  meta.newest_published_at = items[0] && items[0].published_at || null;
  fs.writeFileSync(path.join(outDir, "meta.json"), JSON.stringify(meta, null, 2), "utf8");
  log(`完成：${items.length} 条唯一岗位 → ${outFile}`);
  log(`覆盖：${meta.sources && Object.entries(meta.sources).map(([k, v]) => `${k} ${v.fetched}/${v.total ?? "?"}`).join("；")}`);
}

main().catch((err) => {
  console.error("采集失败：", err && err.stack ? err.stack : err);
  process.exit(1);
});
