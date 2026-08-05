import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { pct } from "../../lib/format";

const PRODUCT_TYPES = ["insurance", "fund", "eam_account", "other"];

export default function AdminProducts() {
  const qc = useQueryClient();
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.products() });

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

  return (
    <div>
      <h1 className="page-title">Products</h1>
      <p className="page-sub">Sellable products and their base commission rates</p>

      <div className="card">
        <h2>Catalogue</h2>
        <table>
          <thead>
            <tr><th>Code</th><th>Name</th><th>Type</th><th>Provider</th><th className="num">Base rate</th><th>Schedule</th></tr>
          </thead>
          <tbody>
            {products.data?.map((p) => (
              <tr key={p.id}>
                <td>{p.code}</td><td>{p.name}</td><td>{p.type}</td>
                <td className="muted">{p.provider ?? "—"}</td>
                <td className="num">{pct(p.base_commission_rate)}</td>
                <td>{p.commission_schedule}
                  {p.commission_schedule === "trail" && p.trail_periods
                    ? ` · ${p.trail_periods}× ${p.trail_frequency}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); createProduct.mutate(); }}>
        <h2>Add product</h2>
        {prodErr && <div className="error">{prodErr}</div>}
        <div className="row">
          <div><label>Code</label>
            <input value={prod.code} required onChange={(e) => setProd({ ...prod, code: e.target.value })} /></div>
          <div><label>Name</label>
            <input value={prod.name} required onChange={(e) => setProd({ ...prod, name: e.target.value })} /></div>
          <div><label>Provider</label>
            <input value={prod.provider} onChange={(e) => setProd({ ...prod, provider: e.target.value })} /></div>
        </div>
        <div className="row">
          <div><label>Type</label>
            <select value={prod.type} onChange={(e) => setProd({ ...prod, type: e.target.value })}>
              {PRODUCT_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select></div>
          <div><label>Base rate (of notional)</label>
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
  );
}
