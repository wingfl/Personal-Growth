import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** 把 ISO 时间截成「2026-11-20」；空值显示占位符 */
export function day(value?: string | null, fallback = "—") {
  if (!value) return fallback;
  return value.slice(0, 10);
}

export function pct(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value}%`;
}

export function relativeDays(value?: string | null) {
  if (!value) return null;
  const target = new Date(value.slice(0, 10) + "T00:00:00");
  if (Number.isNaN(target.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((today.getTime() - target.getTime()) / 86400000);
}
