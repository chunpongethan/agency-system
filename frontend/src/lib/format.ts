export function money(n: number | string, currency = "USD"): string {
  const v = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(v);
}

export function pct(rate: number | string): string {
  const v = typeof rate === "string" ? Number(rate) : rate;
  return `${(v * 100).toFixed(2)}%`;
}

// Current calendar month as [start, end] ISO date strings, plus YYYY-MM.
export function currentPeriod(): { start: string; end: string; ym: string } {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth(); // 0-based
  const start = new Date(y, m, 1);
  const end = new Date(y, m + 1, 0);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const ym = `${y}-${String(m + 1).padStart(2, "0")}`;
  return { start: iso(start), end: iso(end), ym };
}
