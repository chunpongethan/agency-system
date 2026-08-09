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
    Agent, Transaction, Product, CommissionEntry, CommissionKind, TxnStatus, Role,
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
                   start: date | None = None, end: date | None = None,
                   agent_ids: set[int] | None = None) -> list[dict]:
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
    if agent_ids is not None:
        q = q.where(Agent.id.in_(agent_ids))
    q = _window(q, start, end)
    return [
        {"agent_id": aid, "code": code, "name": name, "level": int(level),
         "total": float(Decimal(total))}
        for aid, code, name, level, total in session.execute(q)
    ]


# --------------------------------------------------------------------------- #
# AFYP + commission production (per agent), for team views
# --------------------------------------------------------------------------- #
def _month_last_day(year: int, month: int) -> date:
    first_next = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return date.fromordinal(first_next.toordinal() - 1)


def three_period_windows(today: date | None = None) -> dict[str, tuple[date, date]]:
    """YTD, last month and current-month [start, end] windows relative to today."""
    today = today or date.today()
    lm_year, lm_month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return {
        "ytd": (date(today.year, 1, 1), today),
        "last_month": (date(lm_year, lm_month, 1), _month_last_day(lm_year, lm_month)),
        "current_month": (date(today.year, today.month, 1), today),
    }


def production_by_agent(session: Session, agent_ids: set[int],
                        start: date, end: date) -> dict[int, dict]:
    """Per-agent AFYP (own settled sales) and commission earned, in a window."""
    out = {aid: {"afyp": Decimal("0"), "commission": Decimal("0")} for aid in agent_ids}
    if not agent_ids:
        return out

    # AFYP = notional × product.afyp_conversion, for settled sales the agent closed.
    aq = (
        select(Transaction.agent_id,
               func.coalesce(func.sum(Transaction.notional * Product.afyp_conversion), 0))
        .join(Product, Transaction.product_id == Product.id)
        .where(Transaction.status == TxnStatus.SETTLED)
        .where(Transaction.agent_id.in_(agent_ids))
        .group_by(Transaction.agent_id)
    )
    aq = _window(aq, start, end)
    for aid, afyp in session.execute(aq):
        out[aid]["afyp"] = Decimal(afyp)

    # Commission earned (direct + override) by the agent.
    cq = (
        select(CommissionEntry.agent_id,
               func.coalesce(func.sum(CommissionEntry.amount), 0))
        .join(Transaction, CommissionEntry.transaction_id == Transaction.id)
        .where(CommissionEntry.agent_id.in_(agent_ids))
        .group_by(CommissionEntry.agent_id)
    )
    cq = _window(cq, start, end)
    for aid, comm in session.execute(cq):
        out[aid]["commission"] = Decimal(comm)
    return out


def _production_split(session: Session, agent_id: int,
                      start: date, end: date) -> dict:
    """AFYP plus commission split into direct vs override for one agent/window."""
    aq = _window(
        select(func.coalesce(func.sum(Transaction.notional * Product.afyp_conversion), 0))
        .join(Product, Transaction.product_id == Product.id)
        .where(Transaction.status == TxnStatus.SETTLED)
        .where(Transaction.agent_id == agent_id),
        start, end,
    )
    afyp = Decimal(session.execute(aq).scalar_one())

    cq = _window(
        select(CommissionEntry.kind,
               func.coalesce(func.sum(CommissionEntry.amount), 0))
        .join(Transaction, CommissionEntry.transaction_id == Transaction.id)
        .where(CommissionEntry.agent_id == agent_id)
        .group_by(CommissionEntry.kind),
        start, end,
    )
    direct = Decimal("0")
    override = Decimal("0")
    for kind, amount in session.execute(cq):
        if kind == CommissionKind.DIRECT:
            direct += Decimal(amount)
        else:
            override += Decimal(amount)
    return {"afyp": float(afyp), "direct": float(direct), "override": float(override)}


def _nearest_upline_manager(session: Session, agent: Agent) -> Agent | None:
    seen: set[int] = set()
    cur = session.get(Agent, agent.upline_id) if agent.upline_id else None
    while cur is not None and cur.id not in seen:
        if cur.role == Role.MANAGER:
            return cur
        seen.add(cur.id)
        cur = session.get(Agent, cur.upline_id) if cur.upline_id else None
    return None


def agent_scorecard(session: Session, agent_id: int) -> dict:
    """Header card for an agent: identity, manager, district (unit), and AFYP /
    direct commission / override across YTD, last month and current month."""
    agent = session.get(Agent, agent_id)
    manager = _nearest_upline_manager(session, agent)
    # District = the agent's own unit code (managers) or their manager's unit.
    district = agent.unit_code or (manager.unit_code if manager else None)
    windows = three_period_windows()
    periods = {k: _production_split(session, agent_id, s, e)
               for k, (s, e) in windows.items()}
    return {
        "agent": {"id": agent.id, "code": agent.code, "name": agent.name},
        "manager": {"name": manager.name, "code": manager.code} if manager else None,
        "district": district,
        "periods": periods,
    }


def team_scorecards(session: Session, agent_ids: set[int]) -> list[dict]:
    """A scorecard per agent (identity, manager, district, 3-period AFYP/comm/
    override), ordered by YTD AFYP descending."""
    cards = [agent_scorecard(session, aid) for aid in agent_ids]
    cards.sort(key=lambda c: c["periods"]["ytd"]["afyp"], reverse=True)
    return cards


def team_production(session: Session, agent_ids: set[int]) -> list[dict]:
    """Per-agent AFYP + commission for YTD / last month / current month."""
    windows = three_period_windows()
    periods_data = {k: production_by_agent(session, agent_ids, s, e)
                    for k, (s, e) in windows.items()}
    rows = []
    for aid in agent_ids:
        row = {"agent_id": aid}
        for k in windows:
            row[k] = {"afyp": float(periods_data[k][aid]["afyp"]),
                      "commission": float(periods_data[k][aid]["commission"])}
        rows.append(row)
    return rows
