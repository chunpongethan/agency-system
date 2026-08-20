import { useMemo, useState, type ReactNode } from "react";
import { useI18n } from "../i18n/LanguageContext";
import { pct } from "../lib/format";
import { productTypeLabel, scheduleLabel, PRODUCT_TYPES, SCHEDULES } from "../i18n/labels";
import type { Product } from "../api/types";

function ageRange(p: Product): string {
  if (p.age_min == null && p.age_max == null) return "—";
  return `${p.age_min ?? 0}–${p.age_max ?? "?"}`;
}

/**
 * Filterable products table shared by the admin (with edit/delete actions) and
 * the agent read-only view. Filtering is client-side over the loaded catalogue
 * and composes as AND. Pass `actions` to render a trailing per-row action cell;
 * omit it for a read-only table.
 */
export default function ProductCatalogue({ products, actions }:
  { products: Product[]; actions?: (p: Product) => ReactNode }) {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const [fType, setFType] = useState("");
  const [fProvider, setFProvider] = useState("");
  const [fTenor, setFTenor] = useState(""); // "" | "none" | "<int>"
  const [fSchedule, setFSchedule] = useState("");
  const [fPI, setFPI] = useState(""); // "" | "yes" | "no"

  const providerOptions = useMemo(() => {
    const set = new Set<string>();
    for (const p of products) if (p.provider) set.add(p.provider);
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [products]);
  const tenorOptions = useMemo(() => {
    const set = new Set<number>();
    let hasNone = false;
    for (const p of products) {
      if (p.payment_tenor == null) hasNone = true;
      else set.add(p.payment_tenor);
    }
    return { nums: Array.from(set).sort((a, b) => a - b), hasNone };
  }, [products]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return products.filter((p) => {
      if (needle && !`${p.code} ${p.name} ${p.provider ?? ""}`.toLowerCase().includes(needle)) return false;
      if (fType && p.type !== fType) return false;
      if (fProvider && p.provider !== fProvider) return false;
      if (fTenor === "none" && p.payment_tenor != null) return false;
      if (fTenor && fTenor !== "none" && String(p.payment_tenor) !== fTenor) return false;
      if (fSchedule && p.commission_schedule !== fSchedule) return false;
      if (fPI === "yes" && !p.professional_investor) return false;
      if (fPI === "no" && p.professional_investor) return false;
      return true;
    });
  }, [products, q, fType, fProvider, fTenor, fSchedule, fPI]);

  const hasFilters = q !== "" || fType !== "" || fProvider !== "" || fTenor !== "" || fSchedule !== "" || fPI !== "";
  const clearFilters = () => { setQ(""); setFType(""); setFProvider(""); setFTenor(""); setFSchedule(""); setFPI(""); };
  const colSpan = actions ? 8 : 7;

  return (
    <>
      <div className="product-filters">
        <input className="filter-search" type="search" value={q} placeholder={t("admin.products.searchPlaceholder")}
          onChange={(e) => setQ(e.target.value)} />
        <select value={fType} onChange={(e) => setFType(e.target.value)}>
          <option value="">{t("admin.products.filterAllTypes")}</option>
          {PRODUCT_TYPES.map((pt) => <option key={pt} value={pt}>{productTypeLabel(pt)}</option>)}
        </select>
        <select value={fProvider} onChange={(e) => setFProvider(e.target.value)}>
          <option value="">{t("admin.products.filterAllProviders")}</option>
          {providerOptions.map((pr) => <option key={pr} value={pr}>{pr}</option>)}
        </select>
        <select value={fTenor} onChange={(e) => setFTenor(e.target.value)}>
          <option value="">{t("admin.products.filterAllTenors")}</option>
          {tenorOptions.nums.map((n) => <option key={n} value={String(n)}>{t("admin.products.tenorOption", { n })}</option>)}
          {tenorOptions.hasNone && <option value="none">{t("admin.products.tenorNone")}</option>}
        </select>
        <select value={fSchedule} onChange={(e) => setFSchedule(e.target.value)}>
          <option value="">{t("admin.products.filterAllSchedules")}</option>
          {SCHEDULES.map((s) => <option key={s} value={s}>{scheduleLabel(s)}</option>)}
        </select>
        <select value={fPI} onChange={(e) => setFPI(e.target.value)}>
          <option value="">{t("admin.products.filterAllPI")}</option>
          <option value="yes">{t("admin.products.filterPIYes")}</option>
          <option value="no">{t("admin.products.filterPINo")}</option>
        </select>
        <span className="muted filter-count">{t("admin.products.showing", { n: filtered.length, total: products.length })}</span>
        {hasFilters && <button type="button" className="ghost" onClick={clearFilters}>{t("admin.products.clearFilters")}</button>}
      </div>
      <table>
        <thead>
          <tr>
            <th>{t("common.code")}</th><th>{t("common.name")}</th><th>{t("common.type")}</th><th className="num">{t("admin.products.thBaseRate")}</th>
            <th className="num">{t("admin.products.thAfypConv")}</th><th>{t("admin.products.thSchedule")}</th><th>{t("admin.products.thInsuranceDetails")}</th>
            {actions && <th></th>}
          </tr>
        </thead>
        <tbody>
          {filtered.length === 0 && (
            <tr><td colSpan={colSpan} className="muted" style={{ textAlign: "center", padding: "18px 0" }}>{t("admin.products.noMatch")}</td></tr>
          )}
          {filtered.map((p) => (
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
              {actions && (
                <td className="num" style={{ whiteSpace: "nowrap" }}>{actions(p)}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
