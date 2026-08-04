import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { money } from "../lib/format";
import StatusBadge from "../components/StatusBadge";

export default function ClientDetail() {
  const { id } = useParams();
  const clientId = Number(id);
  const qc = useQueryClient();
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
      setMsg("Saved.");
      setError(null);
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

  if (client.isLoading) return <div className="spinner">Loading…</div>;
  if (client.error) return <div className="error">Could not load client (out of scope?).</div>;

  return (
    <div>
      <p className="page-sub"><Link to="/clients">← Clients</Link></p>
      <h1 className="page-title">{client.data!.name}</h1>
      <p className="page-sub">{client.data!.ref}</p>

      <div className="grid cols-2">
        <form
          className="card"
          onSubmit={(e) => { e.preventDefault(); save.mutate(); }}
        >
          <h2>Profile</h2>
          {msg && <div className="success">{msg}</div>}
          {error && <div className="error">{error}</div>}
          <label>Name</label>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <div className="row">
            <div>
              <label>Email</label>
              <input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div>
              <label>Phone</label>
              <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </div>
          </div>
          <label>Risk profile</label>
          <input value={form.risk_profile}
            onChange={(e) => setForm({ ...form, risk_profile: e.target.value })} />
          <label>Notes</label>
          <textarea rows={3} value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <div style={{ marginTop: 14 }}>
            <button className="primary" type="submit" disabled={save.isPending}>
              {save.isPending ? "Saving…" : "Save profile"}
            </button>
          </div>
        </form>

        <div className="card">
          <h2>Transaction history</h2>
          {txns.isLoading && <div className="spinner">Loading…</div>}
          <table>
            <thead>
              <tr>
                <th>Ref</th><th>Date</th><th className="num">Notional</th>
                <th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {txns.data?.map((t) => (
                <tr key={t.id}>
                  <td>{t.ref}</td>
                  <td className="muted">{t.trade_date}</td>
                  <td className="num">{money(t.notional, t.currency)}</td>
                  <td><StatusBadge status={t.status} /></td>
                  <td className="num">
                    {t.status === "pending" && (
                      <button className="ghost" onClick={() => settle.mutate(t.id)}>Settle</button>
                    )}
                    {t.status === "settled" && (
                      <button className="ghost" onClick={() => cancel.mutate(t.id)}>Cancel</button>
                    )}
                  </td>
                </tr>
              ))}
              {txns.data?.length === 0 && (
                <tr><td colSpan={5} className="muted">No transactions.</td></tr>
              )}
            </tbody>
          </table>
          <p style={{ marginTop: 12 }}>
            <Link to="/transactions/new">+ Book a new transaction</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
