import type { Agent, Product } from "../api/types";
import { translate } from "../i18n/LanguageContext";
import { productTypeLabel as i18nProductTypeLabel } from "../i18n/labels";

// An agent's unit is its own unit code (managers) or, for an individual agent,
// the nearest upline manager's unit code. Mirrors the backend payout logic.
export function resolveUnit(
  agent: Agent | undefined,
  byId: Map<number, Agent>,
): string | null {
  const seen = new Set<number>();
  let a = agent;
  while (a && !seen.has(a.id)) {
    if (a.unit_code) return a.unit_code;
    seen.add(a.id);
    a = a.upline_id != null ? byId.get(a.upline_id) : undefined;
  }
  return null;
}

// Re-export the localized product-type label so existing imports keep working.
export const productTypeLabel = i18nProductTypeLabel;

// A short, human-readable summary of a product's key details for a table cell.
// Insurance products carry the extra admin-maintained fields.
export function productDetails(p: Product | undefined): string {
  if (!p) return "";
  const parts: string[] = [];
  if (p.provider) parts.push(p.provider);
  if (p.type === "insurance") {
    if (p.payment_tenor != null) parts.push(translate("product.tenor", { n: p.payment_tenor }));
    if (p.age_min != null && p.age_max != null)
      parts.push(translate("product.ageRange", { min: p.age_min, max: p.age_max }));
    if (p.professional_investor) parts.push(translate("product.piOnly"));
  }
  return parts.join(" · ");
}
