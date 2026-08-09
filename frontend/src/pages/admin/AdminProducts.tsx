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

interface PForm {
  code: string;
  name: string;
  type: string;
  provider: string;
  base_commission_rate: string;
  afyp_conversion: string;
  commission_schedule: string;
  trail_frequency: string;
  trail_periods: string;
  ins: InsDetails;
}

const emptyIns = (): InsDetails => ({
  payment_tenor: "10", professional_investor: "no", age_min: "0", age_max: "70",
  yearComm: Array(10).fill(""),
});

const emptyForm = (): PForm => ({
  code: "", name: "", type: "insurance", provider: "",
  base_commission_rate: "0.05", afyp_conversion: "1", commission_schedule: "upfront",
  trail_frequency: "monthly", trail_periods: "12", ins: emptyIns(),
});

function formFromProduct(p: Product): PForm {
  const yc = p.year_commissions ?? [];
  return {
    code: p.code, name: p.name, type: p.type, provider: p.provider ?? "",
    base_commission_rate: p.base_commission_rate,
    afyp_conversion: p.afyp_conversion,
    commission_schedule: p.commission_schedule,
    trail_frequency: p.trail_frequency ?? "monthly",
    trail_periods: p.trail_periods != null ? String(p.trail_periods) : "12",
    ins: {
      payment_tenor: p.payment_tenor != null ? String(p.payment_tenor) : "",
      professional_investor: p.professional_investor ? "yes" : "no",
      age_min: p.age_min != null ? String(p.age_min) : "",
      age_max: p.age_max != null ? String(p.age_max) : "",
      yearComm: Array.from({ length: 10 }, (_, i) => yc[i] ?? ""),
    },
  };
}

function buildPayload(f: PForm, forCreate: boolean): Record<string, unknown> {
  const isIns = f.type === "insurance";
  const payload: Record<string, unknown> = {
    name: f.name,
    provider: f.provider || undefined,
    commission_schedule: f.commission_schedule,
    afyp_conversion: f.afyp_conversion,
    // For insurance the base rate is the Yr1 commission; the backend enforces this too.
    base_commission_rate: isIns ? (f.ins.yearComm[0]?.trim() || "0") : f.base_commission_rate,
  };
  if (forCreate) {
    payload.code = f.code;
    payload.type = f.type;
  }
  if (f.commission_schedule === "trail") {
    payload.trail_frequency = f.trail_frequency;
    payload.trail_periods = Number(f.trail_periods);
  }
  if (isIns) {
    payload.payment_tenor = f.ins.payment_tenor ? Number(f.ins.payment_tenor) : null;
    payload.professional_investor = f.ins.professional_investor === "yes";
    payload.age_min = f.ins.age_min ? Number(f.ins.age_min) : null;
    payload.age_max = f.ins.age_max ? Number(f.ins.age_max) : null;
    payload.year_commissions = f.ins.yearComm.map((v) => (v.trim() === "" ? "0" : v));
  }
  return payload;
}

function ageRange(p: Product): string {
  if (p.age_min == null && p.age_max == null) return "—";
  return `${p.age_min ?? 0}–${p.age_max ?? "?"}`;
}

