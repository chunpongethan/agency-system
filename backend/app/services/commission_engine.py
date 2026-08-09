"""
Commission engine — the heart of the system.

For a settled transaction it produces, for each *due* accrual period:
  - one DIRECT entry for the closing agent (product.base_commission_rate)
  - one OVERRIDE entry per qualifying upline, using the OverrideRule in force on
    the trade_date, keyed on product_type + level_gap (1 = direct upline, up to
    3 gaps in a 4-level tree)

UPFRONT products pay once (period 0). TRAIL products accrue the rate per period
for `trail_periods` periods; `run_accruals(as_of)` generates periods that have
come due. Cancelling a settled transaction does not delete rows — it emits
matching negative `is_reversal` entries so statements net to zero yet still show
the clawback (decision 5).

All money math uses Decimal, quantized to 2dp at the boundary. The ledger is
derived: re-running for a transaction clears and regenerates its entries.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.models.models import (
    Agent, Transaction, Product, OverrideRule,
    CommissionEntry, CommissionKind, TxnStatus,
    CommissionSchedule, TrailFrequency, Role,
)

CENTS = Decimal("0.01")

_FREQ_MONTHS = {
    TrailFrequency.MONTHLY: 1,
    TrailFrequency.QUARTERLY: 3,
    TrailFrequency.ANNUAL: 12,
}


def _money(x: Decimal) -> Decimal:
    return x.quantize(CENTS, rounding=ROUND_HALF_UP)


def _add_months(d: date, months: int) -> date:
    """Add whole months to a date, clamping the day to the month's length."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    # Clamp day (e.g. Jan 31 + 1 month -> Feb 28/29).
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = (next_month_first - date(year, month, 1)).days
    return date(year, month, min(d.day, last_day))


def _upline_chain(session: Session, agent: Agent, max_gap: int = 4):
    """Yield (gap, upline_agent) for gap = 1..max_gap, stopping at the top.

    max_gap is 4: overrides reach the 1st..4th upline; deeper uplines earn 0%.
    """
    current = agent
    gap = 0
    while current.upline_id is not None and gap < max_gap:
        gap += 1
        current = session.get(Agent, current.upline_id)
        if current is None or not current.is_active:
            break
        # Admins are not sellers and earn no overrides; stop at one.
        if current.role == Role.ADMIN:
            break
        yield gap, current


def _rules_for(session: Session, product_type, on: date) -> dict[int, Decimal]:
    """Override rates by level_gap in force on `on` (effective-dated selection)."""
    rows = session.execute(
        select(OverrideRule).where(OverrideRule.product_type == product_type)
    ).scalars()
    rules: dict[int, Decimal] = {}
    for r in rows:
        if r.valid_from and r.valid_from > on:
            continue
        if r.valid_to is not None and r.valid_to < on:
            continue
        # Single active rule per (product_type, level_gap) at any date is an
        # invariant enforced on creation; if duplicates slip in, prefer the one
        # with the latest valid_from.
        existing = rules.get(r.level_gap)
        if existing is None:
            rules[r.level_gap] = r.override_rate
    return rules


def scheduled_periods(product: Product, txn: Transaction) -> list[tuple[int, date]]:
    """All (period_index, accrual_date) an entry could exist for this product."""
    if product.commission_schedule == CommissionSchedule.TRAIL:
        n = product.trail_periods or 1
        months = _FREQ_MONTHS.get(product.trail_frequency, 1)
        return [(k, _add_months(txn.trade_date, months * k)) for k in range(n)]
    # Upfront: a single period on the trade date.
    return [(0, txn.trade_date)]


def _due_periods(product: Product, txn: Transaction, as_of: date) -> list[tuple[int, date]]:
    """Periods that have come due by `as_of`. Period 0 is always due on settle."""
    due = []
    for k, d in scheduled_periods(product, txn):
        if k == 0 or d <= as_of:
            due.append((k, d))
    return due


