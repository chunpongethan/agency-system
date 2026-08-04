import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { money, currentPeriod } from "../lib/format";
import StatusBadge from "../components/StatusBadge";

export default function Dashboard() {
  const { me } = useAuth();
  const period = currentPeriod();
  const agentId = me!.id;

  const statement = useQuery({
    queryKey: ["statement", agentId, period.ym],
    queryFn: () => api.agentStatement(agentId, period.start, period.end),
  });
  const clients = useQuery({
    queryKey: ["agentClients", agentId],
    queryFn: () => api.agentClients(agentId),
  });
  const txns = useQuery({
    queryKey: ["agentTxns", agentId],
    queryFn: () => api.agentTransactions(agentId),
  });

  return (
    <div>
      <h1 className="page-title">Dashboard</h1>
      <p className="page-sub">
        {me!.name} · this period ({period.ym})
      </p>

      <div className="grid cols-3">
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
          <div className="label">Total earned</div>
          <div className="value">
            {statement.data ? money(statement.data.grand_total) : "—"}
          </div>
        </div>
      </div>

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
                <th>Ref</th><th>Date</th><th className="num">Notional</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {txns.data?.slice(0, 8).map((t) => (
                <tr key={t.id}>
                  <td>{t.ref}</td>
                  <td className="muted">{t.trade_date}</td>
                  <td className="num">{money(t.notional, t.currency)}</td>
                  <td><StatusBadge status={t.status} /></td>
                </tr>
              ))}
              {txns.data?.length === 0 && (
                <tr><td className="muted">No transactions yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
