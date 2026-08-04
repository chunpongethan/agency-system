import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { money, pct, currentPeriod } from "../lib/format";
import type { PayoutResult, PeriodInfo } from "../api/types";

const PRODUCT_TYPES = ["insurance", "fund", "eam_account", "other"];

export default function Admin() {
  const qc = useQueryClient();
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.products() });
  const rules = useQuery({ queryKey: ["overrideRules"], queryFn: () => api.overrideRules() });

  // --- Product form ---
  const [prod, setProd] = useState({
    code: "", name: "", type: "insurance", provider: "",
    base_commission_rate: "0.05", commission_schedule: "upfront",
    trail_frequency: "monthly", trail_periods: "12",
  });
  const [prodErr, setProdErr] = useState<string | null>(null);
  const createProduct = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        code: prod.code, name: prod.name, type: prod.type,
        provider: prod.provider || undefined,
        base_commission_rate: prod.base_commission_rate,
        commission_schedule: prod.commission_schedule,
      };
      if (prod.commission_schedule === "trail") {
        payload.trail_frequency = prod.trail_frequency;
        payload.trail_periods = Number(prod.trail_periods);
      }
      return api.createProduct(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      setProd({ ...prod, code: "", name: "" });
      setProdErr(null);
    },
    onError: (e) => setProdErr(e instanceof ApiError ? e.message : "Failed"),
  });

  // --- Override rule form ---
  const [rule, setRule] = useState({
    product_type: "insurance", level_gap: "1", override_rate: "0.015",
    valid_from: "", valid_to: "",
  });
  const [ruleErr, setRuleErr] = useState<string | null>(null);
  const createRule = useMutation({
    mutationFn: () =>
      api.createOverrideRule({
        product_type: rule.product_type,
        level_gap: Number(rule.level_gap),
        override_rate: rule.override_rate,
        valid_from: rule.valid_from || undefined,
        valid_to: rule.valid_to || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["overrideRules"] });
      setRuleErr(null);
    },
    onError: (e) => setRuleErr(e instanceof ApiError ? e.message : "Failed"),
  });

  // --- Period + payout ---
  const [ym, setYm] = useState(currentPeriod().ym);
  const period = useQuery<PeriodInfo>({
    queryKey: ["period", ym],
    queryFn: () => api.period(ym),
  });
  const lock = useMutation({
    mutationFn: () => api.lockPeriod(ym),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["period", ym] }),
  });
  const unlock = useMutation({
    mutationFn: () => api.unlockPeriod(ym),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["period", ym] }),
  });
  const [payout, setPayout] = useState<PayoutResult | null>(null);
  const [payoutErr, setPayoutErr] = useState<string | null>(null);
  const runPayout = useMutation({
    mutationFn: () => api.runPayout(ym),
    onSuccess: (r) => { setPayout(r); setPayoutErr(null); },
    onError: (e) => setPayoutErr(e instanceof ApiError ? e.message : "Failed"),
  });

  return (
    <div>
      <h1 className="page-title">Admin</h1>
      <p className="page-sub">Products, override rules, period control, and payouts</p>

      <div className="grid cols-2">
        {/* Products */}
        <div className="card">
          <h2>Products</h2>
          <table>
            <thead>
              <tr><th>Code</th><th>Name</th><th>Type</th><th className="num">Rate</th><th>Schedule</th></tr>
            </thead>
            <tbody>
              {products.data?.map((p) => (
                <tr key={p.id}>
                  <td>{p.code}</td><td>{p.name}</td><td>{p.type}</td>
                  <td className="num">{pct(p.base_commission_rate)}</td>
                  <td>{p.commission_schedule}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <form onSubmit={(e: FormEvent) => { e.preventDefault(); createProduct.mutate(); }}
            style={{ marginTop: 12 }}>
            <h2>Add product</h2>
            {prodErr && <div className="error">{prodErr}</div>}
            <div className="row">
              <div><label>Code</label>
                <input value={prod.code} required onChange={(e) => setProd({ ...prod, code: e.target.value })} /></div>
              <div><label>Name</label>
                <input value={prod.name} required onChange={(e) => setProd({ ...prod, name: e.target.value })} /></div>
            </div>
            <div className="row">
              <div><label>Type</label>
                <select value={prod.type} onChange={(e) => setProd({ ...prod, type: e.target.value })}>
                  {PRODUCT_TYPES.map((t) => <option key={t}>{t}</option>)}
                </select></div>
              <div><label>Base rate</label>
                <input value={prod.base_commission_rate} onChange={(e) => setProd({ ...prod, base_commission_rate: e.target.value })} /></div>
              <div><label>Schedule</label>
                <select value={prod.commission_schedule} onChange={(e) => setProd({ ...prod, commission_schedule: e.target.value })}>
                  <option value="upfront">upfront</option>
                  <option value="trail">trail</option>
                </select></div>
            </div>
            {prod.commission_schedule === "trail" && (
              <div className="row">
                <div><label>Frequency</label>
                  <select value={prod.trail_frequency} onChange={(e) => setProd({ ...prod, trail_frequency: e.target.value })}>
                    <option>monthly</option><option>quarterly</option><option>annual</option>
                  </select></div>
                <div><label>Periods</label>
                  <input type="number" value={prod.trail_periods} onChange={(e) => setProd({ ...prod, trail_periods: e.target.value })} /></div>
              </div>
            )}
            <div style={{ marginTop: 12 }}>
              <button className="primary" type="submit" disabled={createProduct.isPending}>Add product</button>
            </div>
          </form>
        </div>

        {/* Override rules */}
        <div className="card">
          <h2>Override rules</h2>
          <table>
            <thead>
              <tr><th>Product type</th><th>Gap</th><th className="num">Rate</th><th>From</th><th>To</th></tr>
            </thead>
            <tbody>
              {rules.data?.map((r) => (
                <tr key={r.id}>
                  <td>{r.product_type}</td><td>{r.level_gap}</td>
                  <td className="num">{pct(r.override_rate)}</td>
                  <td className="muted">{r.valid_from}</td>
                  <td className="muted">{r.valid_to ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <form onSubmit={(e: FormEvent) => { e.preventDefault(); createRule.mutate(); }}
            style={{ marginTop: 12 }}>
            <h2>Add / update rule</h2>
            {ruleErr && <div className="error">{ruleErr}</div>}
            <div className="row">
              <div><label>Product type</label>
                <select value={rule.product_type} onChange={(e) => setRule({ ...rule, product_type: e.target.value })}>
                  {PRODUCT_TYPES.map((t) => <option key={t}>{t}</option>)}
                </select></div>
              <div><label>Level gap</label>
                <select value={rule.level_gap} onChange={(e) => setRule({ ...rule, level_gap: e.target.value })}>
                  <option>1</option><option>2</option><option>3</option>
                </select></div>
              <div><label>Rate</label>
                <input value={rule.override_rate} onChange={(e) => setRule({ ...rule, override_rate: e.target.value })} /></div>
            </div>
            <div className="row">
              <div><label>Valid from</label>
                <input type="date" value={rule.valid_from} onChange={(e) => setRule({ ...rule, valid_from: e.target.value })} /></div>
              <div><label>Valid to</label>
                <input type="date" value={rule.valid_to} onChange={(e) => setRule({ ...rule, valid_to: e.target.value })} /></div>
            </div>
            <div style={{ marginTop: 12 }}>
              <button className="primary" type="submit" disabled={createRule.isPending}>Save rule</button>
            </div>
          </form>
        </div>
      </div>

      {/* Period + payout control */}
      <div className="card">
        <h2>Period control & payouts</h2>
        <div className="row">
          <div className="shrink" style={{ minWidth: 140 }}>
            <label>Period (YYYY-MM)</label>
            <input value={ym} onChange={(e) => setYm(e.target.value)} />
          </div>
          <div className="shrink" style={{ alignSelf: "flex-end", display: "flex", gap: 8 }}>
            {period.data?.is_locked ? (
              <button className="ghost" onClick={() => unlock.mutate()}>Unlock period</button>
            ) : (
              <button className="ghost" onClick={() => lock.mutate()}>Lock period</button>
            )}
            <button className="primary" onClick={() => runPayout.mutate()}>Run payout</button>
          </div>
          <div style={{ alignSelf: "flex-end" }}>
            {period.data && (
              <span className={`badge ${period.data.is_locked ? "cancelled" : "settled"}`}>
                {period.data.is_locked ? "locked" : "open"}
              </span>
            )}
          </div>
        </div>

        {payoutErr && <div className="error">{payoutErr}</div>}
        {payout && (
          <div style={{ marginTop: 14 }}>
            <div className="success">
              Payout {payout.period}: {payout.new_entries_paid} entries paid this run ·
              total {money(payout.total)}
            </div>
            <table>
              <thead><tr><th>Agent</th><th className="num">Payable</th></tr></thead>
              <tbody>
                {payout.payable.map((p) => (
                  <tr key={p.agent_id}>
                    <td>#{p.agent_id}</td>
                    <td className="num">{money(p.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
