import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/LanguageContext";
import { money } from "../lib/format";
import { productTypeLabel, productDetails } from "../lib/agency";
import StatusBadge from "../components/StatusBadge";

export default function ClientDetail() {
  const { id } = useParams();
  const clientId = Number(id);
  const qc = useQueryClient();
  const { me } = useAuth();
  const { t } = useI18n();
  const isAdmin = me?.role === "admin";
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const client = useQuery({
    queryKey: ["client", clientId],
    queryFn: () => api.client(clientId),
  });
  const txns = useQuery({
    queryKey: ["clientTxns", clientId],
    queryFn: () => api.clientTransactions(clientId),
  });
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.products() });
  const productsById = new Map((products.data ?? []).map((p) => [p.id, p]));

  // Both the owning agent and admins may maintain the client profile.
  const canEditProfile = true;

  const [form, setForm] = useState({
    name: "", email: "", phone: "", risk_profile: "", notes: "",
  });
  useEffect(() => {
    if (client.data) {
      setForm({
        name: client.data.name,
        email: client.data.email ?? "",
        phone: client.data.phone ?? "",
        risk_profile: client.data.risk_profile ?? "",
        notes: client.data.notes ?? "",
      });
    }
  }, [client.data]);

  const save = useMutation({
    mutationFn: () =>
      api.updateClient(clientId, {
        name: form.name,
        email: form.email || undefined,
        phone: form.phone || undefined,
        risk_profile: form.risk_profile || undefined,
        notes: form.notes || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client", clientId] });
      setMsg(t("clientDetail.saved")); setError(null);
      setTimeout(() => setMsg(null), 2500);
    },
    onError: (e) => setError(errorText(e, t) || t("clientDetail.saveFailed")),
  });

  const approve = useMutation({
    mutationFn: (txnId: number) => api.approveTransaction(txnId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clientTxns", clientId] }),
  });
  const cancel = useMutation({
    mutationFn: (txnId: number) => api.cancelTransaction(txnId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clientTxns", clientId] }),
  });
  const remove = useMutation({
    mutationFn: (txnId: number) => api.deleteTransaction(txnId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clientTxns", clientId] }),
    onError: (e) => setError(errorText(e, t) || t("clientDetail.deleteFailed")),
  });

  if (client.isLoading) return <div className="spinner">{t("common.loading")}</div>;
  if (client.error) return <div className="error">{t("clientDetail.loadFailed")}</div>;

  return (
    <div>
      <p className="page-sub"><Link to="/clients">{t("clientDetail.back")}</Link></p>
      <h1 className="page-title">{client.data!.name}</h1>
      <p className="page-sub">{client.data!.ref}</p>

      <div>
        <form className="card" onSubmit={(e) => { e.preventDefault(); if (canEditProfile) save.mutate(); }}>
          <h2>{t("clientDetail.profile")}</h2>
          {msg && <div className="success">{msg}</div>}
          {error && <div className="error">{error}</div>}
          <label>{t("common.name")}</label>
          <input value={form.name} disabled={!canEditProfile}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <div className="row">
            <div>
              <label>{t("common.email")}</label>
              <input value={form.email} disabled={!canEditProfile}
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div>
              <label>{t("common.phone")}</label>
              <input value={form.phone} disabled={!canEditProfile}
                onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </div>
          </div>
          <label>{t("clients.riskProfile")}</label>
          <input value={form.risk_profile} disabled={!canEditProfile}
            onChange={(e) => setForm({ ...form, risk_profile: e.target.value })} />
          <label>{t("clientDetail.notes")}</label>
          <textarea rows={3} value={form.notes} disabled={!canEditProfile}
            onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          {canEditProfile && (
            <div style={{ marginTop: 14 }}>
              <button className="primary" type="submit" disabled={save.isPending}>
                {save.isPending ? t("common.saving") : t("clientDetail.saveProfile")}
              </button>
            </div>
          )}
        </form>

        <div className="card">
          <h2>{t("clientDetail.txnHistory")}</h2>
          {txns.isLoading && <div className="spinner">{t("common.loading")}</div>}
          <table>
            <thead>
              <tr>
                <th>{t("common.ref")}</th><th>{t("common.date")}</th><th>{t("common.product")}</th><th className="num">{t("common.notional")}</th>
                <th>{t("common.status")}</th>{isAdmin && <th></th>}
              </tr>
            </thead>
            <tbody>
              {txns.data?.map((tx) => {
                const p = productsById.get(tx.product_id);
                const details = productDetails(p);
                return (
                <tr key={tx.id}>
                  <td>{tx.ref}</td>
                  <td className="muted">{tx.trade_date}</td>
                  <td>
                    <div>{p ? p.name : `#${tx.product_id}`}</div>
                    <div className="muted" style={{ fontSize: 11 }}>
                      {p && <span className="badge role" style={{ marginRight: 6 }}>{productTypeLabel(p.type)}</span>}
                      {details}
                    </div>
                  </td>
                  <td className="num">{money(tx.notional, tx.currency)}</td>
                  <td><StatusBadge status={tx.status} /></td>
                  {isAdmin && (
                    <td className="num" style={{ whiteSpace: "nowrap" }}>
                      {tx.status === "pending" && (
                        <button className="ghost" onClick={() => approve.mutate(tx.id)}>{t("clientDetail.approve")}</button>
                      )}{" "}
                      {tx.status === "approved" && (
                        <button className="ghost" onClick={() => cancel.mutate(tx.id)}>{t("common.cancel")}</button>
                      )}{" "}
                      <button className="ghost" style={{ color: "var(--bad)" }}
                        onClick={() => { if (window.confirm(t("clientDetail.confirmDelete", { ref: tx.ref }))) remove.mutate(tx.id); }}>
                        {t("common.delete")}
                      </button>
                    </td>
                  )}
                </tr>
                );
              })}
              {txns.data?.length === 0 && (
                <tr><td colSpan={isAdmin ? 6 : 5} className="muted">{t("clientDetail.noTxns")}</td></tr>
              )}
            </tbody>
          </table>
          {isAdmin ? (
            <p style={{ marginTop: 12 }}>
              <Link to="/transactions/new">{t("clientDetail.bookNew")}</Link>
            </p>
          ) : (
            <p className="muted" style={{ marginTop: 12, fontSize: 12 }}>
              {t("clientDetail.adminBooksNote")}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
