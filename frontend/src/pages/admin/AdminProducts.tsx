import { useState, type FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../../api/client";
import { useI18n } from "../../i18n/LanguageContext";
import { pct } from "../../lib/format";
import { productTypeLabel, scheduleLabel, frequencyLabel, PRODUCT_TYPES, SCHEDULES, FREQUENCIES } from "../../i18n/labels";
import type { Product } from "../../api/types";

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

// The Yr1–Yr10 inputs are entered as ACTUAL percentages (e.g. 5.00 = 5%), while
// the backend stores commission rates as fractions (0.05). Convert at the edges.
function fracToPct(frac: string | null | undefined): string {
  if (frac == null || String(frac).trim() === "") return "";
  return String(Math.round(Number(frac) * 10000) / 100);   // 0.0525 -> "5.25"
}
function pctToFrac(pctStr: string): string {
  if (pctStr.trim() === "") return "0";
  return (Number(pctStr) / 100).toFixed(4);                 // "5.25" -> "0.0525"
}

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
      yearComm: Array.from({ length: 10 }, (_, i) => fracToPct(yc[i])),
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
    // For insurance the base rate is the Yr1 commission (backend enforces this too).
    // Yr inputs are percentages; convert to the stored fraction.
    base_commission_rate: isIns ? pctToFrac(f.ins.yearComm[0] ?? "") : f.base_commission_rate,
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
    payload.year_commissions = f.ins.yearComm.map((v) => pctToFrac(v));
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
  const { t } = useI18n();
  const isIns = value.type === "insurance";
  const setIns = (ins: InsDetails) => onChange({ ...value, ins });
  return (
    <>
      <div className="row">
        <div><label>{t("common.code")}</label>
          <input value={value.code} required readOnly={isEdit} disabled={isEdit}
            onChange={(e) => onChange({ ...value, code: e.target.value })} /></div>
        <div><label>{t("common.name")}</label>
          <input value={value.name} required onChange={(e) => onChange({ ...value, name: e.target.value })} /></div>
        <div><label>{t("admin.products.provider")}</label>
          <input value={value.provider} onChange={(e) => onChange({ ...value, provider: e.target.value })} /></div>
      </div>
      <div className="row">
        <div><label>{t("common.type")}</label>
          <select value={value.type} disabled={isEdit}
            onChange={(e) => onChange({ ...value, type: e.target.value })}>
            {PRODUCT_TYPES.map((pt) => <option key={pt} value={pt}>{productTypeLabel(pt)}</option>)}
          </select></div>
        {isIns ? (
          <div><label>{t("admin.products.thBaseRate")}</label>
            <input value={value.ins.yearComm[0]?.trim() ? `${Number(value.ins.yearComm[0]).toFixed(2)}%` : t("admin.products.baseRateEqYr1")}
              readOnly disabled /></div>
        ) : (
          <div><label>{t("admin.products.baseRateNotional")}</label>
            <input value={value.base_commission_rate}
              onChange={(e) => onChange({ ...value, base_commission_rate: e.target.value })} /></div>
        )}
        <div><label>{t("admin.products.afypConversion")}</label>
          <input value={value.afyp_conversion}
            onChange={(e) => onChange({ ...value, afyp_conversion: e.target.value })} /></div>
        <div><label>{t("admin.products.schedule")}</label>
          <select value={value.commission_schedule}
            onChange={(e) => onChange({ ...value, commission_schedule: e.target.value })}>
            {SCHEDULES.map((s) => <option key={s} value={s}>{scheduleLabel(s)}</option>)}
          </select></div>
      </div>
      {value.commission_schedule === "trail" && (
        <div className="row">
          <div><label>{t("admin.products.frequency")}</label>
            <select value={value.trail_frequency}
              onChange={(e) => onChange({ ...value, trail_frequency: e.target.value })}>
              {FREQUENCIES.map((f) => <option key={f} value={f}>{frequencyLabel(f)}</option>)}
            </select></div>
          <div><label>{t("admin.products.periods")}</label>
            <input type="number" value={value.trail_periods}
              onChange={(e) => onChange({ ...value, trail_periods: e.target.value })} /></div>
        </div>
      )}
      {isIns && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
          <h2 style={{ fontSize: 14 }}>{t("admin.products.insDetails")}</h2>
          <p className="muted" style={{ fontSize: 12, marginTop: -6 }}>
            {t("admin.products.insBaseNote")}
          </p>
          <div className="row">
            <div><label>{t("admin.products.paymentTenor")}</label>
              <input type="number" min="1" value={value.ins.payment_tenor}
                onChange={(e) => setIns({ ...value.ins, payment_tenor: e.target.value })} /></div>
            <div><label>{t("newTxn.professionalInvestor")}</label>
              <select value={value.ins.professional_investor}
                onChange={(e) => setIns({ ...value.ins, professional_investor: e.target.value })}>
                <option value="no">{t("newTxn.no")}</option><option value="yes">{t("newTxn.yes")}</option>
              </select></div>
            <div><label>{t("admin.products.ageMin")}</label>
              <input type="number" min="0" max="120" value={value.ins.age_min}
                onChange={(e) => setIns({ ...value.ins, age_min: e.target.value })} /></div>
            <div><label>{t("admin.products.ageMax")}</label>
              <input type="number" min="0" max="120" value={value.ins.age_max}
                onChange={(e) => setIns({ ...value.ins, age_max: e.target.value })} /></div>
          </div>
          <label style={{ marginTop: 10 }}>{t("admin.products.commScheduleYr")}</label>
          <div className="year-grid">
            {value.ins.yearComm.map((v, i) => (
              <div key={i} className="year-cell">
                <span className="yr-label">{i === 0 ? t("admin.products.yrBase", { n: 1 }) : t("admin.products.yr", { n: i + 1 })}</span>
                <input type="number" step="0.01" min="0" max="999.99" placeholder="0.00" value={v}
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
  const { t } = useI18n();
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
    onError: (e) => setCreateErr(errorText(e, t) || t("admin.products.failed")),
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
    onError: (e) => setEditErr(errorText(e, t) || t("admin.products.failed")),
  });

  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [actionOk, setActionOk] = useState(false);
  const removeProduct = useMutation({
    mutationFn: (id: number) => api.deleteProduct(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      setActionMsg(t("admin.products.deleted")); setActionOk(true);
      setTimeout(() => setActionMsg(null), 3000);
    },
    onError: (e) => { setActionMsg(errorText(e, t) || t("admin.products.deleteFailed")); setActionOk(false); },
  });

  function startEdit(p: Product) {
    setEditId(p.id);
    setEditForm(formFromProduct(p));
    setEditErr(null);
  }
  function confirmDelete(p: Product) {
    if (window.confirm(t("admin.products.confirmDelete", { name: p.name, code: p.code }))) {
      removeProduct.mutate(p.id);
    }
  }

  return (
    <div>
      <h1 className="page-title">{t("admin.products.title")}</h1>
      <p className="page-sub">{t("admin.products.subtitle")}</p>

      <div className="card">
        <h2>{t("admin.products.catalogue")}</h2>
        {actionMsg && <div className={actionOk ? "success" : "error"}>{actionMsg}</div>}
        <table>
          <thead>
            <tr>
              <th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("common.type")}</th><th className="num">{t("admin.products.thBaseRate")}</th>
              <th className="num">{t("admin.products.thAfypConv")}</th><th>{t("admin.products.thSchedule")}</th><th>{t("admin.products.thInsuranceDetails")}</th><th></th>
            </tr>
          </thead>
          <tbody>
            {products.data?.map((p) => (
              <tr key={p.id}>
                <td>{p.code}</td><td>{p.name}</td><td>{productTypeLabel(p.type)}</td>
                <td className="num">{pct(p.base_commission_rate)}</td>
                <td className="num">{pct(p.afyp_conversion)}</td>
                <td>{scheduleLabel(p.commission_schedule)}</td>
                <td className="muted" style={{ fontSize: 12 }}>
                  {p.type === "insurance"
                    ? t("admin.products.insSummary", { tenor: p.payment_tenor ?? "—", age: ageRange(p), pi: p.professional_investor ? "Y" : "N" })
                    : "—"}
                </td>
                <td className="num" style={{ whiteSpace: "nowrap" }}>
                  <button className="ghost" onClick={() => startEdit(p)}>{t("common.edit")}</button>{" "}
                  <button className="ghost" onClick={() => confirmDelete(p)}
                    style={{ color: "var(--bad)" }}>{t("common.delete")}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editId != null && (
        <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); updateProduct.mutate(); }}>
          <h2>{t("admin.products.editTitle", { name: editForm.name, code: editForm.code })}</h2>
          {editErr && <div className="error">{editErr}</div>}
          <ProductFields value={editForm} onChange={setEditForm} isEdit />
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button className="primary" type="submit" disabled={updateProduct.isPending}>
              {updateProduct.isPending ? t("common.saving") : t("admin.agents.saveChanges")}
            </button>
            <button className="ghost" type="button" onClick={() => setEditId(null)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}

      <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); createProduct.mutate(); }}>
        <h2>{t("admin.products.add")}</h2>
        {createErr && <div className="error">{createErr}</div>}
        <ProductFields value={form} onChange={setForm} isEdit={false} />
        <div style={{ marginTop: 12 }}>
          <button className="primary" type="submit" disabled={createProduct.isPending}>{t("admin.products.add")}</button>
        </div>
      </form>
    </div>
  );
}
