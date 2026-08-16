import { convertCurrency } from "../lib/format";

// Percentage of the annual title target achieved. `afypUsd` is the ledger-base
// (USD) AFYP; `targetHkd` is the rank's annual target in HKD. Returns null when
// no target is set for the rank.
export function targetPct(afypUsd: number, targetHkd: number): number | null {
  if (!targetHkd || targetHkd <= 0) return null;
  const achievedHkd = convertCurrency(afypUsd, "USD", "HKD");
  return (achievedHkd / targetHkd) * 100;
}

// Compact progress readout used inside the agency summary table and the
// hierarchy nodes: a slim bar plus the percentage achieved. Rendered with inline
// spans so it is valid phrasing content inside the hierarchy's <button> node.
export default function TargetProgress({
  afypUsd, targetHkd, width = 120,
}: {
  afypUsd: number; targetHkd: number; width?: number;
}) {
  const pctVal = targetPct(afypUsd, targetHkd);
  if (pctVal == null) return <span className="muted">—</span>;
  const barPct = Math.min(100, Math.max(0, pctVal));
  const done = pctVal >= 100;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8, verticalAlign: "middle" }}>
      <span style={{ display: "inline-block", width, height: 8, background: "var(--line)", borderRadius: 999, overflow: "hidden" }}>
        <span style={{ display: "block", width: `${barPct}%`, height: "100%", background: done ? "var(--good)" : "var(--accent)", borderRadius: 999 }} />
      </span>
      <span style={{ fontSize: 12, minWidth: 40, textAlign: "right", fontWeight: 600, color: done ? "var(--good)" : "inherit" }}>
        {pctVal.toFixed(0)}%
      </span>
    </span>
  );
}
