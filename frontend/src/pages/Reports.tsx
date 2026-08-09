import { useMemo, useState, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { api, downloadFile } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/LanguageContext";
import { money, pct, currentPeriod } from "../lib/format";
import { productDetails } from "../lib/agency";
import { productTypeLabel, kindLabel } from "../i18n/labels";
import DataTable from "../components/DataTable";
import type { AgencySummaryRow, Product } from "../api/types";

export default function Reports() {
  const { me } = useAuth();
  const { t, lang } = useI18n();
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

  const qsWin = `start=${start}&end=${end}&lang=${lang}`;

  const summaryColumns = useMemo<ColumnDef<AgencySummaryRow, any>[]>(() => [
    { header: t("common.agent"), accessorKey: "name" },
    { header: t("common.code"), accessorKey: "code" },
    { header: t("common.level"), accessorFn: (r) => `L${r.level}`, id: "level" },
    {
      header: t("common.afyp"), accessorKey: "afyp", meta: { num: true },
      cell: (ctx) => money(ctx.getValue() as number),
    },
    {
      header: t("reports.commissionIncome"), accessorKey: "direct", meta: { num: true },
      cell: (ctx) => money(ctx.getValue() as number),
    },
    {
      header: t("reports.overrideIncome"), accessorKey: "override", meta: { num: true },
      cell: (ctx) => money(ctx.getValue() as number),
    },
    {
      header: t("reports.total"), accessorKey: "total", meta: { num: true },
      cell: (ctx) => money(ctx.getValue() as number),
    },
  ], [t]);

  return (
    <div>
      <h1 className="page-title">{t("reports.title")}</h1>
      <p className="page-sub">{t("reports.subtitle")}</p>

      <div className="card">
        <div className="row">
          <div>
            <label>{t("common.agent")}</label>
            <select value={agentId} onChange={(e) => setAgentId(Number(e.target.value))}>
              {agents.data?.map((a) => (
                <option key={a.id} value={a.id}>{a.name} ({a.code})</option>
              ))}
            </select>
          </div>
          <div>
            <label>{t("reports.from")}</label>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div>
            <label>{t("reports.to")}</label>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2>{t("reports.agentStatement")}</h2>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="ghost"
              onClick={() => downloadFile(`/reports/agent/${agentId}/export?format=csv&${qsWin}`,
                `statement_${agentId}.csv`)}>{t("reports.downloadCsv")}</button>
            <button className="ghost"
              onClick={() => downloadFile(`/reports/agent/${agentId}/export?format=pdf&${qsWin}`,
                `statement_${agentId}.pdf`)}>{t("reports.downloadPdf")}</button>
          </div>
        </div>
        {statement.isLoading && <div className="spinner">{t("common.loading")}</div>}
        {statement.data && (
          <>
            <div className="grid cols-3" style={{ marginBottom: 14 }}>
              <div className="stat">
                <div className="label">{t("reports.direct")}</div>
                <div className="value good">{money(statement.data.direct_total)}</div>
              </div>
              <div className="stat">
                <div className="label">{t("common.override")}</div>
                <div className="value good">{money(statement.data.override_total)}</div>
              </div>
              <div className="stat">
                <div className="label">{t("reports.grandTotal")}</div>
                <div className="value">{money(statement.data.grand_total)}</div>
              </div>
            </div>
            <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>{t("reports.thKind")}</th><th>{t("reports.thRef")}</th><th>{t("reports.thDate")}</th>
                  <th>{t("reports.thClient")}</th><th>{t("common.product")}</th>
                  <th className="num">{t("common.notional")}</th>
                  <th className="num">{t("reports.thRate")}</th>
                  <th className="num">{t("reports.thAmount")}</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const entries = statement.data!.entries;
                  if (entries.length === 0) {
                    return <tr><td colSpan={8} className="muted">{t("reports.noCommission")}</td></tr>;
                  }
                  const order: Record<string, number> = { direct: 0, override: 1 };
                  const kinds = [...new Set(entries.map((e) => e.kind))]
                    .sort((a, b) => (order[a] ?? 9) - (order[b] ?? 9));
                  const out: ReactElement[] = [];
                  kinds.forEach((kind) => {
                    const group = entries.filter((e) => e.kind === kind);
                    group.forEach((e, i) => {
                      const detail = productDetails({
                        provider: e.provider, type: e.product_type, payment_tenor: e.payment_tenor,
                        age_min: e.age_min, age_max: e.age_max, professional_investor: e.professional_investor,
                      } as unknown as Product);
                      return out.push(
                        <tr key={`${kind}-${i}`}>
                          <td>{i === 0 ? kindLabel(kind) : ""}</td>
                          <td>{e.transaction_ref}</td>
                          <td className="muted">{e.trade_date}</td>
                          <td>{e.client_name}</td>
                          <td>
                            <div>{e.product_name} <span className="muted" style={{ fontSize: 11 }}>({productTypeLabel(e.product_type)})</span></div>
                            {detail && <div className="muted" style={{ fontSize: 11 }}>{detail}</div>}
                          </td>
                          <td className="num">{money(e.notional)}</td>
                          <td className="num">{e.kind === "override" && e.override_rate ? pct(e.override_rate) : pct(e.commission_rate)}</td>
                          <td className="num">{money(e.amount)}</td>
                        </tr>,
                      );
                    });
                    const subAmt = group.reduce((s, e) => s + e.amount, 0);
                    out.push(
                      <tr key={`${kind}-subtotal`} className="subtotal-row">
                        <td colSpan={7}>{kindLabel(kind)} {t("reports.subtotal")}</td>
                        <td className="num">{money(subAmt)}</td>
                      </tr>,
                    );
                  });
                  return out;
                })()}
              </tbody>
              {statement.data.entries.length > 0 && (
                <tfoot>
                  <tr style={{ fontWeight: 700 }}>
                    <td colSpan={7}>{t("reports.grandTotal")}</td>
                    <td className="num">{money(statement.data.grand_total)}</td>
                  </tr>
                </tfoot>
              )}
            </table>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h2>{t("reports.productMix")}</h2>
          <span className="muted" style={{ fontSize: 13 }}>
            {t("reports.productMixSub")}
          </span>
        </div>
        {mix.isLoading && <div className="spinner">{t("common.loading")}</div>}
        {mix.data && (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>{t("common.product")}</th><th>{t("common.type")}</th>
                  <th className="num">#</th>
                  <th className="num">{t("common.notional")}</th>
                  <th className="num">{t("common.afyp")}</th>
                  <th className="num">{t("common.commission")}</th>
                  <th style={{ width: 160 }}>{t("reports.afypShare")}</th>
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
                  <tr><td colSpan={7} className="muted">{t("reports.noSettled")}</td></tr>
                )}
              </tbody>
              {mix.data.rows.length > 0 && (
                <tfoot>
                  <tr style={{ fontWeight: 700 }}>
                    <td>{t("reports.total")}</td><td></td>
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
          <h2>{t("reports.agencySummary")}</h2>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="ghost"
              onClick={() => downloadFile(`/reports/agency/export?format=csv&${qsWin}`,
                "agency_summary.csv")}>{t("reports.downloadCsv")}</button>
            <button className="ghost"
              onClick={() => downloadFile(`/reports/agency/export?format=pdf&${qsWin}`,
                "agency_summary.pdf")}>{t("reports.downloadPdf")}</button>
          </div>
        </div>
        {summary.isLoading && <div className="spinner">{t("common.loading")}</div>}
        <DataTable
          data={summary.data ?? []}
          columns={summaryColumns}
          empty={t("reports.noData")}
        />
      </div>
    </div>
  );
}
