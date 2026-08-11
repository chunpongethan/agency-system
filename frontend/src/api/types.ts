// Types mirroring the FastAPI Pydantic schemas.

export type Role = "admin" | "manager" | "agent";

export type Title =
  | "business_manager"
  | "district_manager"
  | "district_director"
  | "principal_partner";

export interface Me {
  id: number;
  code: string;
  name: string;
  email: string;
  level: number;
  role: Role;
  title: Title | null;
  unit_code: string | null;
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
  title: Title | null;
  unit_code: string | null;
  direct_client: boolean;
  is_active: boolean;
}

export interface PeriodProduction {
  afyp: number;
  commission: number;
}

export interface TeamProductionRow {
  agent_id: number;
  ytd: PeriodProduction;
  last_month: PeriodProduction;
  current_month: PeriodProduction;
}

export interface ScorecardPeriod {
  afyp: number;
  direct: number;
  override: number;
}

export interface AgentScorecard {
  agent: { id: number; code: string; name: string };
  manager: { name: string; code: string } | null;
  district: string | null;
  periods: {
    ytd: ScorecardPeriod;
    last_month: ScorecardPeriod;
    current_month: ScorecardPeriod;
  };
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
  afyp_conversion: string;
  commission_schedule: string;
  trail_frequency: string | null;
  trail_periods: number | null;
  // Insurance-only product details (admin-maintained).
  payment_tenor: number | null;
  professional_investor: boolean | null;
  age_min: number | null;
  age_max: number | null;
  year_commissions: string[] | null;
  is_active: boolean;
}

export interface Transaction {
  id: number;
  ref: string;
  client_id: number;
  product_id: number;
  agent_id: number;
  lead_agent_id?: number | null;
  sales_dev_agent_id?: number | null;
  lead_pct?: string | null;
  sales_dev_pct?: string | null;
  closing_pct?: string | null;
  deal_type?: string;
  notional: string;
  policy_no?: string | null;
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

export interface StatementRole {
  role: "lead" | "sales_dev" | "closing";
  agent_id: number | null;
  name: string | null;
  code: string | null;
  pct: number;
}

export interface StatementEntry {
  transaction_ref: string;
  trade_date: string;
  client_name: string;
  product_name: string;
  product_type: string;
  provider: string | null;
  payment_tenor: number | null;
  professional_investor: boolean | null;
  age_min: number | null;
  age_max: number | null;
  kind: string;
  notional: number;
  commission_rate: string;
  override_rate: string | null;
  level_gap: number | null;
  amount: number;
  roles: StatementRole[];
}

export interface AgentStatement {
  agent: { id: number; code: string; name: string; level: number };
  period: { start: string | null; end: string | null };
  lines: StatementLine[];
  entries: StatementEntry[];
  direct_total: number;
  override_total: number;
  grand_total: number;
}

export interface AgencySummaryRow {
  agent_id: number;
  code: string;
  name: string;
  level: number;
  afyp: number;
  direct: number;
  override: number;
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
  payable: {
    agent_id: number;
    agent_name: string | null;
    agent_code: string | null;
    unit_code: string | null;
    direct: number;
    override: number;
    total: number;
  }[];
  total: number;
}

export interface ProductMixRow {
  product_id: number;
  code: string;
  name: string;
  type: string;
  count: number;
  notional: number;
  afyp: number;
  commission: number;
}

export interface ProductMix {
  rows: ProductMixRow[];
  totals: { count: number; notional: number; afyp: number; commission: number };
}

export interface PeriodInfo {
  period: string;
  is_locked: boolean;
  locked_at: string | null;
  snapshot: AgencySummaryRow[] | null;
}
