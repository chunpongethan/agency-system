import { useI18n } from "../i18n/LanguageContext";
import { stageLabel } from "../i18n/labels";

// Pipeline stage -> an existing .badge.* colour (see index.css).
const STAGE_CLASS: Record<string, string> = {
  lead: "pending",     // amber
  prospect: "unit",    // cyan
  m1: "role",          // accent
  m2: "title",         // purple
  m3: "settled",       // green
};

export default function StageBadge({ stage }: { stage: string }) {
  useI18n(); // subscribe so the label re-renders on language toggle
  return <span className={`badge ${STAGE_CLASS[stage] ?? "role"}`}>{stageLabel(stage)}</span>;
}
