import { useMemo, useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, errorText } from "../api/client";
import { useI18n } from "../i18n/LanguageContext";
import { money, pct } from "../lib/format";
import { kindLabel, scheduleLabel, frequencyLabel } from "../i18n/labels";
import StatusBadge from "../components/StatusBadge";
import type { Transaction } from "../api/types";

export default function NewTransaction() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Transaction | null>(null);

  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api.agents() });
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api.clients() });
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.products() });
  const nextRef = useQuery({ queryKey: ["nextRef"], queryFn: () => api.nextTransactionRef() });

  const [form, setForm] = useState({
    lead_agent_id: "",
    sales_dev_agent_id: "",
    agent_id: "",            // closing agent
    client_id: "",
    product_id: "",
    notional: "100000",
    currency: "USD",
    lead_pct: "0",
    sales_dev_pct: "0",
    closing_pct: "100",
  });

  const agentId = Number(form.agent_id) || 0;   // closing agent
  const notionalNum = Number(form.notional) || 0;
  const pctSum = Number(form.lead_pct || 0) + Number(form.sales_dev_pct || 0) + Number(form.closing_pct || 0);
  const pctValid = Math.round(pctSum * 100) === 10000;
  const rolesChosen = !!form.lead_agent_id && !!form.sales_dev_agent_id && !!form.agent_id;

  // Non-admin active agents are eligible for any role.
  const closerOptions = (agents.data ?? []).filter((a) => a.role !== "admin" && a.is_active);
  // Clients belonging to the chosen closing agent.
  const clientOptions = (clients.data ?? []).filter((c) => c.agent_id === agentId);
  const agentName = (id: number) => agents.data?.find((a) => a.id === id)?.name ?? `#${id}`;

  const selectedProduct = useMemo(
    () => products.data?.find((p) => p.id === Number(form.product_id)),
    [products.data, form.product_id],
  );
  const isInsurance = selectedProduct?.type === "insurance";

  const rolePayload = () => ({
    lead_agent_id: form.lead_agent_id ? Number(form.lead_agent_id) : null,
    sales_dev_agent_id: form.sales_dev_agent_id ? Number(form.sales_dev_agent_id) : null,
    lead_pct: form.lead_pct || "0",
    sales_dev_pct: form.sales_dev_pct || "0",
    closing_pct: form.closing_pct || "0",
  });

  const preview = useQuery({
    queryKey: ["preview", form.product_id, agentId, notionalNum,
               form.lead_agent_id, form.sales_dev_agent_id, form.lead_pct, form.sales_dev_pct, form.closing_pct],
    queryFn: () =>
      api.previewTransaction({
        product_id: Number(form.product_id),
        agent_id: agentId,
        notional: form.notional,
        ...rolePayload(),
      }),
    enabled: !!form.product_id && rolesChosen && notionalNum > 0 && pctValid,
  });

  const create = useMutation({
    mutationFn: () =>
      api.createTransaction({
        client_id: Number(form.client_id),
        product_id: Number(form.product_id),
        agent_id: agentId,
        notional: form.notional,
        currency: form.currency,
        ...rolePayload(),
      }),
    onSuccess: (txn) => {
      setCreated(txn);
      setError(null);
      qc.invalidateQueries({ queryKey: ["nextRef"] });
    },
    onError: (e) => setError(errorText(e, t) || t("newTxn.createFailed")),
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
      <h1 className="page-title">{t("newTxn.title")}</h1>
      <p className="page-sub">{t("newTxn.subtitle")}</p>

      <div className="grid cols-2">
        <form className="card" onSubmit={onSubmit}>
          <h2>{t("newTxn.details")}</h2>
          {error && <div className="error">{error}</div>}

          <label>{t("newTxn.txnCode")}</label>
          <input value={nextRef.data?.ref ?? "…"} readOnly disabled />

          <label>{t("newTxn.leadAgent")}</label>
          <select value={form.lead_agent_id} required
            onChange={(e) => setForm({ ...form, lead_agent_id: e.target.value })}>
            <option value="">{t("newTxn.selectAgent")}</option>
            {closerOptions.map((a) => (
              <option key={a.id} value={a.id}>{a.name} ({a.code}) · L{a.level}</option>
            ))}
          </select>

          <label>{t("newTxn.salesDevAgent")}</label>
          <select value={form.sales_dev_agent_id} required
            onChange={(e) => setForm({ ...form, sales_dev_agent_id: e.target.value })}>
            <option value="">{t("newTxn.selectAgent")}</option>
            {closerOptions.map((a) => (
              <option key={a.id} value={a.id}>{a.name} ({a.code}) · L{a.level}</option>
            ))}
          </select>

          <label>{t("newTxn.closingAgent")}</label>
          <select value={form.agent_id} required
            onChange={(e) => setForm({ ...form, agent_id: e.target.value, client_id: "" })}>
            <option value="">{t("newTxn.selectAgent")}</option>
            {closerOptions.map((a) => (
              <option key={a.id} value={a.id}>{a.name} ({a.code}) · L{a.level}</option>
            ))}
          </select>

          <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <h2 style={{ fontSize: 14 }}>{t("newTxn.splitTitle")}</h2>
              {!pctValid && <span style={{ fontSize: 12, color: "var(--bad)" }}>{t("newTxn.splitMustBe100", { sum: pctSum })}</span>}
            </div>
            <div className="row">
              <div>
                <label>{t("newTxn.pctLead")}</label>
                <input type="number" min="0" max="100" step="1" value={form.lead_pct}
                  onChange={(e) => setForm({ ...form, lead_pct: e.target.value })} />
              </div>
              <div>
                <label>{t("newTxn.pctSalesDev")}</label>
                <input type="number" min="0" max="100" step="1" value={form.sales_dev_pct}
                  onChange={(e) => setForm({ ...form, sales_dev_pct: e.target.value })} />
              </div>
              <div>
                <label>{t("newTxn.pctClosing")}</label>
                <input type="number" min="0" max="100" step="1" value={form.closing_pct}
                  onChange={(e) => setForm({ ...form, closing_pct: e.target.value })} />
              </div>
            </div>
            <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>{t("newTxn.splitNote")}</p>
          </div>

          <label>{t("newTxn.client")} {form.agent_id && clientOptions.length === 0 ? t("newTxn.agentNoClients") : ""}</label>
          <select value={form.client_id} required disabled={!form.agent_id}
            onChange={(e) => setForm({ ...form, client_id: e.target.value })}>
            <option value="">{form.agent_id ? t("newTxn.selectClient") : t("newTxn.pickAgentFirst")}</option>
            {clientOptions.map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.ref})</option>
            ))}
          </select>

          <label>{t("common.product")}</label>
          <select value={form.product_id} required
            onChange={(e) => setForm({ ...form, product_id: e.target.value })}>
            <option value="">{t("newTxn.selectProduct")}</option>
            {products.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {pct(p.base_commission_rate)} {scheduleLabel(p.commission_schedule)}
              </option>
            ))}
          </select>

          <div className="row">
            <div style={{ flex: 3 }}>
              <label>{t("common.notional")}</label>
              <input type="number" value={form.notional} min="0" step="1000"
                onChange={(e) => setForm({ ...form, notional: e.target.value })} />
            </div>
            <div style={{ flex: 1 }}>
              <label>{t("newTxn.currency")}</label>
              <select value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}>
                <option>USD</option><option>HKD</option><option>EUR</option><option>GBP</option>
              </select>
            </div>
          </div>

          {isInsurance && selectedProduct && (
            <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <h2 style={{ fontSize: 14 }}>{t("newTxn.insuranceDetails")}</h2>
                <span className="muted" style={{ fontSize: 11 }}>{t("newTxn.adminReadonly")}</span>
              </div>
              <div className="grid cols-3" style={{ gap: 10 }}>
                <div className="stat">
                  <div className="label">{t("newTxn.paymentTenor")}</div>
                  <div className="value" style={{ fontSize: 18 }}>
                    {selectedProduct.payment_tenor != null ? t("newTxn.years", { n: selectedProduct.payment_tenor }) : "—"}
                  </div>
                </div>
                <div className="stat">
                  <div className="label">{t("newTxn.ageRange")}</div>
                  <div className="value" style={{ fontSize: 18 }}>
                    {selectedProduct.age_min != null || selectedProduct.age_max != null
                      ? `${selectedProduct.age_min ?? 0}–${selectedProduct.age_max ?? "?"}` : "—"}
                  </div>
                </div>
                <div className="stat">
                  <div className="label">{t("newTxn.professionalInvestor")}</div>
                  <div className="value" style={{ fontSize: 18 }}>
                    {selectedProduct.professional_investor == null
                      ? "—" : selectedProduct.professional_investor ? t("newTxn.yes") : t("newTxn.no")}
                  </div>
                </div>
              </div>
              {selectedProduct.year_commissions && selectedProduct.year_commissions.length > 0 && (
                <>
                  <label style={{ marginTop: 10 }}>{t("newTxn.commSchedule")}</label>
                  <div className="year-grid">
                    {selectedProduct.year_commissions.map((v, i) => (
                      <div key={i} className="year-cell">
                        <span className="yr-label">{t("newTxn.yr", { n: i + 1 })}</span>
                        <div style={{ fontVariantNumeric: "tabular-nums", fontSize: 13, fontWeight: 600 }}>{pct(v)}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          <div style={{ marginTop: 16 }}>
            <button className="primary" type="submit" disabled={create.isPending || !!created || !pctValid}>
              {created ? t("newTxn.booked") : create.isPending ? t("newTxn.booking") : t("newTxn.book")}
            </button>
          </div>

          {created && (
            <div className="success" style={{ marginTop: 14 }}>
              {t("newTxn.bookedMsg", { ref: created.ref })} <StatusBadge status={created.status} />
              <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                {created.status === "pending" && (
                  <button className="ghost" type="button" onClick={() => settle.mutate(created.id)}>
                    {settle.isPending ? t("newTxn.settling") : t("newTxn.settleNow")}
                  </button>
                )}
                <button className="ghost" type="button" onClick={() => navigate(`/clients/${created.client_id}`)}>
                  {t("newTxn.viewClient")}
                </button>
              </div>
            </div>
          )}
        </form>

        <div className="card">
          <h2>{t("newTxn.previewTitle")}</h2>
          <p className="muted" style={{ fontSize: 13, marginTop: -6 }}>
            {t("newTxn.previewNote")}
          </p>
          {(!form.product_id || !form.agent_id) && <div className="spinner">{t("newTxn.previewPrompt")}</div>}
          {preview.isFetching && <div className="spinner">{t("newTxn.calculating")}</div>}
          {preview.data && (
            <>
              <table>
                <thead>
                  <tr>
                    <th>{t("newTxn.thBeneficiary")}</th><th>{t("newTxn.thKind")}</th><th>{t("newTxn.thGap")}</th>
                    <th className="num">{t("newTxn.thRate")}</th><th className="num">{t("newTxn.thAmount")}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.data.lines.map((l, i) => (
                    <tr key={i}>
                      <td>{agentName(l.agent_id)}</td>
                      <td>{kindLabel(l.kind)}</td>
                      <td>{l.level_gap}</td>
                      <td className="num">{pct(l.rate)}</td>
                      <td className="num">{money(l.amount, form.currency)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={4} style={{ fontWeight: 700 }}>{t("newTxn.totalPaid")}</td>
                    <td className="num" style={{ fontWeight: 700 }}>{money(preview.data.total, form.currency)}</td>
                  </tr>
                </tfoot>
              </table>
              {selectedProduct?.commission_schedule === "trail" && (
                <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
                  {t("newTxn.trailNote", { frequency: frequencyLabel(selectedProduct.trail_frequency), periods: selectedProduct.trail_periods ?? 0 })}
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
