// 薪资字符串解析：把「2.1-2.5万·14薪」「8千-1.2万」「20-30万/年」转成月薪区间（元）。
// 解析不了（面议、元/天、时薪）返回 null 字段，由上层标记 salary_text 原样保留。

const UNIT = { 千: 1000, 万: 10000, k: 1000, K: 1000, 元: 1 };

function toNumber(raw) {
  if (raw == null) return null;
  const s = String(raw).trim();
  if (!s) return null;
  const m = s.match(/^(\d+(?:\.\d+)?)\s*(千|万|k|K|元)?$/);
  if (!m) return null;
  const value = parseFloat(m[1]);
  if (!Number.isFinite(value)) return null;
  const unit = m[2] || "";
  return value * (UNIT[unit] || 1);
}

/**
 * @returns {{min:number|null,max:number|null,months:number,text:string}}
 */
function parseSalary(text) {
  const raw = (text || "").trim();
  const result = { min: null, max: null, months: 12, text: raw };
  if (!raw) return result;

  // 14薪 / 13薪
  const monthsMatch = raw.match(/(\d{1,2})\s*薪/);
  if (monthsMatch) {
    const n = parseInt(monthsMatch[1], 10);
    if (n >= 12 && n <= 24) result.months = n;
  }

  // 年薪 / 元/天 / 时薪 不折算，保留原文
  if (/\/年|年薪|元\/天|元\/时|小时/.test(raw)) return result;

  const body = raw.replace(/·?\d{1,2}\s*薪/g, "").replace(/[（(].*?[)）]/g, "").trim();

  // 区间 a-b单位
  const range = body.match(/^(\d+(?:\.\d+)?)\s*(千|万|k|K|元)?\s*[-~—至]\s*(\d+(?:\.\d+)?)\s*(千|万|k|K|元)?$/);
  if (range) {
    const unit = range[4] || range[2] || "元";
    const factor = UNIT[unit] || 1;
    const min = parseFloat(range[1]) * factor;
    const max = parseFloat(range[3]) * factor;
    if (Number.isFinite(min) && Number.isFinite(max) && min > 0 && max >= min) {
      result.min = Math.round(min);
      result.max = Math.round(max);
    }
    return result;
  }

  // 单值
  const single = toNumber(body);
  if (single != null) {
    result.min = Math.round(single);
    result.max = Math.round(single);
  }
  return result;
}

module.exports = { parseSalary, toNumber };
