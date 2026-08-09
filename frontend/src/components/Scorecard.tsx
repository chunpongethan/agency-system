import { money } from "../lib/format";
import { useI18n } from "../i18n/LanguageContext";
import type { AgentScorecard } from "../api/types";

const ROWS: { labelKey: string; key: "afyp" | "direct" | "override" }[] = [
  { labelKey: "scorecard.afyp", key: "afyp" },
  { labelKey: "scorecard.comm", key: "direct" },
  { labelKey: "scorecard.override", key: "override" },
];

// Identity header (agent / manager / district) plus a table of AFYP, direct
// commission and override across YTD / last month / current month.
export default function Scorecard({
  data,
  compact = false,
}: {
  data: AgentScorecard;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const p = data.periods;
  return (
    <div className="card" style={compact ? { marginBottom: 14 } : undefined}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 24, alignItems: "baseline", marginBottom: 14 }}>
        <div>
          <span className="muted" style={{ fontSize: 12 }}>{t("scorecard.agent")}</span><br />
          <strong>{data.agent.name}</strong>{" "}
          <span className="muted">({data.agent.code})</span>
        </div>
        <div>
          <span className="muted" style={{ fontSize: 12 }}>{t("scorecard.manager")}</span><br />
          {data.manager
            ? <>{data.manager.name} <span className="muted">({data.manager.code})</span></>
            : <span className="muted">—</span>}
        </div>
        <div>
          <span className="muted" style={{ fontSize: 12 }}>{t("scorecard.district")}</span><br />
          {data.district
            ? <span className="badge unit">{data.district}</span>
            : <span className="muted">—</span>}
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th></th>
            <th className="num">{t("common.ytd")}</th>
            <th className="num">{t("common.lastMonth")}</th>
            <th className="num">{t("common.currentMonth")}</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.key}>
              <td><strong>{t(r.labelKey)}</strong></td>
              <td className="num">{money(p.ytd[r.key])}</td>
              <td className="num">{money(p.last_month[r.key])}</td>
              <td className="num">{money(p.current_month[r.key])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
