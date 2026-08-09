import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { api, downloadFile } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { money, currentPeriod } from "../lib/format";
import { productTypeLabel } from "../lib/agency";
import DataTable from "../components/DataTable";
import type { AgencySummaryRow } from "../api/types";

export default function Reports() {
  const { me } = useAuth();
  const p = currentPeriod();
  const [start, setStart] = useState(p.start);
  const [end, setEnd] = useState(p.end);
  const [agentId, setAgentId] = useState(me!.id);

  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api.agents() });
  const statement = useQuery({
    queryKey: ["report-agent", agentId, start, end],
    queryFn: () => api.agentStatement(agentId, start, end),
  });
  const summary = useQuery({
    queryKey: ["report-agency", start, end],
    queryFn: () => api.agencySummary(start, end),
  });
  const mix = useQuery({
    queryKey: ["report-mix", start, end],
    queryFn: () => api.productMix(start, end),
  });

  const qsWin = `start=${start}&end=${end}`;

  const summaryColumns = useMemo<ColumnDef<AgencySummaryRow, any>[]>(() => [
    { header: "Agent", accessorKey: "name" },
    { header: "Code", accessorKey: "code" },
    { header: "Level", accessorFn: (r) => `L${r.level}`, id: "level" },
    {
      header: "Total", accessorKey: "total", meta: { num: true },
      cell: (ctx) => money(ctx.getValue() as number),
    },
  ], []);

  return (
    <div>
      <h1 className="page-title">Reports</h1>
      <p className="page-sub">Agent statements and the agency summary</p>

      <div className="card">
        <div className="row">
          <div>
            <label>Agent</label>
            <select value={agentId} onChange={(e) => setAgentId(Number(e.target.value))}>
              {agents.data?.map((a) => (
                <option key={a.id} value={a.id}>{a.name} ({a.code})</option>
              ))}
            </select>
          </div>
          <div>
            <label>From</label>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div>
            <label>To</label>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2>Agent statement</h2>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="ghost"
              onClick={() => downloadFile(`/reports/agent/${agentId}/export?format=csv&${qsWin}`,
                `statement_${agentId}.csv`)}>Download CSV</button>
            <button className="ghost"
              onClick={() => downloadFile(`/reports/agent/${agentId}/export?format=pdf&${qsWin}`,
                `statement_${agentId}.pdf`)}>Download PDF</button>
          </div>
        </div>
        {statement.isLoading && <div className="spinner">Loading…</div>}
        {statement.data && (
          <>
            <div className="grid cols-3" style={{ marginBottom: 14 }}>
              <div className="stat">
                <div className="label">Direct</div>
                <div className="value good">{money(statement.data.direct_total)}</div>
              </div>
              <div className="stat">
                <div className="label">Override</div>
                <div className="value good">{money(statement.data.override_total)}</div>
              </div>
              <div className="stat">
                <div className="label">Grand total</div>
                <div className="value">{money(statement.data.grand_total)}</div>
              </div>
            </div>
            <table>
              <thead>
                <tr><th>Kind</th><th>Product type</th><th className="num">Count</th><th className="num">Amount</th></tr>
              </thead>
              <tbody>
                {statement.data.lines.map((l, i) => (
                  <tr key={i}>
                    <td>{l.kind}</td>
                    <td>{l.product_type}</td>
                    <td className="num">{l.count}</td>
                    <td className="num">{money(l.amount)}</td>
                  </tr>
                ))}
                {statement.data.lines.length === 0 && (
                  <tr><td colSpan={4} className="muted">No commission in this window.</td></tr>
                )}
              </tbody>
            </table>
          </>
        )}
      </div>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h2>Product mix</h2>
          <span className="muted" style={{ fontSize: 13 }}>
            Settled production by product · AFYP share
          </span>
        </div>
        {mix.isLoading && <div className="spinner">Loading…</div>}
        {mix.data && (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Product</th><th>Type</th>
                  <th className="num">#</th>
                  <th className="num">Notional</th>
                  <th className="num">AFYP</th>
                  <th className="num">Commission</th>
                  <th style={{ width: 160 }}>AFYP share</th>
                </tr>
              </thead>
              <tbody>
                {mix.data.rows.map((r) => {
                  const share = mix.data!.totals.afyp > 0 ? (r.afyp / mix.data!.totals.afyp) * 100 : 0;
                  return (
                    <tr key={r.product_id}>
                      <td>{r.name} <span className="muted">({r.code})</span></td>
                      <td><span className="badge role">{productTypeLabel(r.type)}</span></td>
                      <td className="num">{r.count}</td>
                      <td className="num">{money(r.notional)}</td>
                      <td className="num">{money(r.afyp)}</td>
                      <td className="num">{money(r.commission)}</td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div style={{ flex: 1, height: 8, background: "var(--line)", borderRadius: 999 }}>
                            <div style={{ width: `${share}%`, height: "100%", background: "var(--accent)", borderRadius: 999 }} />
                          </div>
                          <span className="muted" style={{ fontSize: 12, minWidth: 42, textAlign: "right" }}>
                            {share.toFixed(1)}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {mix.data.rows.length === 0 && (
                  <tr><td colSpan={7} className="muted">No settled production in this window.</td></tr>
                )}
              </tbody>
              {mix.data.rows.length > 0 && (
                <tfoot>
                  <tr style={{ fontWeight: 700 }}>
                    <td>Total</td><td></td>
                    <td className="num">{mix.data.totals.count}</td>
                    <td className="num">{money(mix.data.totals.notional)}</td>
                    <td className="num">{money(mix.data.totals.afyp)}</td>
                    <td className="num">{money(mix.data.totals.commission)}</td>
                    <td></td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2>Agency summary</h2>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="ghost"
              onClick={() => downloadFile(`/reports/agency/export?format=csv&${qsWin}`,
                "agency_summary.csv")}>Download CSV</button>
            <button className="ghost"
              onClick={() => downloadFile(`/reports/agency/export?format=pdf&${qsWin}`,
                "agency_summary.pdf")}>Download PDF</button>
          </div>
        </div>
        {summary.isLoading && <div className="spinner">Loading…</div>}
        <DataTable
          data={summary.data ?? []}
          columns={summaryColumns}
          empty="No data in this window."
        />
      </div>
    </div>
  );
}
