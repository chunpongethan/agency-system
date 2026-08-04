// Types mirroring the FastAPI Pydantic schemas.

export type Role = "admin" | "manager" | "agent";

export interface Me {
  id: number;
  code: string;
  name: string;
  email: string;
  level: number;
  role: Role;
  upline_id: number | null;
}

export interface Agent {
  id: number;
  code: string;
  name: string;
  email: string;
  level: number;
  upline_id: number | null;
  role: Role;
  is_active: boolean;
}

export interface Client {
  id: number;
  ref: string;
  name: string;
  email: string | null;
  phone: string | null;
  risk_profile: string | null;
  notes: string | null;
  agent_id: number;
  created_at: string;
}

export interface Product {
  id: number;
  code: string;
  name: string;
  type: string;
  provider: string | null;
  base_commission_rate: string;
  commission_schedule: string;
  trail_frequency: string | null;
  trail_periods: number | null;
  is_active: boolean;
}

export interface Transaction {
  id: number;
  ref: string;
  client_id: number;
  product_id: number;
  agent_id: number;
  notional: string;
  currency: string;
  status: string;
  trade_date: string;
}

export interface OverrideRule {
  id: number;
  product_type: string;
  level_gap: number;
  override_rate: string;
  valid_from: string;
  valid_to: string | null;
}

export interface StatementLine {
  kind: string;
  product_type: string;
  count: number;
  amount: number;
}

export interface AgentStatement {
  agent: { id: number; code: string; name: string; level: number };
  period: { start: string | null; end: string | null };
  lines: StatementLine[];
  direct_total: number;
  override_total: number;
  grand_total: number;
}

export interface AgencySummaryRow {
  agent_id: number;
  code: string;
  name: string;
  level: number;
  total: number;
}

export interface PreviewLine {
  agent_id: number;
  kind: string;
  rate: string;
  amount: string;
  level_gap: number;
  period_index: number;
}

export interface CommissionPreview {
  lines: PreviewLine[];
  total: string;
}

export interface PayoutResult {
  period: string;
  payout_id: number | null;
  new_entries_paid: number;
  payable: { agent_id: number; total: number }[];
  total: number;
}

export interface PeriodInfo {
  period: string;
  is_locked: boolean;
  locked_at: string | null;
  snapshot: AgencySummaryRow[] | null;
}
