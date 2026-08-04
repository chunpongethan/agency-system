"""
Payout runs.

`run_payout(year, month)` snapshots every unpaid commission entry that accrued in
the period into an immutable Payout batch, marks those entries paid, and returns
a per-agent payable summary (net of reversals). It is idempotent per period:
re-running with no new unpaid entries returns the same summary and pays nothing
extra. A reversal booked after a payout is simply an unpaid negative entry that
the next run picks up as an adjustment.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    CommissionEntry, Transaction, Payout, Agent,
)


def _entry_period(entry: CommissionEntry, txn: Transaction) -> tuple[int, int]:
    d = entry.accrual_date or txn.trade_date
    return d.year, d.month


def _period_entries(session: Session, year: int, month: int) -> list[tuple[CommissionEntry, Transaction]]:
    rows = session.execute(
        select(CommissionEntry, Transaction)
        .join(Transaction, CommissionEntry.transaction_id == Transaction.id)
    ).all()
    return [(e, t) for (e, t) in rows if _entry_period(e, t) == (year, month)]


def _summarise(entries: list[CommissionEntry]) -> tuple[list[dict], Decimal]:
    per_agent: dict[int, Decimal] = {}
    for e in entries:
        per_agent[e.agent_id] = per_agent.get(e.agent_id, Decimal("0")) + e.amount
    total = sum(per_agent.values(), Decimal("0"))
    payable = [
        {"agent_id": aid, "total": amt}
        for aid, amt in sorted(per_agent.items())
    ]
    return payable, total


def run_payout(session: Session, year: int, month: int) -> dict:
    """Run (or re-run) the payout for a period. Idempotent."""
    all_in_period = _period_entries(session, year, month)
    unpaid = [e for (e, _t) in all_in_period if not e.paid]

    payout = session.execute(
        select(Payout).where(Payout.year == year, Payout.month == month)
    ).scalars().first()

    new_count = len(unpaid)
    if unpaid:
        if payout is None:
            payout = Payout(year=year, month=month, total_amount=Decimal("0"))
            session.add(payout); session.flush()
        for e in unpaid:
            e.paid = True
            e.payout_id = payout.id
        session.flush()

    # Summary covers everything ever paid for this period (stable across reruns).
    paid_entries = [e for (e, _t) in all_in_period if e.payout_id is not None]
    payable, total = _summarise(paid_entries)
    if payout is not None:
        payout.total_amount = total
        session.commit()
    else:
        session.commit()

    return {
        "period": f"{year}-{month:02d}",
        "payout_id": payout.id if payout else None,
        "new_entries_paid": new_count,
        "payable": [{"agent_id": p["agent_id"], "total": float(p["total"])} for p in payable],
        "total": float(total),
    }


def payout_summary(session: Session, year: int, month: int) -> dict:
    """Read-only view of a period's payout without mutating anything."""
    all_in_period = _period_entries(session, year, month)
    paid_entries = [e for (e, _t) in all_in_period if e.payout_id is not None]
    payable, total = _summarise(paid_entries)
    payout = session.execute(
        select(Payout).where(Payout.year == year, Payout.month == month)
    ).scalars().first()
    return {
        "period": f"{year}-{month:02d}",
        "payout_id": payout.id if payout else None,
        "payable": [{"agent_id": p["agent_id"], "total": float(p["total"])} for p in payable],
        "total": float(total),
    }
