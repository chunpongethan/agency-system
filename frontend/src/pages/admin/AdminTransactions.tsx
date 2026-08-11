import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { money } from "../../lib/format";
import { productTypeLabel } from "../../i18n/labels";
import StatusBadge from "../../components/StatusBadge";
import type { AdminTxnRow } from "../../api/types";

const STATUSES = ["pending", "approved", "cancelled"];

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
    mutationFn: (id: number) => api.approveTransaction(id),
    onSuccess: () => { invalidate(); setRowErr(null); }, onError: onErr,
  });
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
    notional: "", trade_date: "", policy_no: "", product_id: "", agent_id: "",
  });
  const [editErr, setEditErr] = useState<string | null>(null);

  const update = useMutation({
    mutationFn: () => api.updateTransaction(editId!, {
      notional: editForm.notional,
      trade_date: editForm.trade_date,
      policy_no: editForm.policy_no || null,
      product_id: Number(editForm.product_id),
      agent_id: Number(editForm.agent_id),
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
    });
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
                <th>{t("adminTxn.thAgent")}</th>
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
                  <td>{r.agent_name}<br />
                    <span className="muted" style={{ fontSize: 12 }}>{r.agent_code}</span>
                  </td>
                  <td className="num">{money(r.notional, r.currency)}</td>
                  <td>
                    <span className="badge">
                      {r.deal_type === "direct_client" ? t("newTxn.dealDirectClient") : t("newTxn.dealAgent")}
                    </span>
                  </td>
                  <td><StatusBadge status={r.status} /></td>
                  <td className="num" style={{ whiteSpace: "nowrap" }}>
                    {r.status === "pending" && (
                      <button className="ghost" onClick={() => approve.mutate(r.id)}>{t("adminTxn.approve")}</button>
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
                <tr><td colSpan={9} className="muted">{t("adminTxn.empty")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {editId != null && (
        <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); update.mutate(); }}>
          <h2>{t("adminTxn.editTitle", { ref: editRef })}</h2>
          {editErr && <div className="error">{editErr}</div>}
          <div className="row">
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
          <div className="row">
            <div><label>{t("adminTxn.product")}</label>
              <select value={editForm.product_id} required
                onChange={(e) => setEditForm({ ...editForm, product_id: e.target.value })}>
                {(products.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>{p.code} · {p.name}</option>
                ))}
              </select></div>
            <div><label>{t("adminTxn.owningAgent")}</label>
              <select value={editForm.agent_id} required
                onChange={(e) => setEditForm({ ...editForm, agent_id: e.target.value })}>
                {(agents.data ?? []).map((a) => (
                  <option key={a.id} value={a.id}>{a.code} · {a.name}</option>
                ))}
              </select></div>
          </div>
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <button className="primary" type="submit" disabled={update.isPending}>
              {update.isPending ? t("common.saving") : t("adminTxn.save")}
            </button>
            <button className="ghost" type="button" onClick={() => setEditId(null)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}
    </div>
  );
}
