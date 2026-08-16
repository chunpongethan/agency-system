import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/LanguageContext";
import { money, moneyFixed, convertCurrency, currentPeriod, yearToDate } from "../lib/format";
import { productTypeLabel, productDetails } from "../lib/agency";
import { riskLabel } from "../i18n/labels";
import { titleLabel } from "../lib/titles";
import StatusBadge from "../components/StatusBadge";
import Scorecard from "../components/Scorecard";

type View = "month" | "ytd";

export default function Dashboard() {
  const { me } = useAuth();
  const { t } = useI18n();
  const agentId = me!.id;
  const isManager = me!.role === "manager";

  const [view, setView] = useState<View>("month");
  const month = currentPeriod();
  const ytd = yearToDate();
  const win = view === "ytd"
    ? { start: ytd.start, end: ytd.end, label: ytd.label }
    : { start: month.start, end: month.end, label: month.ym };

  const scorecard = useQuery({
    queryKey: ["scorecard", agentId],
    queryFn: () => api.agentScorecard(agentId),
  });
  const titleTargets = useQuery({ queryKey: ["titleTargets"], queryFn: () => api.titleTargets() });
  const statement = useQuery({
    queryKey: ["statement", agentId, view, win.start, win.end],
    queryFn: () => api.agentStatement(agentId, win.start, win.end),
  });
  const team = useQuery({
    queryKey: ["team", view, win.start, win.end],
    queryFn: () => api.agencySummary(win.start, win.end),
    enabled: isManager,
  });
  // A manager's target is measured against their whole team's YTD production
  // (self + all downlines), independent of the month/YTD view toggle. The
  // agency summary is already scoped to the manager's subtree.
  const teamYtd = useQuery({
    queryKey: ["teamYtdTarget", ytd.start, ytd.end],
    queryFn: () => api.agencySummary(ytd.start, ytd.end),
    enabled: isManager,
  });
  const teamCards = useQuery({
    queryKey: ["teamScorecards"],
    queryFn: () => api.teamScorecards(),
    enabled: isManager,
  });
  const clients = useQuery({
    queryKey: ["agentClients", agentId],
    queryFn: () => api.agentClients(agentId),
  });
  const txns = useQuery({
    queryKey: ["agentTxns", agentId],
    queryFn: () => api.agentTransactions(agentId),
  });
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.products() });
  const productsById = new Map((products.data ?? []).map((p) => [p.id, p]));

  // Annual AFYP target progress for the agent's 職級, in HKD. Agents are scored
  // on their own YTD AFYP; managers on their whole team's YTD AFYP.
  const myTargetHkd = (titleTargets.data ?? []).find((tt) => tt.title === me!.title)?.target_afyp ?? 0;
  const ownAfypUsd = scorecard.data?.periods.ytd.afyp ?? 0;
  const teamAfypUsd = (teamYtd.data ?? []).reduce((s, r) => s + r.afyp, 0);
  const achievedAfypUsd = isManager ? teamAfypUsd : ownAfypUsd;
  const achievedHkd = convertCurrency(achievedAfypUsd, "USD", "HKD");
  const targetRawPct = myTargetHkd > 0 ? (achievedHkd / myTargetHkd) * 100 : 0;
  const targetBarPct = Math.min(100, targetRawPct);

  const teamTotal = (team.data ?? []).reduce((s, r) => s + r.total, 0);
  const teamAfyp = (team.data ?? []).reduce((s, r) => s + r.afyp, 0);
  const teamDirect = (team.data ?? []).reduce((s, r) => s + r.direct, 0);
  const teamOverride = (team.data ?? []).reduce((s, r) => s + r.override, 0);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <div>
          <h1 className="page-title">{t("dashboard.title")}</h1>
          <p className="page-sub">{me!.name} · {win.label}</p>
        </div>
        <div className="seg">
          <button className={view === "month" ? "active" : ""} onClick={() => setView("month")}>
            {t("dashboard.segMonth")}
          </button>
          <button className={view === "ytd" ? "active" : ""} onClick={() => setView("ytd")}>
            {t("dashboard.segYtd")}
          </button>
        </div>
      </div>

      {me!.title && (
        <div className="card" style={{ marginTop: 18, borderColor: myTargetHkd > 0 && targetRawPct >= 100 ? "var(--good)" : undefined }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
            <h2 style={{ margin: 0 }}>{t("dashboard.targetTitle")}</h2>
            <span className="badge title">{titleLabel(me!.title)}</span>
          </div>
          {myTargetHkd > 0 ? (
            <>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 20, flexWrap: "wrap", marginTop: 14 }}>
                <div>
                  <div className="label">{isManager ? t("dashboard.targetAchievedTeam") : t("dashboard.targetAchieved")}</div>
                  <div style={{ fontSize: 30, fontWeight: 800, color: "var(--good)", lineHeight: 1.1 }}>
                    {moneyFixed(achievedHkd, "HKD")}
                  </div>
                </div>
                <div style={{ fontSize: 24, color: "var(--muted)", paddingBottom: 4 }}>/</div>
                <div>
                  <div className="label">{t("dashboard.targetGoal")}</div>
                  <div style={{ fontSize: 30, fontWeight: 800, lineHeight: 1.1 }}>
                    {moneyFixed(myTargetHkd, "HKD")}
                  </div>
                </div>
                <div style={{ marginLeft: "auto", textAlign: "right" }}>
                  <div className="label">{t("dashboard.targetProgress")}</div>
                  <div style={{ fontSize: 34, fontWeight: 800, lineHeight: 1, color: targetRawPct >= 100 ? "var(--good)" : "var(--accent)" }}>
                    {targetRawPct.toFixed(1)}%
                  </div>
                </div>
              </div>
              <div style={{ background: "var(--line)", borderRadius: 999, height: 14, overflow: "hidden", marginTop: 14 }}>
                <div style={{ width: `${targetBarPct}%`, height: "100%", background: targetRawPct >= 100 ? "var(--good)" : "var(--accent)", borderRadius: 999, transition: "width .3s" }} />
              </div>
            </>
          ) : (
            <p className="muted" style={{ fontSize: 13, margin: "8px 0 0" }}>{t("dashboard.targetNone")}</p>
          )}
        </div>
      )}

      {scorecard.data && (
        <div style={{ marginTop: 18 }}>
          <Scorecard data={scorecard.data} />
        </div>
      )}

      <div className="grid cols-3" style={{ marginTop: 18 }}>
        <div className="stat">
          <div className="label">{t("dashboard.directCommission")}</div>
          <div className="value good">
            {statement.data ? money(statement.data.direct_total) : "—"}
          </div>
        </div>
        <div className="stat">
          <div className="label">{t("dashboard.overrideCommission")}</div>
          <div className="value good">
            {statement.data ? money(statement.data.override_total) : "—"}
          </div>
        </div>
        <div className="stat">
          <div className="label">{t("dashboard.totalEarned", { label: win.label })}</div>
          <div className="value">
            {statement.data ? money(statement.data.grand_total) : "—"}
          </div>
        </div>
      </div>

      {isManager && (
        <div className="card" style={{ marginTop: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <h2>{t("dashboard.teamPerformance")}</h2>
            <span className="muted" style={{ fontSize: 13 }}>
              {t("dashboard.teamMeta", { label: win.label, count: team.data?.length ?? 0, total: money(teamTotal) })}
            </span>
          </div>
          {team.isLoading && <div className="spinner">{t("common.loading")}</div>}
          <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>{t("dashboard.thRank")}</th><th>{t("common.agent")}</th><th>{t("common.code")}</th><th>{t("common.level")}</th>
                <th className="num">{t("common.afyp")}</th>
                <th className="num">{t("common.commission")}</th>
                <th className="num">{t("common.override")}</th>
                <th className="num">{t("dashboard.thProduction")}</th><th className="num">{t("dashboard.thShare")}</th>
              </tr>
            </thead>
            <tbody>
              {team.data?.map((r, i) => (
                <tr key={r.agent_id}>
                  <td className="muted">{i + 1}</td>
                  <td>{r.name}{r.agent_id === agentId ? t("dashboard.you") : ""}</td>
                  <td className="muted">{r.code}</td>
                  <td>L{r.level}</td>
                  <td className="num">{money(r.afyp)}</td>
                  <td className="num">{money(r.direct)}</td>
                  <td className="num">{money(r.override)}</td>
                  <td className="num">{money(r.total)}</td>
                  <td className="num muted">
                    {teamTotal > 0 ? `${((r.total / teamTotal) * 100).toFixed(1)}%` : "—"}
                  </td>
                </tr>
              ))}
              {team.data?.length === 0 && (
                <tr><td colSpan={9} className="muted">{t("dashboard.noTeamProduction")}</td></tr>
              )}
            </tbody>
            {team.data && team.data.length > 0 && (
              <tfoot>
                <tr style={{ fontWeight: 700 }}>
                  <td colSpan={4}>{t("hierarchy.teamTotal")}</td>
                  <td className="num">{money(teamAfyp)}</td>
                  <td className="num">{money(teamDirect)}</td>
                  <td className="num">{money(teamOverride)}</td>
                  <td className="num">{money(teamTotal)}</td>
                  <td className="num muted">100%</td>
                </tr>
              </tfoot>
            )}
          </table>
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            {t("dashboard.teamNote1")}<Link to="/hierarchy">{t("nav.hierarchy")}</Link>{t("dashboard.teamNote2")}
          </p>
        </div>
      )}

      {isManager && (
        <div style={{ marginTop: 18 }}>
          <h2 style={{ fontSize: 15, margin: "0 0 12px" }}>{t("dashboard.teamScorecards")}</h2>
          {teamCards.isLoading && <div className="spinner">{t("common.loading")}</div>}
          {(teamCards.data ?? [])
            .filter((c) => c.agent.id !== agentId)
            .map((c) => <Scorecard key={c.agent.id} data={c} compact />)}
          {teamCards.data && teamCards.data.filter((c) => c.agent.id !== agentId).length === 0 && (
            <div className="card"><span className="muted">{t("dashboard.noTeamMembers")}</span></div>
          )}
        </div>
      )}

      <div className="grid cols-2" style={{ marginTop: 18 }}>
        <div className="card">
          <h2>{t("dashboard.myClients", { count: clients.data?.length ?? 0 })}</h2>
          {clients.isLoading && <div className="spinner">{t("common.loading")}</div>}
          <table>
            <tbody>
              {clients.data?.map((c) => (
                <tr key={c.id}>
                  <td><Link to={`/clients/${c.id}`}>{c.name}</Link></td>
                  <td className="muted">{c.ref}</td>
                  <td className="muted">{riskLabel(c.risk_profile)}</td>
                </tr>
              ))}
              {clients.data?.length === 0 && (
                <tr><td className="muted">{t("dashboard.noClients")}</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h2>{t("dashboard.recentTxns")}</h2>
          {txns.isLoading && <div className="spinner">{t("common.loading")}</div>}
          <table>
            <thead>
              <tr>
                <th>{t("common.ref")}</th><th>{t("common.date")}</th><th>{t("common.product")}</th><th className="num">{t("common.notional")}</th><th>{t("common.status")}</th>
              </tr>
            </thead>
            <tbody>
              {txns.data?.slice(0, 8).map((t) => {
                const p = productsById.get(t.product_id);
                const details = productDetails(p);
                return (
                  <tr key={t.id}>
                    <td>{t.ref}</td>
                    <td className="muted">{t.trade_date}</td>
                    <td>
                      <div>{p ? p.name : `#${t.product_id}`}</div>
                      <div className="muted" style={{ fontSize: 11 }}>
                        {p && <span className="badge role" style={{ marginRight: 6 }}>{productTypeLabel(p.type)}</span>}
                        {details}
                      </div>
                    </td>
                    <td className="num">{money(t.notional, t.currency)}</td>
                    <td><StatusBadge status={t.status} /></td>
                  </tr>
                );
              })}
              {txns.data?.length === 0 && (
                <tr><td colSpan={5} className="muted">{t("dashboard.noTxns")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
