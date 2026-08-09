import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { money } from "../lib/format";
import { productTypeLabel, productDetails } from "../lib/agency";
import StatusBadge from "../components/StatusBadge";

export default function ClientDetail() {
  const { id } = useParams();
  const clientId = Number(id);
  const qc = useQueryClient();
  const { me } = useAuth();
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

  // Admins can view a client but not edit the profile (owner-only).
  const canEditProfile = !isAdmin;

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
      setMsg("Saved."); setError(null);
      setTimeout(() => setMsg(null), 2500);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Save failed"),
  });

  const settle = useMutation({
    mutationFn: (txnId: number) => api.settleTransaction(txnId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clientTxns", clientId] }),
  });
  const cancel = useMutation({
    mutationFn: (txnId: number) => api.cancelTransaction(txnId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clientTxns", clientId] }),
  });
  const remove = useMutation({
    mutationFn: (txnId: number) => api.deleteTransaction(txnId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clientTxns", clientId] }),
    onError: (e) => setError(e instanceof ApiError ? e.message : "Delete failed"),
  });

  if (client.isLoading) return <div className="spinner">Loading…</div>;
  if (client.error) return <div className="error">Could not load client (out of scope?).</div>;

  return (
    <div>
      <p className="page-sub"><Link to="/clients">← Clients</Link></p>
      <h1 className="page-title">{client.data!.name}</h1>
      <p className="page-sub">{client.data!.ref}</p>

      <div>
        <form className="card" onSubmit={(e) => { e.preventDefault(); if (canEditProfile) save.mutate(); }}>
          <h2>Profile {isAdmin && <span className="muted" style={{ fontSize: 12 }}>(read-only — owner edits)</span>}</h2>
          {msg && <div className="success">{msg}</div>}
          {error && <div className="error">{error}</div>}
          <label>Name</label>
          <input value={form.name} disabled={!canEditProfile}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <div className="row">
            <div>
              <label>Email</label>
              <input value={form.email} disabled={!canEditProfile}
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div>
              <label>Phone</label>
              <input value={form.phone} disabled={!canEditProfile}
                onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </div>
          </div>
          <label>Risk profile</label>
          <input value={form.risk_profile} disabled={!canEditProfile}
            onChange={(e) => setForm({ ...form, risk_profile: e.target.value })} />
          <label>Notes</label>
          <textarea rows={3} value={form.notes} disabled={!canEditProfile}
            onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          {canEditProfile && (
            <div style={{ marginTop: 14 }}>
              <button className="primary" type="submit" disabled={save.isPending}>
                {save.isPending ? "Saving…" : "Save profile"}
              </button>
            </div>
          )}
        </form>

        <div className="card">
          <h2>Transaction history</h2>
          {txns.isLoading && <div className="spinner">Loading…</div>}
          <table>
            <thead>
              <tr>
                <th>Ref</th><th>Date</th><th>Product</th><th className="num">Notional</th>
                <th>Status</th>{isAdmin && <th></th>}
              </tr>
            </thead>
            <tbody>
              {txns.data?.map((t) => {
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
                  {isAdmin && (
                    <td className="num" style={{ whiteSpace: "nowrap" }}>
                      {t.status === "pending" && (
                        <button className="ghost" onClick={() => settle.mutate(t.id)}>Settle</button>
                      )}{" "}
                      {t.status === "settled" && (
                        <button className="ghost" onClick={() => cancel.mutate(t.id)}>Cancel</button>
                      )}{" "}
                      <button className="ghost" style={{ color: "var(--bad)" }}
                        onClick={() => { if (window.confirm(`Delete transaction ${t.ref}?`)) remove.mutate(t.id); }}>
                        Delete
                      </button>
                    </td>
                  )}
                </tr>
                );
              })}
              {txns.data?.length === 0 && (
                <tr><td colSpan={isAdmin ? 6 : 5} className="muted">No transactions.</td></tr>
              )}
            </tbody>
          </table>
          {isAdmin ? (
            <p style={{ marginTop: 12 }}>
              <Link to="/transactions/new">+ Book a new transaction</Link>
            </p>
          ) : (
            <p className="muted" style={{ marginTop: 12, fontSize: 12 }}>
              Transactions are booked and managed by an admin.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
