import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { money } from "../../lib/format";
import { productTypeLabel } from "../../i18n/labels";
import StatusBadge from "../../components/StatusBadge";
import LockedRate from "../../components/LockedRate";
import RoleAgent from "../../components/RoleAgent";
import type { AdminTxnRow } from "../../api/types";

const STATUSES = ["pending", "approved", "cancelled"];

// Rates are stored as fractions (0.05) but shown/edited as percentages (5.00).
function fracToPct(frac: string | null | undefined): string {
  if (frac == null || String(frac).trim() === "") return "";
  return String(Math.round(Number(frac) * 10000) / 100);
}
function pctToFrac(pctStr: string): string {
  if (pctStr.trim() === "") return "0";
  return (Number(pctStr) / 100).toFixed(4);
}

export default function AdminTransactions() {
  const { t } = useI18n();
  const qc = useQueryClient();

  const txns = useQuery({ queryKey: ["adminTxns"], queryFn: () => api.listTransactions() });
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.products() });
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api.agents() });

  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [rowErr, setRowErr] = useState<string | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["adminTxns"] });
  const onErr = (e: unknown) => setRowErr(errorText(e, t) || t("adminTxn.actionFailed"));

  const approve = useMutation({
    mutationFn: (v: { id: number; override?: Record<string, unknown> }) =>
      api.approveTransaction(v.id, v.override),
    onSuccess: () => { invalidate(); setApproveId(null); setRowErr(null); }, onError: onErr,
  });

  // --- Approve with an optional final-rate override ---
  const [approveId, setApproveId] = useState<number | null>(null);
  const [approveRef, setApproveRef] = useState("");
  const [approvePerYear, setApprovePerYear] = useState(false);
  const [approveBase, setApproveBase] = useState("");   // percent, flat products
  const [approveYears, setApproveYears] = useState<string[]>([]);  // percent, per-year
  function startApprove(r: AdminTxnRow) {
    setApproveId(r.id);
    setApproveRef(r.ref);
    const yc = r.locked_year_commissions;
    if (r.commission_schedule === "trail" && yc && yc.length) {
      setApprovePerYear(true);
      setApproveYears(yc.map((v) => fracToPct(v)));
      setApproveBase("");
    } else {
      setApprovePerYear(false);
      setApproveBase(fracToPct(r.locked_base_rate));
      setApproveYears([]);
    }
  }
  function submitApprove() {
    const override = approvePerYear
      ? { year_commissions: approveYears.map((v) => pctToFrac(v)) }
      : { base_commission_rate: pctToFrac(approveBase) };
    approve.mutate({ id: approveId!, override });
  }
  const cancel = useMutation({
    mutationFn: (id: number) => api.cancelTransaction(id),
    onSuccess: () => { invalidate(); setRowErr(null); }, onError: onErr,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteTransaction(id),
    onSuccess: () => { invalidate(); setRowErr(null); }, onError: onErr,
  });

  // --- Edit ---
  const [editId, setEditId] = useState<number | null>(null);
  const [editRef, setEditRef] = useState("");
  const [editForm, setEditForm] = useState({
    notional: "", trade_date: "", policy_no: "", product_id: "",
    agent_id: "",            // closing agent
    lead_agent_id: "", sales_dev_agent_id: "",
    lead_pct: "0", sales_dev_pct: "0", closing_pct: "100",
    deal_type: "agent",      // "agent" (代理) | "direct_client" (直客)
  });
  // Manual override levels (up to 4): agent + rate %. Honoured for both deal
  // types. editHadOverrides tracks whether the row already stored overrides, so
  // the hierarchy defaults don't clobber them on load.
  const [editOverrides, setEditOverrides] = useState<{ agent_id: string; pct: string }[]>([{ agent_id: "", pct: "" }]);
  const [editHadOverrides, setEditHadOverrides] = useState(false);
  const [editErr, setEditErr] = useState<string | null>(null);

  // Agents pickable for a role (exclude admins; keep inactive so an existing
  // assignment still renders). 直客 overrides are limited to 直客-flagged agents;
  // 代理 overrides may go to any active agent.
  const roleOptions = (agents.data ?? []).filter((a) => a.role !== "admin");
  const dcAgents = roleOptions.filter((a) => a.direct_client && a.is_active);
  const isDirectClient = editForm.deal_type === "direct_client";
  const overrideAgents = isDirectClient ? dcAgents : roleOptions.filter((a) => a.is_active);
  const pctSum = Number(editForm.lead_pct || 0) + Number(editForm.sales_dev_pct || 0) + Number(editForm.closing_pct || 0);
  const pctValid = Math.round(pctSum * 100) === 10000;

  // For a 代理 deal with no stored overrides, pre-fill the editor from the lead
  // agent's hierarchy (same source as the booking form). The engine treats the
  // closing agent as the lead when lead_agent_id is unset (legacy deals), so use
  // that same fallback. Refetches only when the effective lead or product changes.
  const effLead = editForm.lead_agent_id || editForm.agent_id;
  const overrideDefaultsQ = useQuery({
    queryKey: ["overrideDefaults", effLead, editForm.product_id],
    queryFn: () => api.overrideDefaults(Number(effLead), Number(editForm.product_id)),
    enabled: editId != null && !isDirectClient && !!effLead && !!editForm.product_id,
  });
  useEffect(() => {
    if (isDirectClient || editHadOverrides) return;
    const d = overrideDefaultsQ.data;
    if (!d) return;
    setEditOverrides(d.length
      ? d.map((x) => ({ agent_id: String(x.agent_id), pct: String(x.pct) }))
      : [{ agent_id: "", pct: "" }]);
  }, [isDirectClient, editHadOverrides, effLead, editForm.product_id, overrideDefaultsQ.data]);

  const update = useMutation({
    mutationFn: () => api.updateTransaction(editId!, {
      notional: editForm.notional,
      trade_date: editForm.trade_date,
      policy_no: editForm.policy_no || null,
      product_id: Number(editForm.product_id),
      agent_id: Number(editForm.agent_id),
      lead_agent_id: editForm.lead_agent_id ? Number(editForm.lead_agent_id) : null,
      sales_dev_agent_id: editForm.sales_dev_agent_id ? Number(editForm.sales_dev_agent_id) : null,
      lead_pct: editForm.lead_pct || "0",
      sales_dev_pct: editForm.sales_dev_pct || "0",
      closing_pct: editForm.closing_pct || "0",
      deal_type: editForm.deal_type,
      direct_overrides: (() => {
        const rowsO = editOverrides
          .filter((o) => o.agent_id && o.pct)
          .map((o) => ({ agent_id: Number(o.agent_id), pct: o.pct }));
        return rowsO.length ? rowsO : null;
      })(),
    }),
    onSuccess: () => { invalidate(); setEditId(null); setEditErr(null); },
    onError: (e) => setEditErr(errorText(e, t) || t("adminTxn.actionFailed")),
  });

  function startEdit(r: AdminTxnRow) {
    setEditId(r.id);
    setEditRef(r.ref);
    setEditForm({
      notional: r.notional, trade_date: r.trade_date, policy_no: r.policy_no ?? "",
      product_id: String(r.product_id), agent_id: String(r.agent_id),
      lead_agent_id: r.lead_agent_id ? String(r.lead_agent_id) : "",
      sales_dev_agent_id: r.sales_dev_agent_id ? String(r.sales_dev_agent_id) : "",
      lead_pct: r.lead_pct != null ? String(r.lead_pct) : "0",
      sales_dev_pct: r.sales_dev_pct != null ? String(r.sales_dev_pct) : "0",
      closing_pct: r.closing_pct != null ? String(r.closing_pct) : "100",
      deal_type: r.deal_type || "agent",
    });
    const stored = r.direct_overrides && r.direct_overrides.length;
    setEditHadOverrides(!!stored);
    setEditOverrides(
      stored
        ? r.direct_overrides!.map((o) => ({ agent_id: String(o.agent_id), pct: String(o.pct) }))
        : [{ agent_id: "", pct: "" }],
    );
    setEditErr(null);
  }

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (txns.data ?? []).filter((r) => {
      if (status && r.status !== status) return false;
      if (!needle) return true;
      return [r.ref, r.client_name, r.client_ref, r.product_name, r.policy_no,
              r.agent_name, r.agent_code]
        .some((v) => (v ?? "").toLowerCase().includes(needle));
    });
  }, [txns.data, status, q]);

  return (
    <div>
      <h1 className="page-title">{t("adminTxn.title")}</h1>
      <p className="page-sub">{t("adminTxn.subtitle")}</p>

      <div className="card">
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 2 }}>
            <label>{t("common.search")}</label>
            <input value={q} onChange={(e) => setQ(e.target.value)}
              placeholder={t("adminTxn.searchPlaceholder")} />
          </div>
          <div>
            <label>{t("adminTxn.filterStatus")}</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("adminTxn.all")}</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>{t(`enum.status.${s}`)}</option>
              ))}
            </select>
          </div>
        </div>

        {rowErr && <div className="error" style={{ marginTop: 10 }}>{rowErr}</div>}
        {txns.isError && (
          <div className="error" style={{ marginTop: 10 }}>{errorText(txns.error, t) || t("adminTxn.actionFailed")}</div>
        )}
        <p className="muted" style={{ margin: "10px 0" }}>
          {txns.isLoading ? t("common.loading") : t("adminTxn.count", { count: rows.length })}
        </p>

        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>{t("common.ref")}</th>
                <th>{t("common.date")}</th>
                <th>{t("common.client")}</th>
                <th>{t("common.product")}</th>
                <th>{t("txn.roleLead")}</th>
                <th>{t("txn.roleSdr")}</th>
                <th>{t("txn.roleClosing")}</th>
                <th className="num">{t("txn.commRate")}</th>
                <th className="num">{t("common.notional")}</th>
                <th>{t("adminTxn.thType")}</th>
                <th>{t("common.status")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.ref}</td>
                  <td>{r.trade_date}</td>
                  <td>
                    <Link to={`/clients/${r.client_id}`}>{r.client_name}</Link>
                    <br /><span className="muted" style={{ fontSize: 12 }}>{r.client_ref}</span>
                  </td>
                  <td>{r.product_name}<br />
                    <span className="muted" style={{ fontSize: 12 }}>{productTypeLabel(r.product_type)}</span>
                  </td>
                  <td><RoleAgent name={r.lead_name} code={r.lead_code} pct={r.lead_pct} /></td>
                  <td><RoleAgent name={r.sdr_name} code={r.sdr_code} pct={r.sales_dev_pct} /></td>
                  <td><RoleAgent name={r.closing_name ?? r.agent_name} code={r.closing_code ?? r.agent_code} pct={r.closing_pct} /></td>
                  <td className="num"><LockedRate base={r.locked_base_rate} years={r.locked_year_commissions} /></td>
                  <td className="num">{money(r.notional, r.currency)}</td>
                  <td>
                    <span className="badge">
                      {r.deal_type === "direct_client" ? t("newTxn.dealDirectClient") : t("newTxn.dealAgent")}
                    </span>
                  </td>
                  <td><StatusBadge status={r.status} /></td>
                  <td className="num" style={{ whiteSpace: "nowrap" }}>
                    {r.status === "pending" && (
                      <button className="ghost" onClick={() => startApprove(r)}>{t("adminTxn.approve")}</button>
                    )}{" "}
                    {r.status === "approved" && (
                      <button className="ghost"
                        onClick={() => { if (window.confirm(t("adminTxn.confirmCancel", { ref: r.ref }))) cancel.mutate(r.id); }}>
                        {t("common.cancel")}
                      </button>
                    )}{" "}
                    <button className="ghost" onClick={() => startEdit(r)}>{t("common.edit")}</button>{" "}
                    <button className="ghost" style={{ color: "var(--bad)" }}
                      onClick={() => { if (window.confirm(t("adminTxn.confirmDelete", { ref: r.ref }))) remove.mutate(r.id); }}>
                      {t("common.delete")}
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={12} className="muted">{t("adminTxn.empty")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {approveId != null && (
        <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); submitApprove(); }}>
          <h2>{t("adminTxn.approveTitle", { ref: approveRef })}</h2>
          <p className="muted" style={{ fontSize: 12, marginTop: -6 }}>{t("adminTxn.finalRateNote")}</p>
          {approvePerYear ? (
            <>
              <label>{t("adminTxn.finalSchedule")}</label>
              <div className="year-grid">
                {approveYears.map((v, i) => (
                  <div key={i} className="year-cell">
                    <span className="yr-label">{t("admin.products.yr", { n: i + 1 })}</span>
                    <input type="number" step="0.01" min="0" max="999.99" value={v}
                      onChange={(e) => setApproveYears(approveYears.map((x, j) => j === i ? e.target.value : x))} />
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div style={{ maxWidth: 220 }}>
              <label>{t("adminTxn.finalRate")}</label>
              <input type="number" step="0.01" min="0" max="999.99" value={approveBase}
                onChange={(e) => setApproveBase(e.target.value)} />
            </div>
          )}
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button className="primary" type="submit" disabled={approve.isPending}>
              {approve.isPending ? t("common.saving") : t("adminTxn.approveConfirm")}
            </button>
            <button className="ghost" type="button" onClick={() => setApproveId(null)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}

      {editId != null && (
        <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); update.mutate(); }}>
          <h2>{t("adminTxn.editTitle", { ref: editRef })}</h2>
          {editErr && <div className="error">{editErr}</div>}

          <label>{t("newTxn.dealType")}</label>
          <select value={editForm.deal_type}
            onChange={(e) => setEditForm({ ...editForm, deal_type: e.target.value })}>
            <option value="agent">{t("newTxn.dealAgent")}</option>
            <option value="direct_client">{t("newTxn.dealDirectClient")}</option>
          </select>

          {/* Role agents */}
          <div className="row">
            <div><label>{t("newTxn.leadAgent")}</label>
              <select value={editForm.lead_agent_id}
                onChange={(e) => { setEditForm({ ...editForm, lead_agent_id: e.target.value }); setEditHadOverrides(false); }}>
                <option value="">—</option>
                {roleOptions.map((a) => (
                  <option key={a.id} value={a.id}>{a.name} ({a.code}) · L{a.level}</option>
                ))}
              </select></div>
            <div><label>{t("newTxn.salesDevAgent")}</label>
              <select value={editForm.sales_dev_agent_id}
                onChange={(e) => setEditForm({ ...editForm, sales_dev_agent_id: e.target.value })}>
                <option value="">—</option>
                {roleOptions.map((a) => (
                  <option key={a.id} value={a.id}>{a.name} ({a.code}) · L{a.level}</option>
                ))}
              </select></div>
            <div><label>{t("newTxn.closingAgent")}</label>
              <select value={editForm.agent_id} required
                onChange={(e) => { setEditForm({ ...editForm, agent_id: e.target.value }); setEditHadOverrides(false); }}>
                {roleOptions.map((a) => (
                  <option key={a.id} value={a.id}>{a.name} ({a.code}) · L{a.level}</option>
                ))}
              </select></div>
          </div>

          {/* Split percentages */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: 6 }}>
            <h2 style={{ fontSize: 14 }}>{t("newTxn.splitTitle")}</h2>
            {!pctValid && <span style={{ fontSize: 12, color: "var(--bad)" }}>{t("newTxn.splitMustBe100", { sum: pctSum })}</span>}
          </div>
          <div className="row">
            <div><label>{t("newTxn.pctLead")}</label>
              <input type="number" min="0" max="100" step="0.1" value={editForm.lead_pct}
                onChange={(e) => setEditForm({ ...editForm, lead_pct: e.target.value })} /></div>
            <div><label>{t("newTxn.pctSalesDev")}</label>
              <input type="number" min="0" max="100" step="0.1" value={editForm.sales_dev_pct}
                onChange={(e) => setEditForm({ ...editForm, sales_dev_pct: e.target.value })} /></div>
            <div><label>{t("newTxn.pctClosing")}</label>
              <input type="number" min="0" max="100" step="0.1" value={editForm.closing_pct}
                onChange={(e) => setEditForm({ ...editForm, closing_pct: e.target.value })} /></div>
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>{t("newTxn.splitNote")}</p>

          {/* Override levels (直客: manual; 代理: loaded from hierarchy, editable) */}
          <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
            <h2 style={{ fontSize: 14 }}>{isDirectClient ? t("newTxn.overrideLevels") : t("newTxn.overrideHierTitle")}</h2>
            <p className="muted" style={{ fontSize: 12, marginTop: -4 }}>
              {isDirectClient ? t("newTxn.overrideNote") : t("newTxn.overrideHierNote")}
            </p>
            {isDirectClient && dcAgents.length === 0 ? (
              <div className="error" style={{ fontSize: 12 }}>{t("newTxn.noDcAgents")}</div>
            ) : (
              <>
                {editOverrides.map((o, i) => (
                  <div className="row" key={i} style={{ alignItems: "flex-end" }}>
                    <div style={{ flex: 3 }}>
                      {i === 0 && <label>{t("common.agent")}</label>}
                      <select value={o.agent_id}
                        onChange={(e) => setEditOverrides(editOverrides.map((x, j) => j === i ? { ...x, agent_id: e.target.value } : x))}>
                        <option value="">{isDirectClient ? t("newTxn.selectDcAgent") : t("newTxn.selectAgent")}</option>
                        {overrideAgents.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.code})</option>)}
                      </select>
                    </div>
                    <div style={{ flex: 1 }}>
                      {i === 0 && <label>{t("newTxn.ratePct")}</label>}
                      <input type="number" min="0" max="100" step="1" value={o.pct}
                        onChange={(e) => setEditOverrides(editOverrides.map((x, j) => j === i ? { ...x, pct: e.target.value } : x))} />
                    </div>
                    <div className="shrink">
                      <button type="button" className="ghost" style={{ color: "var(--bad)" }}
                        disabled={editOverrides.length === 1}
                        onClick={() => setEditOverrides(editOverrides.filter((_, j) => j !== i))}>
                        {t("newTxn.removeLevel")}
                      </button>
                    </div>
                  </div>
                ))}
                {editOverrides.length < 4 && (
                  <button type="button" className="ghost" style={{ marginTop: 8 }}
                    onClick={() => setEditOverrides([...editOverrides, { agent_id: "", pct: "" }])}>
                    {t("newTxn.addLevel")}
                  </button>
                )}
              </>
            )}
          </div>

          {/* Product / notional / date / policy */}
          <div className="row" style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
            <div><label>{t("adminTxn.product")}</label>
              <select value={editForm.product_id} required
                onChange={(e) => { setEditForm({ ...editForm, product_id: e.target.value }); setEditHadOverrides(false); }}>
                {(products.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>{p.code} · {p.name}</option>
                ))}
              </select></div>
            <div><label>{t("adminTxn.notional")}</label>
              <input type="number" step="0.01" value={editForm.notional} required
                onChange={(e) => setEditForm({ ...editForm, notional: e.target.value })} /></div>
            <div><label>{t("adminTxn.tradeDate")}</label>
              <input type="date" value={editForm.trade_date} required
                onChange={(e) => setEditForm({ ...editForm, trade_date: e.target.value })} /></div>
            <div><label>{t("adminTxn.policyNo")}</label>
              <input value={editForm.policy_no}
                onChange={(e) => setEditForm({ ...editForm, policy_no: e.target.value })} /></div>
          </div>

          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <button className="primary" type="submit" disabled={update.isPending || !pctValid}>
              {update.isPending ? t("common.saving") : t("adminTxn.save")}
            </button>
            <button className="ghost" type="button" onClick={() => setEditId(null)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
    </div>
  );
}
