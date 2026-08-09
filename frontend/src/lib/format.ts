import { getActiveLang, translate } from "../i18n/LanguageContext";

function numberLocale(): string {
  return getActiveLang() === "zh-Hant" ? "zh-Hant-HK" : "en-US";
}

export function money(n: number | string, currency = "USD"): string {
  const v = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat(numberLocale(), {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(v);
}

export function pct(rate: number | string): string {
  const v = typeof rate === "string" ? Number(rate) : rate;
  return `${(v * 100).toFixed(2)}%`;
}

const iso = (d: Date) => d.toISOString().slice(0, 10);

// Current calendar month as [start, end] ISO date strings, plus YYYY-MM.
export function currentPeriod(): { start: string; end: string; ym: string } {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth(); // 0-based
  const start = new Date(y, m, 1);
  const end = new Date(y, m + 1, 0);
  const ym = `${y}-${String(m + 1).padStart(2, "0")}`;
  return { start: iso(start), end: iso(end), ym };
}

// Year-to-date: Jan 1 of the current year through today.
export function yearToDate(): { start: string; end: string; label: string } {
  const now = new Date();
  return {
    start: iso(new Date(now.getFullYear(), 0, 1)),
    end: iso(now),
    label: `${now.getFullYear()} ${translate("common.ytd")}`,
  };
}
