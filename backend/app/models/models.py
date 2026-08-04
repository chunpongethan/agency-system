"""
Core data models for the Agency Management System.

Hierarchy: 4 agent levels (L1 top -> L4 frontline) connected by upline_id.
When an agent closes a sale, commission is paid to that agent and overrides
flow up the chain to their uplines based on level-difference rules.
"""
from __future__ import annotations

import enum
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    String, Integer, ForeignKey, Numeric, DateTime, Date, Enum, Text, Boolean
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AgentLevel(enum.IntEnum):
    """Lower number = higher in the hierarchy."""
    L1 = 1  # e.g. Managing Director / top of an agency line
    L2 = 2  # e.g. Senior Manager
    L3 = 3  # e.g. Manager
    L4 = 4  # e.g. Agent / frontline relationship manager


class ProductType(str, enum.Enum):
    INSURANCE = "insurance"
    FUND = "fund"
    EAM_ACCOUNT = "eam_account"
    OTHER = "other"


class TxnStatus(str, enum.Enum):
    PENDING = "pending"      # submitted, not yet settled
    SETTLED = "settled"      # commissionable
    CANCELLED = "cancelled"  # reverses any accrued commission


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True)
    level: Mapped[AgentLevel] = mapped_column(Enum(AgentLevel))
    upline_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    joined_at: Mapped[date] = mapped_column(Date, default=date.today)

    upline: Mapped["Agent | None"] = relationship(remote_side=[id], backref="downlines")
    clients: Mapped[list["Client"]] = relationship(back_populates="agent")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    risk_profile: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="clients")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="client")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[ProductType] = mapped_column(Enum(ProductType))
    provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Base commission the closing agent earns, as a rate on the notional/premium.
    base_commission_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OverrideRule(Base):
    """
    Defines the override an upline earns on a downline's sale, keyed by the
    number of levels between them (1 = direct upline, 2 = upline's upline...).
    Rate applies to the same base the direct commission is computed on.
    """
    __tablename__ = "override_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_type: Mapped[ProductType] = mapped_column(Enum(ProductType))
    level_gap: Mapped[int] = mapped_column(Integer)  # 1..3
    override_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4))


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))  # closing agent
    notional: Mapped[Decimal] = mapped_column(Numeric(18, 2))       # premium / invested amount
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[TxnStatus] = mapped_column(Enum(TxnStatus), default=TxnStatus.PENDING)
    trade_date: Mapped[date] = mapped_column(Date, default=date.today)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    client: Mapped["Client"] = relationship(back_populates="transactions")
    product: Mapped["Product"] = relationship()
    agent: Mapped["Agent"] = relationship()
    commissions: Mapped[list["CommissionEntry"]] = relationship(back_populates="transaction")


class CommissionKind(str, enum.Enum):
    DIRECT = "direct"      # earned by the closing agent
    OVERRIDE = "override"  # earned by an upline


class CommissionEntry(Base):
    """
    One ledger row per (transaction, beneficiary agent). Generated by the
    commission engine; DIRECT for the closer, OVERRIDE for each qualifying upline.
    """
    __tablename__ = "commission_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    kind: Mapped[CommissionKind] = mapped_column(Enum(CommissionKind))
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    level_gap: Mapped[int] = mapped_column(Integer, default=0)  # 0 for direct
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    transaction: Mapped["Transaction"] = relationship(back_populates="commissions")
    agent: Mapped["Agent"] = relationship()
