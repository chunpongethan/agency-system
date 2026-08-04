"""
Reporting: aggregate the commission ledger into statements.

- agent_statement: everything a single agent earned (direct + overrides), with
  a breakdown by product type, over an optional date window.
- agency_summary: totals per agent for management, filterable by period.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.models import (
    Agent, Transaction, Product, CommissionEntry, CommissionKind,
)


def _window(query, start: date | None, end: date | None):
    if start:
        query = query.where(Transaction.trade_date >= start)
    if end:
        query = query.where(Transaction.trade_date <= end)
    return query


def agent_statement(session: Session, agent_id: int,
                    start: date | None = None, end: date | None = None) -> dict:
    q = (
        select(
            CommissionEntry.kind,
            Product.type,
            func.count(CommissionEntry.id),
            func.coalesce(func.sum(CommissionEntry.amount), 0),
        )
        .join(Transaction, CommissionEntry.transaction_id == Transaction.id)
        .join(Product, Transaction.product_id == Product.id)
        .where(CommissionEntry.agent_id == agent_id)
        .group_by(CommissionEntry.kind, Product.type)
    )
    q = _window(q, start, end)

    lines = []
    direct_total = Decimal("0")
    override_total = Decimal("0")
    for kind, ptype, count, amount in session.execute(q):
        amount = Decimal(amount)
        lines.append({
            "kind": kind.value, "product_type": ptype.value,
            "count": count, "amount": float(amount),
        })
        if kind == CommissionKind.DIRECT:
            direct_total += amount
        else:
            override_total += amount

    agent = session.get(Agent, agent_id)
    return {
        "agent": {"id": agent.id, "code": agent.code, "name": agent.name,
                  "level": int(agent.level)},
        "period": {"start": str(start) if start else None,
                   "end": str(end) if end else None},
        "lines": lines,
        "direct_total": float(direct_total),
        "override_total": float(override_total),
        "grand_total": float(direct_total + override_total),
    }


def agency_summary(session: Session,
                   start: date | None = None, end: date | None = None) -> list[dict]:
    q = (
        select(
            Agent.id, Agent.code, Agent.name, Agent.level,
            func.coalesce(func.sum(CommissionEntry.amount), 0),
        )
        .join(CommissionEntry, CommissionEntry.agent_id == Agent.id)
        .join(Transaction, CommissionEntry.transaction_id == Transaction.id)
        .group_by(Agent.id)
        .order_by(func.sum(CommissionEntry.amount).desc())
    )
    q = _window(q, start, end)
    return [
        {"agent_id": aid, "code": code, "name": name, "level": int(level),
         "total": float(Decimal(total))}
        for aid, code, name, level, total in session.execute(q)
    ]
