// Typed API client against the FastAPI backend. Attaches the JWT bearer token
// from localStorage and centralises error handling.

import type {
  Me, Agent, Client, Product, Transaction, OverrideRule,
  AgentStatement, AgencySummaryRow, CommissionPreview, PayoutResult, PeriodInfo,
  TeamProductionRow, AgentScorecard, ProductMix, AdminTxnRow, OverrideDefault,
} from "./types";
import { translate } from "../i18n/LanguageContext";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const TOKEN_KEY = "agency_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  code: string | null;
  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

// Localize an API error: prefer the stable X-Error-Code, then a generic
// per-status message, then the raw backend detail. `t` is useI18n().t.
export function errorText(err: unknown, t: (k: string, p?: Record<string, string | number>) => string): string {
  if (err instanceof ApiError) {
    if (err.code) {
      const key = `error.${err.code}`;
      const label = t(key);
      if (label !== key) return label;
    }
    const byStatus = t(`error.status.${err.status}`);
    if (byStatus !== `error.status.${err.status}`) return byStatus;
    return err.message || t("error.generic");
  }
  return err instanceof Error ? err.message : t("error.generic");
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    clearToken();
    if (!path.startsWith("/auth/login")) {
      window.location.hash = "#/login";
    }
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
      if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join(", ");
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, String(detail), res.headers.get("X-Error-Code"));
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("Content-Type") || "";
  if (ct.includes("application/json")) return res.json() as Promise<T>;
  return res.text() as unknown as Promise<T>;
}

export const api = {
  base: BASE,

  // Auth
  login: (username: string, password: string) =>
    request<{ access_token: string; token_type: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  me: () => request<Me>("/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),
  forgotPassword: (email: string) =>
    request<void>("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) }),
  resetPassword: (token: string, new_password: string) =>
    request<void>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password }),
    }),

  // Agents
  agents: () => request<Agent[]>("/agents"),
  downlines: (id: number) => request<Agent[]>(`/agents/${id}/downlines`),
  createAgent: (payload: Partial<Agent> & { password?: string }) =>
    request<Agent>("/agents", { method: "POST", body: JSON.stringify(payload) }),
  updateAgent: (id: number, payload: Partial<Pick<Agent, "name" | "email" | "title" | "unit_code" | "role" | "is_active" | "direct_client">> & { password?: string }) =>
    request<Agent>(`/agents/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),

  // Clients
  clients: () => request<Client[]>("/clients"),
  agentClients: (id: number) => request<Client[]>(`/agents/${id}/clients`),
  client: (id: number) => request<Client>(`/clients/${id}`),
  createClient: (payload: Partial<Client>) =>
    request<Client>("/clients", { method: "POST", body: JSON.stringify(payload) }),
  updateClient: (id: number, payload: Partial<Client>) =>
    request<Client>(`/clients/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  clientTransactions: (id: number) =>
    request<Transaction[]>(`/clients/${id}/transactions`),
  agentTransactions: (id: number) =>
    request<Transaction[]>(`/agents/${id}/transactions`),

  // Products
  products: () => request<Product[]>("/products"),
  createProduct: (payload: Record<string, unknown>) =>
    request<Product>("/products", { method: "POST", body: JSON.stringify(payload) }),
  updateProduct: (id: number, payload: Record<string, unknown>) =>
    request<Product>(`/products/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteProduct: (id: number) =>
    request<{ deleted: number }>(`/products/${id}`, { method: "DELETE" }),

  // Override rules (admin)
  overrideRules: () => request<OverrideRule[]>("/override-rules"),
  createOverrideRule: (payload: Record<string, unknown>) =>
    request<OverrideRule>("/override-rules", { method: "POST", body: JSON.stringify(payload) }),
  updateOverrideRule: (id: number, payload: Record<string, unknown>) =>
    request<OverrideRule>(`/override-rules/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteOverrideRule: (id: number) =>
    request<{ deleted: number }>(`/override-rules/${id}`, { method: "DELETE" }),

  // Transactions
  listTransactions: (params?: { status?: string; agent_id?: number; q?: string }) =>
    request<AdminTxnRow[]>(`/transactions${qs({
      status: params?.status,
      agent_id: params?.agent_id != null ? String(params.agent_id) : undefined,
      q: params?.q,
    })}`),
  nextTransactionRef: (period?: string) =>
    request<{ ref: string }>(`/transactions/next-ref${period ? `?period=${period}` : ""}`),
  createTransaction: (payload: Record<string, unknown>) =>
    request<Transaction>("/transactions", { method: "POST", body: JSON.stringify(payload) }),
  previewTransaction: (payload: Record<string, unknown>) =>
    request<CommissionPreview>("/transactions/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  overrideDefaults: (leadAgentId: number, productId: number) =>
    request<OverrideDefault[]>(`/transactions/override-defaults${qs({
      lead_agent_id: String(leadAgentId), product_id: String(productId),
    })}`),
  approveTransaction: (id: number) =>
    request<Transaction>(`/transactions/${id}/approve`, { method: "POST" }),
  cancelTransaction: (id: number) =>
    request<Transaction>(`/transactions/${id}/cancel`, { method: "POST" }),
  updateTransaction: (id: number, payload: Record<string, unknown>) =>
    request<Transaction>(`/transactions/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteTransaction: (id: number) =>
    request<{ deleted: number }>(`/transactions/${id}`, { method: "DELETE" }),

  // Reports
  agentStatement: (id: number, start?: string, end?: string) =>
    request<AgentStatement>(`/reports/agent/${id}${qs({ start, end })}`),
  agencySummary: (start?: string, end?: string) =>
    request<AgencySummaryRow[]>(`/reports/agency${qs({ start, end })}`),
  productMix: (start?: string, end?: string) =>
    request<ProductMix>(`/reports/product-mix${qs({ start, end })}`),
  teamProduction: () => request<TeamProductionRow[]>("/reports/team-production"),
  agentScorecard: (id: number) =>
    request<AgentScorecard>(`/reports/agent/${id}/scorecard`),
  teamScorecards: () => request<AgentScorecard[]>("/reports/team-scorecards"),
  recompute: () => request<{ entries: number }>("/reports/recompute", { method: "POST" }),

  // Periods
  period: (ym: string) => request<PeriodInfo>(`/periods/${ym}`),
  lockPeriod: (ym: string) =>
    request<{ period: string; is_locked: boolean }>(`/periods/${ym}/lock`, { method: "POST" }),
  unlockPeriod: (ym: string) =>
    request<{ period: string; is_locked: boolean }>(`/periods/${ym}/unlock`, { method: "POST" }),

  // Payouts
  runPayout: (period: string) =>
    request<PayoutResult>(`/payouts/run?period=${period}`, { method: "POST" }),

  // Export URLs (open in a new tab; token is passed as a fragment via fetch-download)
  exportUrl: (path: string) => `${BASE}${path}`,
};

function qs(params: Record<string, string | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

// Download a protected file (CSV/PDF) with the bearer token attached.
export async function downloadFile(path: string, filename: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new ApiError(res.status, translate("error.downloadFailed", { status: res.status }));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
