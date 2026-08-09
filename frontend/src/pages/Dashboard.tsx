import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { money, currentPeriod, yearToDate } from "../lib/format";
import { productTypeLabel, productDetails } from "../lib/agency";
import StatusBadge from "../components/StatusBadge";
import Scorecard from "../components/Scorecard";

type View = "month" | "ytd";

export default function Dashboard() {
  const { me } = useAuth();
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
  const statement = useQuery({
    queryKey: ["statement", agentId, view, win.start, win.end],
    queryFn: () => api.agentStatement(agentId, win.start, win.end),
  });
  const team = useQuery({
    queryKey: ["team", view, win.start, win.end],
    queryFn: () => api.agencySummary(win.start, win.end),
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

  const teamTotal = (team.data ?? []).reduce((s, r) => s + r.total, 0);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-sub">{me!.name} · {win.label}</p>
        </div>
        <div className="seg">
          <button className={view === "month" ? "active" : ""} onClick={() => setView("month")}>
            Current month
          </button>
          <button className={view === "ytd" ? "active" : ""} onClick={() => setView("ytd")}>
            Year to date
          </button>
        </div>
      </div>

      {scorecard.data && (
        <div style={{ marginTop: 18 }}>
          <Scorecard data={scorecard.data} />
        </div>
      )}

      <div className="grid cols-3" style={{ marginTop: 18 }}>
        <div className="stat">
          <div className="label">Direct commission</div>
          <div className="value good">
            {statement.data ? money(statement.data.direct_total) : "—"}
          </div>
        </div>
        <div className="stat">
          <div className="label">Override commission</div>
          <div className="value good">
            {statement.data ? money(statement.data.override_total) : "—"}
          </div>
        </div>
        <div className="stat">
          <div className="label">Total earned · {win.label}</div>
          <div className="value">
            {statement.data ? money(statement.data.grand_total) : "—"}
          </div>
        </div>
      </div>

      {isManager && (
        <div className="card" style={{ marginTop: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <h2>Team performance</h2>
            <span className="muted" style={{ fontSize: 13 }}>
              {win.label} · {(team.data?.length ?? 0)} in line · total {money(teamTotal)}
            </span>
          </div>
          {team.isLoading && <div className="spinner">Loading…</div>}
          <table>
            <thead>
              <tr>
                <th>#</th><th>Agent</th><th>Code</th><th>Level</th>
                <th className="num">Production</th><th className="num">Share</th>
              </tr>
            </thead>
            <tbody>
              {team.data?.map((r, i) => (
                <tr key={r.agent_id}>
                  <td className="muted">{i + 1}</td>
                  <td>{r.name}{r.agent_id === agentId ? " (you)" : ""}</td>
                  <td className="muted">{r.code}</td>
                  <td>L{r.level}</td>
                  <td className="num">{money(r.total)}</td>
                  <td className="num muted">
                    {teamTotal > 0 ? `${((r.total / teamTotal) * 100).toFixed(1)}%` : "—"}
                  </td>
                </tr>
              ))}
              {team.data?.length === 0 && (
                <tr><td colSpan={6} className="muted">No team production in this window.</td></tr>
              )}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            Production is commission earned by each agent in your line (direct + overrides).
            See the <Link to="/hierarchy">Hierarchy</Link> for the rolled-up org tree.
          </p>
        </div>
      )}

      {isManager && (
        <div style={{ marginTop: 18 }}>
          <h2 style={{ fontSize: 15, margin: "0 0 12px" }}>Team member scorecards</h2>
          {teamCards.isLoading && <div className="spinner">Loading…</div>}
          {(teamCards.data ?? [])
            .filter((c) => c.agent.id !== agentId)
            .map((c) => <Scorecard key={c.agent.id} data={c} compact />)}
          {teamCards.data && teamCards.data.filter((c) => c.agent.id !== agentId).length === 0 && (
            <div className="card"><span className="muted">No team members in your line yet.</span></div>
          )}
        </div>
      )}

      <div className="grid cols-2" style={{ marginTop: 18 }}>
        <div className="card">
          <h2>My clients ({clients.data?.length ?? 0})</h2>
          {clients.isLoading && <div className="spinner">Loading…</div>}
          <table>
            <tbody>
              {clients.data?.map((c) => (
                <tr key={c.id}>
                  <td><Link to={`/clients/${c.id}`}>{c.name}</Link></td>
                  <td className="muted">{c.ref}</td>
                  <td className="muted">{c.risk_profile ?? "—"}</td>
                </tr>
              ))}
              {clients.data?.length === 0 && (
                <tr><td className="muted">No clients yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h2>Recent transactions</h2>
          {txns.isLoading && <div className="spinner">Loading…</div>}
          <table>
            <thead>
              <tr>
                <th>Ref</th><th>Date</th><th>Product</th><th className="num">Notional</th><th>Status</th>
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
                <tr><td colSpan={5} className="muted">No transactions yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
