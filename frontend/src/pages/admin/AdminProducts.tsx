import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { pct } from "../../lib/format";
import type { Product } from "../../api/types";

const PRODUCT_TYPES = ["insurance", "fund", "eam_account", "other"];

interface InsDetails {
  payment_tenor: string;
  professional_investor: string; // "yes" | "no"
  age_min: string;
  age_max: string;
  yearComm: string[]; // 10 entries
}

const emptyIns = (): InsDetails => ({
  payment_tenor: "10", professional_investor: "no", age_min: "0", age_max: "70",
  yearComm: Array(10).fill(""),
});

function fromProduct(p: Product): InsDetails {
  const yc = p.year_commissions ?? [];
  return {
    payment_tenor: p.payment_tenor != null ? String(p.payment_tenor) : "",
    professional_investor: p.professional_investor ? "yes" : "no",
    age_min: p.age_min != null ? String(p.age_min) : "",
    age_max: p.age_max != null ? String(p.age_max) : "",
    yearComm: Array.from({ length: 10 }, (_, i) => yc[i] ?? ""),
  };
}

function insPayload(d: InsDetails): Record<string, unknown> {
  return {
    payment_tenor: d.payment_tenor ? Number(d.payment_tenor) : null,
    professional_investor: d.professional_investor === "yes",
    age_min: d.age_min ? Number(d.age_min) : null,
    age_max: d.age_max ? Number(d.age_max) : null,
    year_commissions: d.yearComm.map((v) => (v.trim() === "" ? "0" : v)),
  };
}

// Shared insurance-detail input block (used by create + edit).
function InsuranceFields({ value, onChange }: { value: InsDetails; onChange: (d: InsDetails) => void }) {
  return (
    <div>
      <div className="row">
        <div>
          <label>Payment tenor (years)</label>
          <input type="number" min="1" value={value.payment_tenor}
            onChange={(e) => onChange({ ...value, payment_tenor: e.target.value })} />
        </div>
        <div>
          <label>Professional investor</label>
          <select value={value.professional_investor}
            onChange={(e) => onChange({ ...value, professional_investor: e.target.value })}>
            <option value="no">No</option>
            <option value="yes">Yes</option>
          </select>
        </div>
        <div>
          <label>Age range — min</label>
          <input type="number" min="0" max="120" value={value.age_min}
            onChange={(e) => onChange({ ...value, age_min: e.target.value })} />
        </div>
        <div>
          <label>Age range — max</label>
          <input type="number" min="0" max="120" value={value.age_max}
            onChange={(e) => onChange({ ...value, age_max: e.target.value })} />
        </div>
      </div>
      <label style={{ marginTop: 10 }}>Commission schedule — Yr1 to Yr10 (%)</label>
      <div className="year-grid">
        {value.yearComm.map((v, i) => (
          <div key={i} className="year-cell">
            <span className="yr-label">Yr{i + 1}</span>
            <input type="number" step="0.01" min="0" placeholder="0" value={v}
              onChange={(e) => {
                const next = [...value.yearComm];
                next[i] = e.target.value;
                onChange({ ...value, yearComm: next });
              }} />
          </div>
        ))}
      </div>
    </div>
  );
}

function ageRange(p: Product): string {
  if (p.age_min == null && p.age_max == null) return "—";
  return `${p.age_min ?? 0}–${p.age_max ?? "?"}`;
}

export default function AdminProducts() {
  const qc = useQueryClient();
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.products() });

  const [prod, setProd] = useState({
    code: "", name: "", type: "insurance", provider: "",
    base_commission_rate: "0.05", commission_schedule: "upfront",
    trail_frequency: "monthly", trail_periods: "12",
  });
  const [ins, setIns] = useState<InsDetails>(emptyIns());
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
      if (prod.type === "insurance") Object.assign(payload, insPayload(ins));
      return api.createProduct(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      setProd({ ...prod, code: "", name: "" });
      setIns(emptyIns());
      setProdErr(null);
    },
    onError: (e) => setProdErr(e instanceof ApiError ? e.message : "Failed"),
  });

  // --- Editing an existing insurance product's details ---
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editIns, setEditIns] = useState<InsDetails>(emptyIns());
  const [editErr, setEditErr] = useState<string | null>(null);
  const updateProduct = useMutation({
    mutationFn: () => api.updateProduct(editingId!, insPayload(editIns)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      setEditingId(null);
      setEditErr(null);
    },
    onError: (e) => setEditErr(e instanceof ApiError ? e.message : "Failed"),
  });

  function startEdit(p: Product) {
    setEditingId(p.id);
    setEditIns(fromProduct(p));
    setEditErr(null);
  }

  return (
    <div>
      <h1 className="page-title">Products</h1>
      <p className="page-sub">
        Sellable products and their commission rates. Insurance products carry extra details
        (tenor, age range, professional-investor flag, Yr1–Yr10 schedule) maintained here.
      </p>

      <div className="card">
        <h2>Catalogue</h2>
        <table>
          <thead>
            <tr>
              <th>Code</th><th>Name</th><th>Type</th><th className="num">Base rate</th>
              <th>Schedule</th><th>Insurance details</th><th></th>
            </tr>
          </thead>
          <tbody>
            {products.data?.map((p) => (
              <tr key={p.id}>
                <td>{p.code}</td><td>{p.name}</td><td>{p.type}</td>
                <td className="num">{pct(p.base_commission_rate)}</td>
                <td>{p.commission_schedule}</td>
                <td className="muted" style={{ fontSize: 12 }}>
                  {p.type === "insurance"
                    ? `tenor ${p.payment_tenor ?? "—"}y · age ${ageRange(p)} · PI ${p.professional_investor ? "Y" : "N"}`
                    : "—"}
                </td>
                <td className="num">
                  {p.type === "insurance" && (
                    <button className="ghost" onClick={() => startEdit(p)}>Edit details</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editingId != null && (
        <div className="card">
          <h2>Edit insurance details — {products.data?.find((p) => p.id === editingId)?.name}</h2>
          {editErr && <div className="error">{editErr}</div>}
          <InsuranceFields value={editIns} onChange={setEditIns} />
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button className="primary" onClick={() => updateProduct.mutate()} disabled={updateProduct.isPending}>
              {updateProduct.isPending ? "Saving…" : "Save details"}
            </button>
            <button className="ghost" onClick={() => setEditingId(null)}>Cancel</button>
          </div>
        </div>
      )}

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
        {prod.type === "insurance" && (
          <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
            <h2 style={{ fontSize: 14 }}>Insurance details</h2>
            <InsuranceFields value={ins} onChange={setIns} />
          </div>
        )}
        <div style={{ marginTop: 12 }}>
          <button className="primary" type="submit" disabled={createProduct.isPending}>Add product</button>
        </div>
      </form>
    </div>
  );
}
