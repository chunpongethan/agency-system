from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr


# --- Auth -------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str  # agent code or email
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


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
    password: str | None = None


class AgentUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    title: str | None = None
    unit_code: str | None = None
    role: str | None = None
    is_active: bool | None = None


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
class TransactionIn(BaseModel):
    ref: str | None = None  # auto-generated (YYYY-MM-NNN) when omitted
    client_id: int
    product_id: int
    agent_id: int
    notional: Decimal
    currency: str = "USD"
    base_currency: str = "USD"
    fx_rate: Decimal | None = None
    trade_date: date | None = None


class TransactionPreviewIn(BaseModel):
    product_id: int
    agent_id: int
    notional: Decimal
    trade_date: date | None = None


class TransactionUpdate(BaseModel):
    client_id: int | None = None
    product_id: int | None = None
    agent_id: int | None = None
    notional: Decimal | None = None
    currency: str | None = None
    trade_date: date | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ref: str
    client_id: int
    product_id: int
    agent_id: int
    notional: Decimal
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
