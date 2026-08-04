"""
Commission engine — the heart of the system.

For a settled transaction it produces:
  - one DIRECT entry for the closing agent (product.base_commission_rate)
  - one OVERRIDE entry per qualifying upline, using OverrideRule keyed on
    product_type + level_gap (1 = direct upline, up to 3 gaps in a 4-level tree)

Rates apply to the transaction notional. All money math uses Decimal and is
quantized to 2 dp at the end. Re-running for a transaction is idempotent:
existing entries for that transaction are cleared first.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.models.models import (
    Agent, Transaction, Product, OverrideRule,
    CommissionEntry, CommissionKind, TxnStatus,
)

CENTS = Decimal("0.01")


def _money(x: Decimal) -> Decimal:
    return x.quantize(CENTS, rounding=ROUND_HALF_UP)


def _upline_chain(session: Session, agent: Agent, max_gap: int = 3):
    """Yield (gap, upline_agent) for gap = 1..max_gap, stopping at the top."""
    current = agent
    gap = 0
    while current.upline_id is not None and gap < max_gap:
        gap += 1
        current = session.get(Agent, current.upline_id)
        if current is None or not current.is_active:
            break
        yield gap, current


def compute_for_transaction(session: Session, txn: Transaction) -> list[CommissionEntry]:
    """Generate and persist commission entries for one transaction."""
    # Idempotency: clear any prior entries for this txn.
    session.execute(
        delete(CommissionEntry).where(CommissionEntry.transaction_id == txn.id)
    )

    if txn.status != TxnStatus.SETTLED:
        session.flush()
        return []

    product = session.get(Product, txn.product_id)
    closer = session.get(Agent, txn.agent_id)
    entries: list[CommissionEntry] = []

    # Direct commission for the closing agent.
    direct_amt = _money(txn.notional * product.base_commission_rate)
    entries.append(CommissionEntry(
        transaction_id=txn.id, agent_id=closer.id,
        kind=CommissionKind.DIRECT, rate=product.base_commission_rate,
        amount=direct_amt, level_gap=0,
    ))

    # Overrides up the chain.
    rules = {
        r.level_gap: r.override_rate
        for r in session.execute(
            select(OverrideRule).where(OverrideRule.product_type == product.type)
        ).scalars()
    }
    for gap, upline in _upline_chain(session, closer):
        rate = rules.get(gap)
        if rate is None or rate == 0:
            continue
        entries.append(CommissionEntry(
            transaction_id=txn.id, agent_id=upline.id,
            kind=CommissionKind.OVERRIDE, rate=rate,
            amount=_money(txn.notional * rate), level_gap=gap,
        ))

    session.add_all(entries)
    session.flush()
    return entries


def recompute_all(session: Session) -> int:
    """Rebuild the commission ledger for every settled transaction. Returns count."""
    txns = session.execute(
        select(Transaction).where(Transaction.status == TxnStatus.SETTLED)
    ).scalars().all()
    total = 0
    for txn in txns:
        total += len(compute_for_transaction(session, txn))
    session.commit()
    return total
