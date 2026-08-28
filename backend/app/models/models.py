"""
Core data models for the Agency Management System.

Hierarchy: 4 agent levels (L1 top -> L4 frontline) connected by upline_id.
When an agent closes a sale, commission is paid to that agent and overrides
flow up the chain to their uplines based on level-difference rules.
"""
from __future__ import annotations

import enum
from datetime import datetime, date, timezone
from decimal import Decimal

from sqlalchemy import (
    String, Integer, ForeignKey, Numeric, DateTime, Date, Enum, Text, Boolean, JSON,
    LargeBinary, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Python 3.11 exposes datetime.UTC; alias timezone.utc for 3.10 compatibility.
UTC = timezone.utc


def now_utc() -> datetime:
    """Timezone-aware 'now' in UTC. Replaces the deprecated datetime.utcnow()."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class AgentLevel(enum.IntEnum):
    """
    Convenience constants for the top few tree depths. `level` is the agent's
    depth in the hierarchy (1 = top/root, increments downward) and is stored as a
    plain integer — a manager may have an *unlimited* depth of downline, so level
    is NOT capped at 4. These constants just make seed/test code readable.
    """
    L1 = 1
    L2 = 2
    L3 = 3
    L4 = 4


class Title(str, enum.Enum):
    """Business rank a downline agent holds, assigned by an admin. Independent of
    tree depth and of the auth `role`."""
    BUSINESS_MANAGER = "business_manager"
    DISTRICT_MANAGER = "district_manager"
    DISTRICT_DIRECTOR = "district_director"
    PRINCIPAL_PARTNER = "principal_partner"


class ProductType(str, enum.Enum):
    INSURANCE = "insurance"
    FUND = "fund"
    EAM_ACCOUNT = "eam_account"
    OTHER = "other"


class CommissionSchedule(str, enum.Enum):
    """How a product's commission is paid out (decision 2)."""
    UPFRONT = "upfront"  # single payment at settlement (period 0 only)
    TRAIL = "trail"      # accrues periodically over trail_periods


class TrailFrequency(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class Role(str, enum.Enum):
    """Principal role for auth/scoping (Phase 2)."""
    ADMIN = "admin"
    MANAGER = "manager"
    AGENT = "agent"


class TxnStatus(str, enum.Enum):
    PENDING = "pending"      # submitted, awaiting admin approval
    APPROVED = "approved"    # admin-approved -> commissionable
    CANCELLED = "cancelled"  # reverses any accrued commission


class DealType(str, enum.Enum):
    """How a transaction's overrides are determined."""
    AGENT = "agent"                  # 代理: overrides flow up the lead agent's hierarchy
    DIRECT_CLIENT = "direct_client"  # 直客: admin assigns up to 4 override levels manually


class PipelineStage(str, enum.Enum):
    """Sales-funnel stage of a lead/case (pre-transaction CRM)."""
    LEAD = "lead"          # raw lead / name
    PROSPECT = "prospect"  # benefits / concepts delivered
    M1 = "m1"              # fact finding
    M2 = "m2"             # proposal presentation
    M3 = "m3"            # closing


class CaseOutcome(str, enum.Enum):
    """Whether a case is still open or has been closed won/lost."""
    OPEN = "open"
    WON = "won"
    LOST = "lost"


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    # Tenant company, derived from the code prefix ("cpm..." -> cpm, else heritree).
    # Plain string (not an Enum) to avoid native-Postgres-enum coupling.
    company: Mapped[str] = mapped_column(String(20), default="heritree", index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True)
    # Depth in the tree (1 = top). Plain integer: hierarchy depth is unbounded.
    level: Mapped[int] = mapped_column(Integer)
    # Business rank/position, assigned by an admin (nullable for legacy rows).
    title: Mapped[Title | None] = mapped_column(Enum(Title), nullable=True)
    # Unit/team code — a manager heads a unit identified by this code.
    unit_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    upline_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # "直客" eligible: may receive manually-assigned overrides on direct-client deals.
    direct_client: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[date] = mapped_column(Date, default=date.today)

    # --- Auth (Phase 2). password_hash lives on the agent; role drives scoping. ---
    # DECISION: keep auth on Agent rather than a separate User table — one login
    # per agent keeps the principal <-> hierarchy mapping trivial for scoping.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.AGENT)
    # Stamp of the agent's most recent successful login (null until they sign in).
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

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
    # AFYP (Annualised First-Year Premium) conversion: AFYP = notional × this rate.
    afyp_conversion: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- Trail schedule (decision 2) ---
    # DECISION: for TRAIL products the rate is applied to the notional *per period*
    # for `trail_periods` periods. UPFRONT products pay once (period 0) exactly as
    # before. This keeps the accrual model simple and deterministic.
    commission_schedule: Mapped[CommissionSchedule] = mapped_column(
        Enum(CommissionSchedule), default=CommissionSchedule.UPFRONT
    )
    trail_frequency: Mapped[TrailFrequency | None] = mapped_column(
        Enum(TrailFrequency), nullable=True
    )
    trail_periods: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Insurance product details (admin-maintained; only meaningful for insurance
    # products). age_min/age_max are the eligible age range (e.g. 0-70);
    # year_commissions is the Yr1..Yr10 commission schedule as decimal strings.
    payment_tenor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    professional_investor: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    age_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_commissions: Mapped[list | None] = mapped_column(JSON, nullable=True)


class ProductRate(Base):
    """Per-company commission rate for a SHARED product: each company sets its own
    基本比率 (base_commission_rate) — and, for insurance, its own Yr1..Yr10 schedule
    whose Yr1 is that base. The rest of the product (name, type, AFYP conv, age
    range, …) stays shared. Falls back to the Product's own values if absent."""
    __tablename__ = "product_rates"
    __table_args__ = (UniqueConstraint("product_id", "company", name="uq_product_rate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    company: Mapped[str] = mapped_column(String(20), index=True)
    base_commission_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    year_commissions: Mapped[list | None] = mapped_column(JSON, nullable=True)


class OverrideRule(Base):
    """
    Defines the override an upline earns on a downline's sale, keyed by the
    number of levels between them (1 = direct upline, 2 = upline's upline...).

    Rate applies to the *closing agent's direct commission* (not the notional):
    an upline at gap g earns `override_rate` × the closer's commission. Overrides
    reach up to gap 4; gap 5+ earn nothing.

    Effective-dated: the engine picks the rule in force on the transaction's
    trade_date. Keep a single active rule per (product_type, level_gap) at any
    date (validated on creation).
    """
    __tablename__ = "override_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(20), default="heritree", index=True)
    product_type: Mapped[ProductType] = mapped_column(Enum(ProductType))
    level_gap: Mapped[int] = mapped_column(Integer)  # 1..4
    override_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    valid_from: Mapped[date] = mapped_column(Date, default=date(1900, 1, 1))
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))  # closing agent
    # A deal is handled by up to three role-agents that share the direct
    # commission by percentage: Lead, Sales Development, and Closing (= agent_id).
    # The same agent may hold more than one role. Overrides flow up the LEAD
    # agent's hierarchy. lead/sales_dev fall back to the closing agent when unset.
    lead_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    sales_dev_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    lead_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    sales_dev_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    closing_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("100"))
    # 代理 (default): overrides follow the lead agent's hierarchy. 直客: the admin
    # assigns up to 4 override levels, stored as [{"agent_id": int, "pct": number}].
    deal_type: Mapped[DealType] = mapped_column(
        Enum(DealType, values_callable=lambda e: [m.value for m in e]),
        default=DealType.AGENT,
    )
    direct_overrides: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notional: Mapped[Decimal] = mapped_column(Numeric(18, 2))       # premium / invested amount
    policy_no: Mapped[str | None] = mapped_column(String(60), nullable=True)  # insurance policy number
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    # Multi-currency (decision 3): store base_currency + a nullable fx_rate for a
    # later conversion pass. v1 computes/reports in the transaction currency only.
    base_currency: Mapped[str] = mapped_column(String(3), default="USD")
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    status: Mapped[TxnStatus] = mapped_column(Enum(TxnStatus), default=TxnStatus.PENDING)
    trade_date: Mapped[date] = mapped_column(Date, default=date.today)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Rate lock: the effective commission rate is snapshotted here at creation so a
    # later product-rate edit does not move an already-booked deal. locked_base_rate
    # is the flat rate; locked_year_commissions is the Yr1..YrN schedule for a
    # per-year trail (insurance). An admin may override these at approval. Both NULL
    # on legacy rows -> the engine falls back to the live ProductRate.
    locked_base_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    locked_year_commissions: Mapped[list | None] = mapped_column(JSON, nullable=True)

    client: Mapped["Client"] = relationship(back_populates="transactions")
    product: Mapped["Product"] = relationship()
    agent: Mapped["Agent"] = relationship(foreign_keys=[agent_id])
    commissions: Mapped[list["CommissionEntry"]] = relationship(back_populates="transaction")


class CommissionKind(str, enum.Enum):
    DIRECT = "direct"      # earned by the closing agent
    OVERRIDE = "override"  # earned by an upline


class CommissionEntry(Base):
    """
    One ledger row per (transaction, beneficiary agent, period). Generated by the
    commission engine; DIRECT for the closer, OVERRIDE for each qualifying upline.

    The ledger is derived — never hand-edit it; always regenerate. Cancellation
    (decision 5) does not delete rows: it emits matching negative `is_reversal`
    rows so a statement nets to zero while still showing the adjustment.
    """
    __tablename__ = "commission_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    kind: Mapped[CommissionKind] = mapped_column(Enum(CommissionKind))
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    level_gap: Mapped[int] = mapped_column(Integer, default=0)  # 0 for direct
    # Trail accrual bookkeeping: which period this row is for and the date it
    # accrues on. period 0 == upfront / first trail period, on the trade_date.
    period_index: Mapped[int] = mapped_column(Integer, default=0)
    accrual_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Reversal tag for clawbacks (decision 5).
    is_reversal: Mapped[bool] = mapped_column(Boolean, default=False)
    # Payout bookkeeping (Phase 3): set when snapshotted into a Payout batch.
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    payout_id: Mapped[int | None] = mapped_column(ForeignKey("payouts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    transaction: Mapped["Transaction"] = relationship(back_populates="commissions")
    agent: Mapped["Agent"] = relationship()


class Period(Base):
    """A calendar month that can be locked to freeze its statements (Phase 3)."""
    __tablename__ = "periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(20), default="heritree", index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Frozen agency-summary JSON captured at lock time (read on locked periods).
    snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)


class Payout(Base):
    """An immutable batch of paid commission entries for a period (Phase 3)."""
    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(20), default="heritree", index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))


class AuditEntry(Base):
    """Audit trail for commission-affecting changes (Phase 5)."""
    __tablename__ = "audit_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    before: Mapped[str | None] = mapped_column(Text, nullable=True)
    after: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Case(Base):
    """A sales opportunity moving through the pre-sale funnel (Lead -> Prospect ->
    M1 -> M2 -> M3). Worked by three assigned agents (Lead / SDR / Closer). Kept
    separate from Transaction: closing a case just marks it won/lost."""
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(24), unique=True, index=True)

    # Prospect details (a lead is not yet a Client). Optional link to a Client.
    prospect_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    follow_up: Mapped[str | None] = mapped_column(Text, nullable=True)  # 跟進事項 (next action)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)       # 備註 (remarks)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    # Case categories (multi-select): 房產方案 / EAM / 分紅險 / 醫療重疾 / 香港身份 / 教育升學.
    case_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expected_afyp: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)  # 預計AFYP

    # Three-agent assignment (assignment only — commission split lives on the
    # eventual Transaction). lead is the owner/sourcer; sdr/closer are optional.
    lead_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    sdr_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    closer_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)

    stage: Mapped[PipelineStage] = mapped_column(
        Enum(PipelineStage, values_callable=lambda e: [m.value for m in e]),
        default=PipelineStage.LEAD,
    )
    outcome: Mapped[CaseOutcome] = mapped_column(
        Enum(CaseOutcome, values_callable=lambda e: [m.value for m in e]),
        default=CaseOutcome.OPEN,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TitleTarget(Base):
    """Annual AFYP target for a business rank (職級), set by an admin. Agents see
    their own title's target progress on the dashboard."""
    __tablename__ = "title_targets"
    # One target per (company, 職級).
    __table_args__ = (UniqueConstraint("company", "title", name="uq_title_target_company_title"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(20), default="heritree", index=True)
    # Must match Agent.title's Enum config (plain Enum(Title), stores the member
    # NAME) — both share one native `title` enum type on Postgres, so a
    # values_callable mismatch here makes inserts fail in prod ("Failed to fetch").
    title: Mapped[Title] = mapped_column(Enum(Title))
    target_afyp: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))


class TrainingMaterial(Base):
    """A training resource curated by an admin and browsable by every agent.
    Each item may carry an external link (hosted PDF, video, slides) and/or an
    uploaded file (bytes live in the sibling `training_files` table). Grouped in
    the portal by the free-text `category`."""
    __tablename__ = "training_materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Uploaded-file metadata (bytes stored in TrainingFile). Null when none.
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Which companies see this material in the agent portal, e.g. ["heritree",
    # "cpm"]. NULL/empty is treated as "all companies" (legacy rows).
    companies: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class TrainingFile(Base):
    """Blob storage for a training material's uploaded files, kept in its own
    table so listing materials never loads file bytes. A material may have many
    files; each row carries its own name/type/size next to the bytes."""
    __tablename__ = "training_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("training_materials.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255), default="file")
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    # Optional rendered preview (e.g. a PDF generated from an uploaded PPTX/DOCX)
    # so non-natively-viewable Office docs can still preview on screen.
    preview_content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    preview_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class TrainingCategory(Base):
    """The maintained list of training types (培訓類別) admins curate; a material's
    free-text `category` is picked from these. Kept separate from materials so a
    type can exist with no materials, and deleting a type never orphans data."""
    __tablename__ = "training_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
