import type { Title } from "../api/types";

export const TITLES: { value: Title; label: string }[] = [
  { value: "business_manager", label: "Business Manager" },
  { value: "district_manager", label: "District Manager" },
  { value: "district_director", label: "District Director" },
  { value: "principal_partner", label: "Principal Partner" },
];

export function titleLabel(t: Title | null | undefined): string {
  return TITLES.find((x) => x.value === t)?.label ?? "—";
}
