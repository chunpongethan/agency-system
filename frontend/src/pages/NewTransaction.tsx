import { useMemo, useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { money, pct } from "../lib/format";
import StatusBadge from "../components/StatusBadge";
import type { Transaction } from "../api/types";

export default function NewTransaction() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Transaction | null>(null);

  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.clients() });
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.products() });
  // Auto-generated transaction code (YYYY-MM-NNN) for the current month.
  const nextRef = useQuery({ queryKey: ["nextRef"], queryFn: () => api.nextTransactionRef() });

  const [form, setForm] = useState({
    client_id: "",
    product_id: "",
    notional: "100000",
    currency: "USD",
  });

  const agentId = me!.id;
  const notionalNum = Number(form.notional) || 0;

  const selectedProduct = useMemo(
    () => products.data?.find((p) => p.id === Number(form.product_id)),
    [products.data, form.product_id],
  );
  const isInsurance = selectedProduct?.type === "insurance";

  const preview = useQuery({
    queryKey: ["preview", form.product_id, agentId, notionalNum],
    queryFn: () =>
      api.previewTransaction({
        product_id: Number(form.product_id),
        agent_id: agentId,
        notional: form.notional,
      }),
    enabled: !!form.product_id && notionalNum > 0,
  });

  const create = useMutation({
    mutationFn: () =>
      api.createTransaction({
        client_id: Number(form.client_id),
        product_id: Number(form.product_id),
        agent_id: agentId,
        notional: form.notional,
        currency: form.currency,
        // ref omitted — the backend auto-generates YYYY-MM-NNN.
      }),
    onSuccess: (txn) => {
      setCreated(txn);
      setError(null);
      qc.invalidateQueries({ queryKey: ["nextRef"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Failed to create transaction"),
  });

  const settle = useMutation({
    mutationFn: (id: number) => api.settleTransaction(id),
    onSuccess: (txn) => setCreated(txn),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <div>
      <h1 className="page-title">New transaction</h1>
      <p className="page-sub">Book a sale and preview the commission before settling</p>

      <div className="grid cols-2">
        <form className="card" onSubmit={onSubmit}>
          <h2>Details</h2>
          {error && <div className="error">{error}</div>}

          <label>Transaction code (auto-generated)</label>
          <input value={nextRef.data?.ref ?? "…"} readOnly disabled />

          <label>Client</label>
          <select value={form.client_id} required
            onChange={(e) => setForm({ ...form, client_id: e.target.value })}>
            <option value="">Select a client…</option>
            {clients.data?.map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.ref})</option>
            ))}
          </select>

          <label>Product</label>
          <select value={form.product_id} required
            onChange={(e) => setForm({ ...form, product_id: e.target.value })}>
            <option value="">Select a product…</option>
            {products.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {pct(p.base_commission_rate)} {p.commission_schedule}
              </option>
            ))}
          </select>

          <div className="row">
            <div style={{ flex: 3 }}>
              <label>Notional</label>
              <input type="number" value={form.notional} min="0" step="1000"
                onChange={(e) => setForm({ ...form, notional: e.target.value })} />
            </div>
            <div style={{ flex: 1 }}>
              <label>Currency</label>
              <select value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}>
                <option>USD</option><option>HKD</option><option>EUR</option><option>GBP</option>
              </select>
            </div>
          </div>

          {isInsurance && selectedProduct && (
            <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <h2 style={{ fontSize: 14 }}>Insurance product details</h2>
                <span className="muted" style={{ fontSize: 11 }}>maintained by admin · read-only</span>
              </div>
              <div className="grid cols-3" style={{ gap: 10 }}>
                <div className="stat">
                  <div className="label">Payment tenor</div>
                  <div className="value" style={{ fontSize: 18 }}>
                    {selectedProduct.payment_tenor != null ? `${selectedProduct.payment_tenor} yrs` : "—"}
                  </div>
                </div>
                <div className="stat">
                  <div className="label">Age range</div>
                  <div className="value" style={{ fontSize: 18 }}>
                    {selectedProduct.age_min != null || selectedProduct.age_max != null
                      ? `${selectedProduct.age_min ?? 0}–${selectedProduct.age_max ?? "?"}`
                      : "—"}
                  </div>
                </div>
                <div className="stat">
                  <div className="label">Professional investor</div>
                  <div className="value" style={{ fontSize: 18 }}>
                    {selectedProduct.professional_investor == null
                      ? "—" : selectedProduct.professional_investor ? "Yes" : "No"}
                  </div>
                </div>
              </div>
              {selectedProduct.year_commissions && selectedProduct.year_commissions.length > 0 && (
                <>
                  <label style={{ marginTop: 10 }}>Commission schedule — Yr1 to Yr10</label>
                  <div className="year-grid">
                    {selectedProduct.year_commissions.map((v, i) => (
                      <div key={i} className="year-cell">
                        <span className="yr-label">Yr{i + 1}</span>
                        <div style={{ fontVariantNumeric: "tabular-nums", fontSize: 13, fontWeight: 600 }}>
                          {pct(v)}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          <div style={{ marginTop: 16 }}>
            <button className="primary" type="submit"
              disabled={create.isPending || !!created}>
              {created ? "Booked" : create.isPending ? "Booking…" : "Book transaction"}
            </button>
          </div>

          {created && (
            <div className="success" style={{ marginTop: 14 }}>
              Booked {created.ref} <StatusBadge status={created.status} />
              <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                {created.status === "pending" && (
                  <button className="ghost" type="button"
                    onClick={() => settle.mutate(created.id)}>
                    {settle.isPending ? "Settling…" : "Settle now"}
                  </button>
                )}
                <button className="ghost" type="button"
                  onClick={() => navigate(`/clients/${created.client_id}`)}>
                  View client
                </button>
              </div>
            </div>
          )}
        </form>

        <div className="card">
          <h2>Live commission preview</h2>
          <p className="muted" style={{ fontSize: 13, marginTop: -6 }}>
            What settling this sale would pay (period 0). Matches the settled ledger.
            Override rates are a % of your commission (25/20/4/1% for the 1st–4th upline).
          </p>
          {!form.product_id && <div className="spinner">Pick a product to preview…</div>}
          {preview.isFetching && <div className="spinner">Calculating…</div>}
          {preview.data && (
            <>
              <table>
                <thead>
                  <tr>
                    <th>Beneficiary</th><th>Kind</th><th>Gap</th>
                    <th className="num">Rate</th><th className="num">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.data.lines.map((l, i) => (
                    <tr key={i}>
                      <td>{l.agent_id === agentId ? "You" : `Agent #${l.agent_id}`}</td>
                      <td>{l.kind}</td>
                      <td>{l.level_gap}</td>
                      <td className="num">{pct(l.rate)}</td>
                      <td className="num">{money(l.amount, form.currency)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={4} style={{ fontWeight: 700 }}>Total paid out</td>
                    <td className="num" style={{ fontWeight: 700 }}>
                      {money(preview.data.total, form.currency)}
                    </td>
                  </tr>
                </tfoot>
              </table>
              {selectedProduct?.commission_schedule === "trail" && (
                <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
                  Trail product: this repeats each {selectedProduct.trail_frequency} for{" "}
                  {selectedProduct.trail_periods} periods via accrual runs.
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
