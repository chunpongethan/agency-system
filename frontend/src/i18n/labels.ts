// Enum → localized label helpers. These read the active language via translate()
// so they stay pure (no React) and can be called from anywhere. Components that
// render their output consume useI18n and therefore re-render on toggle.
import { translate } from "./LanguageContext";
import type { Title } from "../api/types";

export function roleLabel(role: string | null | undefined): string {
  return role ? translate(`enum.role.${role}`) : "—";
}

export function statusLabel(status: string | null | undefined): string {
  return status ? translate(`enum.status.${status}`) : "—";
}

export function stageLabel(stage: string | null | undefined): string {
  return stage ? translate(`enum.leadStage.${stage}`) : "—";
}

export function outcomeLabel(outcome: string | null | undefined): string {
  return outcome ? translate(`enum.caseOutcome.${outcome}`) : "—";
}

export function caseTypeLabel(type: string | null | undefined): string {
  if (!type) return "—";
  const key = `enum.caseType.${type}`;
  const label = translate(key);
  return label === key ? type : label; // unknown types fall back to the raw value
}

// Ordered pipeline stages (used for the board columns and stage moves).
export const LEAD_STAGES = ["lead", "prospect", "m1", "m2", "m3"];

// Case categories (multi-select on a case).
export const CASE_TYPES = ["property", "eam", "participating", "medical", "hk_identity", "education"];

export function kindLabel(kind: string | null | undefined): string {
  return kind ? translate(`enum.kind.${kind}`) : "—";
}

export function titleLabel(t: Title | null | undefined): string {
  return t ? translate(`enum.title.${t}`) : "—";
}

export function companyLabel(c: string | null | undefined): string {
  if (!c) return "—";
  const label = translate(`enum.company.${c}`);
  return label === `enum.company.${c}` ? c : label;  // fall back to the raw value
}

export function productTypeLabel(type: string | null | undefined): string {
  return type ? translate(`enum.productType.${type}`) : "—";
}

export function scheduleLabel(s: string | null | undefined): string {
  return s ? translate(`enum.schedule.${s}`) : "—";
}

export function frequencyLabel(f: string | null | undefined): string {
  return f ? translate(`enum.frequency.${f}`) : "—";
}

export function riskLabel(r: string | null | undefined): string {
  if (!r) return "—";
  const key = `enum.risk.${r}`;
  const label = translate(key);
  return label === key ? r : label; // free-text risk profiles fall back to raw
}

// Canonical option lists (stable submit values + localized display labels).
export const RISK_PROFILES = ["Conservative", "Balanced", "Growth", "Aggressive"];
export const SCHEDULES = ["upfront", "trail"];
export const FREQUENCIES = ["monthly", "quarterly", "annual"];
export const PRODUCT_TYPES = ["insurance", "fund", "eam_account", "other"];
export const ROLES = ["admin", "manager", "agent"];
