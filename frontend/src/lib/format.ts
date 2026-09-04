import { getActiveLang, getActiveCurrency, translate } from "../i18n/LanguageContext";

function numberLocale(): string {
  return getActiveLang() === "zh-Hant" ? "zh-Hant-HK" : "en-US";
}

// FX rates relative to 1 USD. Fixed demo rates — the system carries no live FX.
export const FX_RATES: Record<string, number> = { USD: 1, HKD: 7.8, EUR: 0.92, GBP: 0.79 };

export function convertCurrency(amount: number, from: string, to: string): number {
  const rf = FX_RATES[from] ?? 1;
  const rt = FX_RATES[to] ?? 1;
  return (amount / rf) * rt;
}

// Format money in the system-wide display currency, converting from the amount's
// source currency (default USD, the base the ledger is computed in).
export function money(n: number | string, sourceCurrency = "USD"): string {
  const v = typeof n === "string" ? Number(n) : n;
  if (v == null || !Number.isFinite(v)) return "—";
  const display = getActiveCurrency();
  return new Intl.NumberFormat(numberLocale(), {
    style: "currency",
    currency: display,
    minimumFractionDigits: 2,
  }).format(convertCurrency(v, sourceCurrency, display));
}

// Format a number as-is in a fixed currency (no FX conversion, ignores the
// display-currency toggle). Used where an amount is entered in one known
// currency, e.g. 預計AFYP in HKD.
export function moneyFixed(n: number | string, currency: string): string {
  const v = typeof n === "string" ? Number(n) : n;
  if (v == null || !Number.isFinite(v)) return "—";
  return new Intl.NumberFormat(numberLocale(), {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(v);
}

// Localized date+time for an ISO timestamp (UTC from the API → viewer's local
// time). Returns an em dash for null/blank/invalid values.
// Normalise an API value to a spec-valid ISO string. The API stores UTC; a value
// with no zone is treated as UTC. A date-only value ("YYYY-MM-DD") must get a full
// "T00:00:00Z" — appending a bare "Z" ("2026-09-10Z") is invalid and iOS Safari
// (unlike Chrome) parses it as Invalid Date, so dates vanished on the H5 client.
function _toUtcIso(iso: string): string {
  if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso)) return iso;   // already zoned
  return iso.includes("T") ? `${iso}Z` : `${iso}T00:00:00Z`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(_toUtcIso(iso));
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(numberLocale(), { dateStyle: "medium", timeStyle: "short" });
}

export function dateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(_toUtcIso(iso));
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(numberLocale(), { dateStyle: "medium" });
}

export function pct(rate: number | string): string {
  const v = typeof rate === "string" ? Number(rate) : rate;
  if (v == null || !Number.isFinite(v)) return "—";
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
