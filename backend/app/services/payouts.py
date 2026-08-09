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
    CommissionEntry, CommissionKind, Transaction, Payout, Agent,
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


def _summarise(session: Session, entries: list[CommissionEntry]) -> tuple[list[dict], Decimal]:
    per_agent: dict[int, Decimal] = {}
    per_direct: dict[int, Decimal] = {}
    per_override: dict[int, Decimal] = {}
    for e in entries:
        per_agent[e.agent_id] = per_agent.get(e.agent_id, Decimal("0")) + e.amount
        bucket = per_direct if e.kind == CommissionKind.DIRECT else per_override
        bucket[e.agent_id] = bucket.get(e.agent_id, Decimal("0")) + e.amount
    total = sum(per_agent.values(), Decimal("0"))

    by_id: dict[int, Agent] = {}
    if per_agent:
        rows = session.execute(select(Agent)).scalars().all()
        by_id = {a.id: a for a in rows}

    def resolve_unit(a: Agent | None) -> str | None:
        # An agent's unit is its own (if a manager with a code) otherwise the
        # nearest upline manager's unit code.
        seen: set[int] = set()
        while a is not None and a.id not in seen:
            if a.unit_code:
                return a.unit_code
            seen.add(a.id)
            a = by_id.get(a.upline_id) if a.upline_id else None
        return None

    payable = []
    for aid, amt in sorted(per_agent.items()):
        a = by_id.get(aid)
        payable.append({
            "agent_id": aid,
            "agent_name": a.name if a else None,
            "agent_code": a.code if a else None,
            "unit_code": resolve_unit(a),
            "direct": per_direct.get(aid, Decimal("0")),
            "override": per_override.get(aid, Decimal("0")),
            "total": amt,
        })
    return payable, total


def _payable_out(payable: list[dict]) -> list[dict]:
    return [
        {
            "agent_id": p["agent_id"],
            "agent_name": p["agent_name"],
            "agent_code": p["agent_code"],
            "unit_code": p["unit_code"],
            "direct": float(p["direct"]),
            "override": float(p["override"]),
            "total": float(p["total"]),
        }
        for p in payable
    ]


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
    payable, total = _summarise(session, paid_entries)
    if payout is not None:
        payout.total_amount = total
        session.commit()
    else:
        session.commit()

    return {
        "period": f"{year}-{month:02d}",
        "payout_id": payout.id if payout else None,
        "new_entries_paid": new_count,
        "payable": _payable_out(payable),
        "total": float(total),
    }


def payout_summary(session: Session, year: int, month: int) -> dict:
    """Read-only view of a period's payout without mutating anything."""
    all_in_period = _period_entries(session, year, month)
    paid_entries = [e for (e, _t) in all_in_period if e.payout_id is not None]
    payable, total = _summarise(session, paid_entries)
    payout = session.execute(
        select(Payout).where(Payout.year == year, Payout.month == month)
    ).scalars().first()
    return {
        "period": f"{year}-{month:02d}",
        "payout_id": payout.id if payout else None,
        "payable": _payable_out(payable),
        "total": float(total),
    }
