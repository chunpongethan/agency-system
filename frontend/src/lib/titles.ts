import type { Title } from "../api/types";
import { titleLabel as i18nTitleLabel } from "../i18n/labels";

// Canonical title values (stable submit values); display labels come from i18n.
export const TITLE_VALUES: Title[] = [
  "business_manager",
  "district_manager",
  "district_director",
  "principal_partner",
];

// Re-export the localized label helper so existing imports keep working.
export const titleLabel = i18nTitleLabel;