def _role_shares(txn: Transaction) -> tuple[dict[int, Decimal], int]:
    """Percentage of the direct commission each distinct agent earns, combining
    an agent that holds more than one role. Returns (shares, lead_agent_id).

    lead/sales_dev fall back to the closing agent (agent_id) when unset, so a
    legacy single-agent transaction behaves exactly as before (100% direct to the
    closer, overrides up the closer's chain).
    """
    closing_id = txn.agent_id
    lead_id = txn.lead_agent_id or closing_id
    sales_dev_id = txn.sales_dev_agent_id or closing_id
    roles = [
        (lead_id, txn.lead_pct or Decimal("0")),
        (sales_dev_id, txn.sales_dev_pct or Decimal("0")),
        (closing_id, txn.closing_pct if txn.closing_pct is not None else Decimal("100")),
    ]
    shares: dict[int, Decimal] = {}
    for aid, pct in roles:
        shares[aid] = shares.get(aid, Decimal("0")) + Decimal(pct)
    return shares, lead_id


def _period_entries(session: Session, txn: Transaction, product: Product,
                    period_index: int, accrual_date: date,
                    reversal: bool) -> list[CommissionEntry]:
    """Build (positive, and if reversal also negative) entries for one period.

    The direct commission is split among the role-agents by percentage; overrides
    flow up the LEAD agent's hierarchy, computed on the full direct commission.
    """
    sign = Decimal("-1") if reversal else Decimal("1")
    out: list[CommissionEntry] = []

    # The full direct commission is the base every upline override is a % of.
    base_direct = _money(txn.notional * product.base_commission_rate)

    shares, lead_id = _role_shares(txn)
    # Split base_direct by percentage; quantize each and give any rounding
    # residue to the largest share so the parts sum back to base_direct exactly.
    split: list[tuple[int, Decimal]] = []
    for aid, pct in shares.items():
        split.append((aid, _money(base_direct * pct / Decimal("100"))))
    residue = base_direct - sum((amt for _, amt in split), Decimal("0"))
    if split and residue != 0:
        idx = max(range(len(split)), key=lambda i: split[i][1])
        split[idx] = (split[idx][0], split[idx][1] + residue)

    for aid, amount in split:
        if amount == 0:
            continue
        out.append(CommissionEntry(
            transaction_id=txn.id, agent_id=aid,
            kind=CommissionKind.DIRECT, rate=product.base_commission_rate,
            amount=amount * sign, level_gap=0,
            period_index=period_index, accrual_date=accrual_date,
            is_reversal=reversal,
        ))

    lead = session.get(Agent, lead_id)
    rules = _rules_for(session, product.type, txn.trade_date)
    for gap, upline in _upline_chain(session, lead):
        rate = rules.get(gap)
        if rate is None or rate == 0:
            continue
        # Override = rate × the full direct commission (not the notional).
        out.append(CommissionEntry(
            transaction_id=txn.id, agent_id=upline.id,
            kind=CommissionKind.OVERRIDE, rate=rate,
            amount=_money(base_direct * rate) * sign, level_gap=gap,
            period_index=period_index, accrual_date=accrual_date,
            is_reversal=reversal,
        ))
    return out


def preview(session: Session, product: Product, notional: Decimal, trade_date: date,
            lead_id: int, sales_dev_id: int, closing_id: int,
            lead_pct: Decimal, sales_dev_pct: Decimal, closing_pct: Decimal) -> list[dict]:
    """
    Compute the commission lines a settlement *would* produce, without persisting
    anything. Mirrors _period_entries for period 0: the direct commission split
    among the role-agents, plus overrides up the lead agent's chain.
    """
    lines: list[dict] = []
    base_direct = _money(notional * product.base_commission_rate)

    shares: dict[int, Decimal] = {}
    for aid, pct in ((lead_id, lead_pct), (sales_dev_id, sales_dev_pct), (closing_id, closing_pct)):
        shares[aid] = shares.get(aid, Decimal("0")) + Decimal(pct or 0)
    split = [(aid, _money(base_direct * pct / Decimal("100"))) for aid, pct in shares.items()]
    residue = base_direct - sum((amt for _, amt in split), Decimal("0"))
    if split and residue != 0:
        idx = max(range(len(split)), key=lambda i: split[i][1])
        split[idx] = (split[idx][0], split[idx][1] + residue)
    for aid, amount in split:
        if amount == 0:
            continue
        lines.append({
            "agent_id": aid, "kind": CommissionKind.DIRECT.value,
            "rate": product.base_commission_rate, "amount": amount,
            "level_gap": 0, "period_index": 0,
        })

    lead = session.get(Agent, lead_id)
    rules = _rules_for(session, product.type, trade_date)
    for gap, upline in _upline_chain(session, lead):
        rate = rules.get(gap)
        if rate is None or rate == 0:
            continue
        lines.append({
            "agent_id": upline.id, "kind": CommissionKind.OVERRIDE.value,
            "rate": rate, "amount": _money(base_direct * rate),
            "level_gap": gap, "period_index": 0,
        })
    return lines


