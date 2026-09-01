import type { MenuSetting } from "../api/types";

export type Role = "admin" | "manager" | "agent";

export interface MenuItem {
  key: string;
  to: string;
  labelKey: string;          // i18n key
  roles: Role[];             // roles whose route access allows this item
  group: "main" | "admin";
  end?: boolean;             // exact-match route (for "/")
  locked?: boolean;          // cannot be hidden (e.g. the menu-control page itself)
}

// The canonical left-menu registry. Order here is the default order; role lists
// mirror the historical Layout gating exactly. Admins customise show/hide + order
// globally via /admin/menu, persisted as MenuSetting rows keyed by `key`.
export const MENU: MenuItem[] = [
  { key: "dashboard", to: "/", labelKey: "nav.dashboard", roles: ["agent", "manager"], group: "main", end: true },
  { key: "clients", to: "/clients", labelKey: "nav.clients", roles: ["agent", "manager", "admin"], group: "main" },
  { key: "leads", to: "/leads", labelKey: "nav.leads", roles: ["agent", "manager", "admin"], group: "main" },
  { key: "training", to: "/training", labelKey: "nav.training", roles: ["agent", "manager", "admin"], group: "main" },
  { key: "knowledgeBase", to: "/knowledge-base", labelKey: "nav.knowledgeBase", roles: ["agent", "manager", "admin"], group: "main" },
  { key: "products", to: "/products", labelKey: "nav.products", roles: ["agent", "manager"], group: "main" },
  { key: "myTxns", to: "/my-transactions", labelKey: "nav.myTxns", roles: ["agent", "manager"], group: "main" },
  { key: "newTransaction", to: "/transactions/new", labelKey: "nav.newTransaction", roles: ["admin"], group: "main" },
  { key: "hierarchy", to: "/hierarchy", labelKey: "nav.hierarchy", roles: ["manager", "admin"], group: "main" },
  { key: "reports", to: "/reports", labelKey: "nav.reports", roles: ["agent", "manager", "admin"], group: "main" },
  // Admin section
  { key: "adminAgents", to: "/admin/agents", labelKey: "nav.agents", roles: ["admin"], group: "admin" },
  { key: "adminTransactions", to: "/admin/transactions", labelKey: "nav.transactions", roles: ["admin"], group: "admin" },
  { key: "adminProducts", to: "/admin/products", labelKey: "nav.products", roles: ["admin"], group: "admin" },
  { key: "adminRules", to: "/admin/rules", labelKey: "nav.rules", roles: ["admin"], group: "admin" },
  { key: "adminTargets", to: "/admin/targets", labelKey: "nav.targets", roles: ["admin"], group: "admin" },
  { key: "adminTraining", to: "/admin/training", labelKey: "nav.trainingAdmin", roles: ["admin"], group: "admin" },
  { key: "adminKnowledgeBase", to: "/admin/knowledge-base", labelKey: "nav.knowledgeBaseAdmin", roles: ["admin"], group: "admin" },
  { key: "adminLlm", to: "/admin/llm", labelKey: "nav.llmAdmin", roles: ["admin"], group: "admin" },
  { key: "adminPayouts", to: "/admin/payouts", labelKey: "nav.payouts", roles: ["admin"], group: "admin" },
  { key: "adminMenu", to: "/admin/menu", labelKey: "nav.menuAdmin", roles: ["admin"], group: "admin", locked: true },
];

export type ResolvedMenuItem = MenuItem & { labelOverride?: string };

// Merge the registry with saved settings for a given role → the ordered, visible
// items per group, each carrying any admin label override. Falls back to registry
// defaults when a key has no setting.
export function buildMenu(role: Role | undefined, settings: MenuSetting[] | undefined) {
  const byKey = new Map((settings ?? []).map((s) => [s.key, s]));
  const idx = (m: MenuItem) => MENU.indexOf(m);
  const order = (m: MenuItem) => byKey.get(m.key)?.sort_order ?? idx(m);
  const visible: ResolvedMenuItem[] = MENU
    .filter((m) => !!role && m.roles.includes(role))
    .filter((m) => m.locked || (byKey.get(m.key)?.enabled ?? true))
    .sort((a, b) => order(a) - order(b) || idx(a) - idx(b))
    .map((m) => ({ ...m, labelOverride: byKey.get(m.key)?.label || undefined }));
  return {
    main: visible.filter((m) => m.group === "main"),
    admin: visible.filter((m) => m.group === "admin"),
  };
}
