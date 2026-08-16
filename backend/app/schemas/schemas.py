from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator


# --- Auth -------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str  # agent code or email
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str

    @model_validator(mode="after")
    def _min_length(self):
        if len(self.new_password) < 8:
            raise ValueError("new password must be at least 8 characters")
        return self


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str

    @model_validator(mode="after")
    def _min_length(self):
        if len(self.new_password) < 8:
            raise ValueError("new password must be at least 8 characters")
        return self


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    email: str
    level: int
    role: str
    title: str | None = None
    unit_code: str | None = None
    upline_id: int | None = None


# --- Agents -----------------------------------------------------------------
class AgentIn(BaseModel):
    code: str
    name: str
    email: EmailStr
    level: int
    upline_id: int | None = None
    role: str = "agent"
    title: str | None = None
    unit_code: str | None = None
    direct_client: bool = False
    password: str | None = None


class AgentUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    title: str | None = None
    unit_code: str | None = None
    role: str | None = None
    is_active: bool | None = None
    direct_client: bool | None = None
    password: str | None = None  # admin manual reset; blank = keep current


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    email: str
    level: int
    upline_id: int | None = None
    role: str
    title: str | None = None
    unit_code: str | None = None
    direct_client: bool = False
    is_active: bool


# --- Clients ----------------------------------------------------------------
class ClientIn(BaseModel):
    ref: str
    name: str
    email: str | None = None
    phone: str | None = None
    risk_profile: str | None = None
    notes: str | None = None
    agent_id: int


class ClientUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    risk_profile: str | None = None
    notes: str | None = None


class ClientOut(ClientIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# --- Cases (sales pipeline) -------------------------------------------------
class CaseIn(BaseModel):
    prospect_name: str
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    client_id: int | None = None
    follow_up: str | None = None
    case_types: list[str] | None = None
    lead_agent_id: int
    sdr_agent_id: int | None = None
    closer_agent_id: int | None = None
    stage: str = "lead"


class CaseUpdate(BaseModel):
    prospect_name: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    client_id: int | None = None
    follow_up: str | None = None
    case_types: list[str] | None = None
    lead_agent_id: int | None = None
    sdr_agent_id: int | None = None
    closer_agent_id: int | None = None
    stage: str | None = None
    outcome: str | None = None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ref: str
    prospect_name: str
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    client_id: int | None = None
    follow_up: str | None = None
    case_types: list[str] | None = None
    lead_agent_id: int
    sdr_agent_id: int | None = None
    closer_agent_id: int | None = None
    stage: str
    outcome: str
    created_at: datetime
    closed_at: datetime | None = None


# --- Products ---------------------------------------------------------------
class ProductIn(BaseModel):
    code: str
    name: str
    type: str
    provider: str | None = None
    base_commission_rate: Decimal
    afyp_conversion: Decimal | None = None
    commission_schedule: str = "upfront"
    trail_frequency: str | None = None
    trail_periods: int | None = None
    # Insurance-only product details.
    payment_tenor: int | None = None
    professional_investor: bool | None = None
    age_min: int | None = None
    age_max: int | None = None
    year_commissions: list[Decimal] | None = None


class ProductUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    base_commission_rate: Decimal | None = None
    afyp_conversion: Decimal | None = None
    commission_schedule: str | None = None
    trail_frequency: str | None = None
    trail_periods: int | None = None
    payment_tenor: int | None = None
    professional_investor: bool | None = None
    age_min: int | None = None
    age_max: int | None = None
    year_commissions: list[Decimal] | None = None
    is_active: bool | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    type: str
    provider: str | None = None
    base_commission_rate: Decimal
    afyp_conversion: Decimal
    commission_schedule: str
    trail_frequency: str | None = None
    trail_periods: int | None = None
    payment_tenor: int | None = None
    professional_investor: bool | None = None
    age_min: int | None = None
    age_max: int | None = None
    year_commissions: list[str] | None = None
    is_active: bool


# --- Override rules ---------------------------------------------------------
class OverrideRuleIn(BaseModel):
    product_type: str
    level_gap: int
    override_rate: Decimal
    valid_from: date | None = None
    valid_to: date | None = None


class OverrideRuleUpdate(BaseModel):
    override_rate: Decimal | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class OverrideRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_type: str
    level_gap: int
    override_rate: Decimal
    valid_from: date
    valid_to: date | None = None


# --- Transactions -----------------------------------------------------------
# A deal is shared by three role-agents (Lead / Sales Development / Closing) that
# split the direct commission by percentage; agent_id is the Closing agent. The
# same agent may hold multiple roles. lead/sales_dev fall back to the closing
# agent when omitted, so single-agent bookings still work.
class DirectOverrideIn(BaseModel):
    agent_id: int
    pct: Decimal


class _RoleSplit(BaseModel):
    lead_agent_id: int | None = None
    sales_dev_agent_id: int | None = None
    lead_pct: Decimal = Decimal("0")
    sales_dev_pct: Decimal = Decimal("0")
    closing_pct: Decimal = Decimal("100")
    # 代理 (default) or 直客 (admin-assigned override levels).
    deal_type: str = "agent"
    direct_overrides: list[DirectOverrideIn] | None = None

    @model_validator(mode="after")
    def _pcts_sum_to_100(self):
        total = (self.lead_pct or 0) + (self.sales_dev_pct or 0) + (self.closing_pct or 0)
        if round(float(total), 2) != 100.0:
            raise ValueError("lead + sales-dev + closing percentages must total 100")
        if self.deal_type == "direct_client" and self.direct_overrides:
            if len(self.direct_overrides) > 4:
                raise ValueError("a direct-client deal has at most 4 override levels")
        return self


class TransactionIn(_RoleSplit):
    ref: str | None = None  # auto-generated (YYYY-MM-NNN) when omitted
    client_id: int
    product_id: int
    agent_id: int          # closing agent
    notional: Decimal
    policy_no: str | None = None
    currency: str = "USD"
    base_currency: str = "USD"
    fx_rate: Decimal | None = None
    trade_date: date | None = None


class TransactionPreviewIn(_RoleSplit):
    product_id: int
    agent_id: int          # closing agent
    notional: Decimal
    trade_date: date | None = None


class TransactionUpdate(BaseModel):
    client_id: int | None = None
    product_id: int | None = None
    agent_id: int | None = None
    lead_agent_id: int | None = None
    sales_dev_agent_id: int | None = None
    lead_pct: Decimal | None = None
    sales_dev_pct: Decimal | None = None
    closing_pct: Decimal | None = None
    deal_type: str | None = None
    direct_overrides: list[DirectOverrideIn] | None = None
    notional: Decimal | None = None
    policy_no: str | None = None
    currency: str | None = None
    trade_date: date | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ref: str
    client_id: int
    product_id: int
    agent_id: int
    lead_agent_id: int | None = None
    sales_dev_agent_id: int | None = None
    lead_pct: Decimal | None = None
    sales_dev_pct: Decimal | None = None
    closing_pct: Decimal | None = None
    deal_type: str = "agent"
    direct_overrides: list | None = None
    notional: Decimal
    policy_no: str | None = None
    currency: str
    status: str
    trade_date: date


class NextRefOut(BaseModel):
    ref: str


class CommissionPreviewLine(BaseModel):
    agent_id: int
    kind: str
    rate: Decimal
    amount: Decimal
    level_gap: int
    period_index: int


class CommissionPreviewOut(BaseModel):
    lines: list[CommissionPreviewLine]
    total: Decimal


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_agent_id: int | None
    action: str
    entity: str
    entity_id: str | None
    before: str | None
    after: str | None
    created_at: datetime