// Shared field set for create + edit. code/type are read-only when editing.
function ProductFields({ value, onChange, isEdit }:
  { value: PForm; onChange: (f: PForm) => void; isEdit: boolean }) {
  const isIns = value.type === "insurance";
  const setIns = (ins: InsDetails) => onChange({ ...value, ins });
  return (
    <>
      <div className="row">
        <div><label>Code</label>
          <input value={value.code} required readOnly={isEdit} disabled={isEdit}
            onChange={(e) => onChange({ ...value, code: e.target.value })} /></div>
        <div><label>Name</label>
          <input value={value.name} required onChange={(e) => onChange({ ...value, name: e.target.value })} /></div>
        <div><label>Provider</label>
          <input value={value.provider} onChange={(e) => onChange({ ...value, provider: e.target.value })} /></div>
      </div>
      <div className="row">
        <div><label>Type</label>
          <select value={value.type} disabled={isEdit}
            onChange={(e) => onChange({ ...value, type: e.target.value })}>
            {PRODUCT_TYPES.map((t) => <option key={t}>{t}</option>)}
          </select></div>
        {isIns ? (
          <div><label>Base rate</label>
            <input value={value.ins.yearComm[0]?.trim() ? pct(value.ins.yearComm[0]) : "= Yr1 commission"}
              readOnly disabled /></div>
        ) : (
          <div><label>Base rate (of notional)</label>
            <input value={value.base_commission_rate}
              onChange={(e) => onChange({ ...value, base_commission_rate: e.target.value })} /></div>
        )}
        <div><label>AFYP conversion (e.g. 1 = 100%)</label>
          <input value={value.afyp_conversion}
            onChange={(e) => onChange({ ...value, afyp_conversion: e.target.value })} /></div>
        <div><label>Schedule</label>
          <select value={value.commission_schedule}
            onChange={(e) => onChange({ ...value, commission_schedule: e.target.value })}>
            <option value="upfront">upfront</option>
            <option value="trail">trail</option>
          </select></div>
      </div>
      {value.commission_schedule === "trail" && (
        <div className="row">
          <div><label>Frequency</label>
            <select value={value.trail_frequency}
              onChange={(e) => onChange({ ...value, trail_frequency: e.target.value })}>
              <option>monthly</option><option>quarterly</option><option>annual</option>
            </select></div>
          <div><label>Periods</label>
            <input type="number" value={value.trail_periods}
              onChange={(e) => onChange({ ...value, trail_periods: e.target.value })} /></div>
        </div>
      )}
      {isIns && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
          <h2 style={{ fontSize: 14 }}>Insurance details</h2>
          <p className="muted" style={{ fontSize: 12, marginTop: -6 }}>
            The base (upfront) rate is set to the Yr1 commission below.
          </p>
          <div className="row">
            <div><label>Payment tenor (years)</label>
              <input type="number" min="1" value={value.ins.payment_tenor}
                onChange={(e) => setIns({ ...value.ins, payment_tenor: e.target.value })} /></div>
            <div><label>Professional investor</label>
              <select value={value.ins.professional_investor}
                onChange={(e) => setIns({ ...value.ins, professional_investor: e.target.value })}>
                <option value="no">No</option><option value="yes">Yes</option>
              </select></div>
            <div><label>Age range — min</label>
              <input type="number" min="0" max="120" value={value.ins.age_min}
                onChange={(e) => setIns({ ...value.ins, age_min: e.target.value })} /></div>
            <div><label>Age range — max</label>
              <input type="number" min="0" max="120" value={value.ins.age_max}
                onChange={(e) => setIns({ ...value.ins, age_max: e.target.value })} /></div>
          </div>
          <label style={{ marginTop: 10 }}>Commission schedule — Yr1 to Yr10 (%)</label>
          <div className="year-grid">
            {value.ins.yearComm.map((v, i) => (
              <div key={i} className="year-cell">
                <span className="yr-label">Yr{i + 1}{i === 0 ? " · base" : ""}</span>
                <input type="number" step="0.01" min="0" placeholder="0" value={v}
                  onChange={(e) => {
                    const next = [...value.ins.yearComm];
                    next[i] = e.target.value;
                    setIns({ ...value.ins, yearComm: next });
                  }} />
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

export default function AdminProducts() {
  const qc = useQueryClient();
  const products = useQuery({ queryKey: ["products"], queryFn: () => api.products() });

  const [form, setForm] = useState<PForm>(emptyForm());
  const [createErr, setCreateErr] = useState<string | null>(null);
  const createProduct = useMutation({
    mutationFn: () => api.createProduct(buildPayload(form, true)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      setForm(emptyForm());
      setCreateErr(null);
    },
    onError: (e) => setCreateErr(e instanceof ApiError ? e.message : "Failed"),
  });

  const [editId, setEditId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<PForm>(emptyForm());
  const [editErr, setEditErr] = useState<string | null>(null);
  const updateProduct = useMutation({
    mutationFn: () => api.updateProduct(editId!, buildPayload(editForm, false)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      setEditId(null);
      setEditErr(null);
    },
    onError: (e) => setEditErr(e instanceof ApiError ? e.message : "Failed"),
  });

  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const removeProduct = useMutation({
    mutationFn: (id: number) => api.deleteProduct(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      setActionMsg("Product deleted.");
      setTimeout(() => setActionMsg(null), 3000);
    },
    onError: (e) => { setActionMsg(e instanceof ApiError ? e.message : "Delete failed"); },
  });

  function startEdit(p: Product) {
    setEditId(p.id);
    setEditForm(formFromProduct(p));
    setEditErr(null);
  }
  function confirmDelete(p: Product) {
    if (window.confirm(`Delete product ${p.name} (${p.code})? This cannot be undone.`)) {
      removeProduct.mutate(p.id);
    }
  }

  return (
    <div>
      <h1 className="page-title">Products</h1>
      <p className="page-sub">
        Create, edit and delete products. Insurance products carry extra details (tenor, age range,
        professional-investor flag, Yr1–Yr10 schedule); their base rate equals the Yr1 commission.
      </p>

      <div className="card">
        <h2>Catalogue</h2>
        {actionMsg && <div className={actionMsg.includes("deleted") ? "success" : "error"}>{actionMsg}</div>}
        <table>
          <thead>
            <tr>
              <th>Code</th><th>Name</th><th>Type</th><th className="num">Base rate</th>
              <th className="num">AFYP conv.</th><th>Schedule</th><th>Insurance details</th><th></th>
            </tr>
          </thead>
          <tbody>
            {products.data?.map((p) => (
              <tr key={p.id}>
                <td>{p.code}</td><td>{p.name}</td><td>{p.type}</td>
                <td className="num">{pct(p.base_commission_rate)}</td>
                <td className="num">{pct(p.afyp_conversion)}</td>
                <td>{p.commission_schedule}</td>
                <td className="muted" style={{ fontSize: 12 }}>
                  {p.type === "insurance"
                    ? `tenor ${p.payment_tenor ?? "—"}y · age ${ageRange(p)} · PI ${p.professional_investor ? "Y" : "N"}`
                    : "—"}
                </td>
                <td className="num" style={{ whiteSpace: "nowrap" }}>
                  <button className="ghost" onClick={() => startEdit(p)}>Edit</button>{" "}
                  <button className="ghost" onClick={() => confirmDelete(p)}
                    style={{ color: "var(--bad)" }}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editId != null && (
        <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); updateProduct.mutate(); }}>
          <h2>Edit product — {editForm.name} ({editForm.code})</h2>
          {editErr && <div className="error">{editErr}</div>}
          <ProductFields value={editForm} onChange={setEditForm} isEdit />
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button className="primary" type="submit" disabled={updateProduct.isPending}>
              {updateProduct.isPending ? "Saving…" : "Save changes"}
            </button>
            <button className="ghost" type="button" onClick={() => setEditId(null)}>Cancel</button>
          </div>
        </form>
      )}

      <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); createProduct.mutate(); }}>
        <h2>Add product</h2>
        {createErr && <div className="error">{createErr}</div>}
        <ProductFields value={form} onChange={setForm} isEdit={false} />
        <div style={{ marginTop: 12 }}>
          <button className="primary" type="submit" disabled={createProduct.isPending}>Add product</button>
        </div>
      </form>
    </div>
  );
}
