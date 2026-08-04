from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr


class AgentIn(BaseModel):
    code: str
    name: str
    email: EmailStr
    level: int
    upline_id: int | None = None


class AgentOut(AgentIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool


class ClientIn(BaseModel):
    ref: str
    name: str
    email: str | None = None
    phone: str | None = None
    risk_profile: str | None = None
    notes: str | None = None
    agent_id: int


class ClientOut(ClientIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class ProductIn(BaseModel):
    code: str
    name: str
    type: str
    provider: str | None = None
    base_commission_rate: Decimal


class ProductOut(ProductIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool


class TransactionIn(BaseModel):
    ref: str
    client_id: int
    product_id: int
    agent_id: int
    notional: Decimal
    currency: str = "USD"
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