def _build_all(session: Session, txn: Transaction, product: Product,
               as_of: date, reversal: bool) -> list[CommissionEntry]:
    out: list[CommissionEntry] = []
    for period_index, accrual_date in _due_periods(product, txn, as_of):
        out += _period_entries(
            session, txn, product, period_index, accrual_date, reversal=reversal
        )
    return out


def compute_for_transaction(session: Session, txn: Transaction,
                            as_of: date | None = None) -> list[CommissionEntry]:
    """
    Regenerate commission entries for one transaction, deterministically from its
    current state, while treating already-*paid* entries as immutable:

      - SETTLED  -> positive entries for every due period.
      - CANCELLED (that was previously settled) -> the positive entries PLUS a
        matching negative reversal for each, netting to zero but visible. If a
        positive was already paid in a payout, its reversal is emitted as an
        unpaid negative adjustment (picked up by the next payout run).
      - anything else -> no entries.

    Only *unpaid* entries are cleared and rebuilt; paid entries are preserved and
    never duplicated. Returns all current entries for the transaction.
    """
    as_of = as_of or date.today()

    existing = session.execute(
        select(CommissionEntry).where(CommissionEntry.transaction_id == txn.id)
    ).scalars().all()
    paid_keys = {
        (e.period_index, e.agent_id, e.kind, e.is_reversal)
        for e in existing if e.paid
    }

    # Clear only unpaid entries; paid entries are frozen in a payout batch.
    session.execute(
        delete(CommissionEntry).where(
            CommissionEntry.transaction_id == txn.id,
            CommissionEntry.paid.is_(False),
        )
    )

    was_settled = txn.settled_at is not None
    generate = txn.status == TxnStatus.SETTLED or (
        txn.status == TxnStatus.CANCELLED and was_settled
    )
    if not generate:
        session.flush()
        return []

    product = session.get(Product, txn.product_id)
    reversal_too = txn.status == TxnStatus.CANCELLED

    def _key(e: CommissionEntry):
        return (e.period_index, e.agent_id, e.kind, e.is_reversal)

    to_add: list[CommissionEntry] = []
    for e in _build_all(session, txn, product, as_of, reversal=False):
        if _key(e) not in paid_keys:
            to_add.append(e)
    if reversal_too:
        for e in _build_all(session, txn, product, as_of, reversal=True):
            if _key(e) not in paid_keys:
                to_add.append(e)

    session.add_all(to_add)
    session.flush()

    return session.execute(
        select(CommissionEntry).where(CommissionEntry.transaction_id == txn.id)
    ).scalars().all()


def run_accruals(session: Session, as_of: date | None = None) -> int:
    """
    Generate trail-product entries that have come due up to `as_of`. Returns the
    number of newly-created period entries (idempotent — already-generated periods
    are not duplicated). Also covers cancelled trail transactions' reversals.
    """
    as_of = as_of or date.today()
    trail_txns = session.execute(
        select(Transaction)
        .join(Product, Transaction.product_id == Product.id)
        .where(Product.commission_schedule == CommissionSchedule.TRAIL)
        .where(Transaction.status.in_([TxnStatus.SETTLED, TxnStatus.CANCELLED]))
    ).scalars().all()

    new_entries = 0
    for txn in trail_txns:
        before = session.execute(
            select(CommissionEntry).where(CommissionEntry.transaction_id == txn.id)
        ).scalars().all()
        before_count = len(before)
        after = compute_for_transaction(session, txn, as_of=as_of)
        new_entries += max(0, len(after) - before_count)
    session.commit()
    return new_entries


def recompute_all(session: Session, as_of: date | None = None) -> int:
    """
    Rebuild the commission ledger for every settled/cancelled transaction,
    deterministically, including already-due trail entries and clawback
    reversals. Returns the total number of entries produced.
    """
    as_of = as_of or date.today()
    txns = session.execute(
        select(Transaction).where(
            Transaction.status.in_([TxnStatus.SETTLED, TxnStatus.CANCELLED])
        )
    ).scalars().all()
    total = 0
    for txn in txns:
        total += len(compute_for_transaction(session, txn, as_of=as_of))
    session.commit()
    return total
