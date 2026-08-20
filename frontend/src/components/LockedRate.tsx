import { pct } from "../lib/format";
import { useI18n } from "../i18n/LanguageContext";

/**
 * Shows the commission rate locked onto a transaction at creation. A per-year
 * (insurance) deal shows the Yr1 rate with a "per-year" marker (full schedule on
 * hover); a flat deal shows the single rate. Legacy deals with no lock show —.
 */
export default function LockedRate({ base, years }:
  { base?: string | null; years?: string[] | null }) {
  const { t } = useI18n();
  if (years && years.length) {
    const full = years.map(pct).join(" / ");
    return (
      <span title={full}>
        {pct(years[0])}
        <span className="muted" style={{ fontSize: 11, marginLeft: 4 }}>· {t("txn.perYear")}</span>
      </span>
    );
  }
  if (base != null && String(base).trim() !== "") return <>{pct(base)}</>;
  return <span className="muted">—</span>;
}
