import type { Agent, Product } from "../api/types";

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

export const PRODUCT_TYPE_LABELS: Record<string, string> = {
  insurance: "Insurance",
  fund: "Fund",
  eam_account: "EAM Account",
  other: "Other",
};

export function productTypeLabel(type: string | undefined): string {
  if (!type) return "—";
  return PRODUCT_TYPE_LABELS[type] ?? type.charAt(0).toUpperCase() + type.slice(1);
}

// A short, human-readable summary of a product's key details for a table cell.
// Insurance products carry the extra admin-maintained fields.
export function productDetails(p: Product | undefined): string {
  if (!p) return "";
  const parts: string[] = [];
  if (p.provider) parts.push(p.provider);
  if (p.type === "insurance") {
    if (p.payment_tenor != null) parts.push(`${p.payment_tenor}-yr tenor`);
    if (p.age_min != null && p.age_max != null) parts.push(`age ${p.age_min}–${p.age_max}`);
    if (p.professional_investor) parts.push("PI only");
  }
  return parts.join(" · ");
}
