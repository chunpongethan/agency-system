import { useI18n } from "../i18n/LanguageContext";
import { statusLabel } from "../i18n/labels";

export default function StatusBadge({ status }: { status: string }) {
  useI18n(); // subscribe so the label re-renders on language toggle
  const cls =
    status === "settled" ? "settled" : status === "cancelled" ? "cancelled" : "pending";
  return <span className={`badge ${cls}`}>{statusLabel(status)}</span>;
}
