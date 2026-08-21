"""
Reporting: aggregate the commission ledger into statements.

- agent_statement: everything a single agent earned (direct + overrides), with
  a breakdown by product type, over an optional date window.
- agency_summary: totals per agent for management, filterable by period.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from app.models.models import (
    Agent, Client, Transaction, Product, CommissionEntry, CommissionKind, TxnStatus, Role,
)


def _window(query, start: date | None, end: date | None):
    if start:
        query = query.where(Transaction.trade_date >= start)
    if end:
        query = query.where(Transaction.trade_date <= end)
    return query


def _role_shares_for_txn(txn) -> dict[int, Decimal]:
    """{agent_id: percentage} of a deal each role agent holds — Lead / SDR /
    Closing, with lead & sales-dev falling back to the closer when unset, and
    combining an agent that holds more than one role. Mirrors the commission
    engine's split so AFYP is credited the same way the commission is."""
    closing = txn.agent_id
    lead = txn.lead_agent_id or closing
    sdr = txn.sales_dev_agent_id or closing
    shares: dict[int, Decimal] = {}
    for aid, pct in ((lead, txn.lead_pct), (sdr, txn.sales_dev_pct), (closing, txn.closing_pct)):
        shares[aid] = shares.get(aid, Decimal("0")) + Decimal(pct or 0)
    return shares


def _afyp_by_agent(session: Session, start: date | None, end: date | None,
                   agent_ids: set[int] | None = None) -> dict[int, Decimal]:
    """Per-agent AFYP for settled sales, split across the deal's Lead/SDR/Closing
    role agents by their share % — so a lead/sales-dev is credited AFYP too, not
    only the closer. Restricted to `agent_ids` when given (a deal counts if any of
    its role agents is in the set, but only those agents' shares accumulate)."""
    q = (select(Transaction, Product.afyp_conversion)
         .join(Product, Transaction.product_id == Product.id)
         .where(Transaction.status == TxnStatus.APPROVED))
    if agent_ids is not None:
        q = q.where(or_(Transaction.agent_id.in_(agent_ids),
                        Transaction.lead_agent_id.in_(agent_ids),
                        Transaction.sales_dev_agent_id.in_(agent_ids)))
    q = _window(q, start, end)
    out: dict[int, Decimal] = {}
    for txn, conv in session.execute(q):
        afyp = Decimal(txn.notional) * Decimal(conv)
        for aid, pct in _role_shares_for_txn(txn).items():
            if agent_ids is not None and aid not in agent_ids:
                continue
            out[aid] = out.get(aid, Decimal("0")) + afyp * pct / Decimal("100")
    return out


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

    # Transaction-level breakdown: one row per (transaction, kind), summing any
    # trail-period entries for the same transaction. Carries the client, product
    # details, trade date, and both the base commission rate and (for override
    # rows) the override rate.
    eq = (
        select(
            Transaction.ref,
            Transaction.trade_date,
            Transaction.notional,
            Client.name,
            Product.name,
            Product.type,
            Product.provider,
            Product.base_commission_rate,
            Product.payment_tenor,
            Product.professional_investor,
            Product.age_min,
            Product.age_max,
            Transaction.agent_id,
            Transaction.lead_agent_id,
            Transaction.sales_dev_agent_id,
            Transaction.lead_pct,
            Transaction.sales_dev_pct,
            Transaction.closing_pct,
            CommissionEntry.kind,
            func.max(CommissionEntry.rate),
            func.max(CommissionEntry.level_gap),
            func.coalesce(func.sum(CommissionEntry.amount), 0),
        )
        .join(Transaction, CommissionEntry.transaction_id == Transaction.id)
        .join(Product, Transaction.product_id == Product.id)
        .join(Client, Transaction.client_id == Client.id)
        .where(CommissionEntry.agent_id == agent_id)
        .group_by(
            Transaction.id, CommissionEntry.kind, Transaction.ref, Transaction.trade_date,
            Transaction.notional, Client.name, Product.name, Product.type, Product.provider,
            Product.base_commission_rate, Product.payment_tenor,
            Product.professional_investor, Product.age_min, Product.age_max,
            Transaction.agent_id, Transaction.lead_agent_id, Transaction.sales_dev_agent_id,
            Transaction.lead_pct, Transaction.sales_dev_pct, Transaction.closing_pct,
        )
        .order_by(CommissionEntry.kind, Transaction.ref)
    )
    eq = _window(eq, start, end)

    # Resolve agent names/codes once for the role breakdown.
    all_agents = {a.id: a for a in session.execute(select(Agent)).scalars()}

    def _role(role: str, aid: int | None, pct) -> dict:
        a = all_agents.get(aid)
        return {"role": role, "agent_id": aid,
                "name": a.name if a else None, "code": a.code if a else None,
                "pct": float(pct or 0)}

    entries = []
    for (ref, tdate, notional, client_name, pname, ptype, provider, base_rate,
         tenor, pro_inv, age_min, age_max, closing_id, lead_id, sales_dev_id,
         lead_pct, sales_dev_pct, closing_pct,
         kind, entry_rate, level_gap, amount) in session.execute(eq):
        is_override = kind == CommissionKind.OVERRIDE
        # lead / sales-dev fall back to the closing agent when unset.
        roles = [
            _role("lead", lead_id or closing_id, lead_pct),
            _role("sales_dev", sales_dev_id or closing_id, sales_dev_pct),
            _role("closing", closing_id, closing_pct if closing_pct is not None else 100),
        ]
        entries.append({
            "transaction_ref": ref,
            "trade_date": str(tdate),
            "client_name": client_name,
            "product_name": pname,
            "product_type": ptype.value,
            "provider": provider,
            "payment_tenor": tenor,
            "professional_investor": pro_inv,
            "age_min": age_min,
            "age_max": age_max,
            "kind": kind.value,
            "notional": float(Decimal(notional)),
            "commission_rate": str(base_rate),
            "override_rate": str(entry_rate) if is_override else None,
            "level_gap": int(level_gap) if is_override else None,
            "amount": float(Decimal(amount)),
            "roles": roles,
        })

    agent = session.get(Agent, agent_id)
    return {
        "agent": {"id": agent.id, "code": agent.code, "name": agent.name,
                  "level": int(agent.level)},
        "period": {"start": str(start) if start else None,
                   "end": str(end) if end else None},
        "lines": lines,
        "entries": entries,
        "direct_total": float(direct_total),
        "override_total": float(override_total),
        "grand_total": float(direct_total + override_total),
    }


def agency_summary(session: Session,
                   start: date | None = None, end: date | None = None,
                   agent_ids: set[int] | None = None,
                   roster: list[Agent] | None = None,
                   targets: dict[str, float] | None = None) -> list[dict]:
    """Totals per agent over an optional window.

    When ``roster`` is given, the result lists exactly those agents (each seeded
    with a zero row so agents with no production still appear) and carries each
    agent's ``title`` plus its annual ``target_afyp`` for a target-progress
    column — mirroring the on-screen team tables. Without a roster the behaviour
    is unchanged (only agents with production, used by period snapshots)."""
    # Commission per agent, split by kind (direct / override).
    cq = (
        select(
            Agent.id, Agent.code, Agent.name, Agent.level,
            CommissionEntry.kind,
            func.coalesce(func.sum(CommissionEntry.amount), 0),
        )
        .join(CommissionEntry, CommissionEntry.agent_id == Agent.id)
        .join(Transaction, CommissionEntry.transaction_id == Transaction.id)
        .group_by(Agent.id, CommissionEntry.kind)
    )
    if agent_ids is not None:
        cq = cq.where(Agent.id.in_(agent_ids))
    cq = _window(cq, start, end)

    rows: dict[int, dict] = {}
    # With a roster, seed a zero row per agent (so those with no production still
    # show) and restrict output to the roster, dropping anyone outside it.
    roster_ids: set[int] | None = None
    if roster is not None:
        roster_ids = {a.id for a in roster}
        for a in roster:
            rows[a.id] = {
                "agent_id": a.id, "code": a.code, "name": a.name, "level": int(a.level),
                "title": a.title.value if a.title else None,
                "direct": Decimal("0"), "override": Decimal("0"), "afyp": Decimal("0"),
            }
    for aid, code, name, level, kind, amount in session.execute(cq):
        if roster_ids is not None:
            if aid not in roster_ids:
                continue
            r = rows[aid]
        else:
            r = rows.setdefault(aid, {
                "agent_id": aid, "code": code, "name": name, "level": int(level),
                "direct": Decimal("0"), "override": Decimal("0"), "afyp": Decimal("0"),
            })
        if kind == CommissionKind.DIRECT:
            r["direct"] += Decimal(amount)
        else:
            r["override"] += Decimal(amount)

    # AFYP per agent, split across each deal's Lead/SDR/Closing role agents.
    for aid, afyp in _afyp_by_agent(session, start, end, agent_ids).items():
        if aid in rows:
            rows[aid]["afyp"] = afyp

    out = []
    for r in rows.values():
        total = r["direct"] + r["override"]
        row = {
            "agent_id": r["agent_id"], "code": r["code"], "name": r["name"], "level": r["level"],
            "afyp": float(r["afyp"]), "direct": float(r["direct"]),
            "override": float(r["override"]), "total": float(total),
        }
        if roster is not None:
            title = r.get("title")
            row["title"] = title
            row["target_afyp"] = (targets or {}).get(title) if title else None
        out.append(row)
    out.sort(key=lambda x: x["total"], reverse=True)
    return out


def product_mix(session: Session,
                start: date | None = None, end: date | None = None,
                agent_ids: set[int] | None = None) -> dict:
    """Settled production broken down by product: transaction count, notional,
    AFYP, and commission earned in scope. Sorted by AFYP descending."""
    # Notional / AFYP / count come from the settled transactions themselves.
    tq = (
        select(
            Product.id, Product.code, Product.name, Product.type,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.notional), 0),
            func.coalesce(func.sum(Transaction.notional * Product.afyp_conversion), 0),
        )
        .join(Transaction, Transaction.product_id == Product.id)
        .where(Transaction.status == TxnStatus.APPROVED)
        .group_by(Product.id)
    )
    if agent_ids is not None:
        tq = tq.where(Transaction.agent_id.in_(agent_ids))
    tq = _window(tq, start, end)

    # Commission earned in scope, attributed to each product via its transaction.
    cq = (
        select(Product.id, func.coalesce(func.sum(CommissionEntry.amount), 0))
        .join(Transaction, Transaction.product_id == Product.id)
        .join(CommissionEntry, CommissionEntry.transaction_id == Transaction.id)
        .group_by(Product.id)
    )
    if agent_ids is not None:
        cq = cq.where(CommissionEntry.agent_id.in_(agent_ids))
    cq = _window(cq, start, end)
    comm_by_product = {pid: Decimal(amt) for pid, amt in session.execute(cq)}

    rows = []
    for pid, code, name, ptype, count, notional, afyp in session.execute(tq):
        rows.append({
            "product_id": pid, "code": code, "name": name, "type": ptype.value,
            "count": count,
            "notional": float(Decimal(notional)),
            "afyp": float(Decimal(afyp)),
            "commission": float(comm_by_product.get(pid, Decimal("0"))),
        })
    rows.sort(key=lambda r: r["afyp"], reverse=True)
    totals = {
        "count": sum(r["count"] for r in rows),
        "notional": sum(r["notional"] for r in rows),
        "afyp": sum(r["afyp"] for r in rows),
        "commission": sum(r["commission"] for r in rows),
    }
    return {"rows": rows, "totals": totals}


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
    """Per-agent AFYP (own settled sales) and commission earned, in a window.

    Commission is returned both as a total and split into direct / override.
    """
    out = {aid: {"afyp": Decimal("0"), "commission": Decimal("0"),
                 "direct": Decimal("0"), "override": Decimal("0")}
           for aid in agent_ids}
    if not agent_ids:
        return out

    # AFYP = notional × afyp_conversion, split across each deal's role agents
    # (Lead/SDR/Closing) so a lead/sales-dev is credited too, not only the closer.
    for aid, afyp in _afyp_by_agent(session, start, end, agent_ids).items():
        if aid in out:
            out[aid]["afyp"] = afyp

    # Commission earned by the agent, split into direct vs override.
    cq = (
        select(CommissionEntry.agent_id, CommissionEntry.kind,
               func.coalesce(func.sum(CommissionEntry.amount), 0))
        .join(Transaction, CommissionEntry.transaction_id == Transaction.id)
        .where(CommissionEntry.agent_id.in_(agent_ids))
        .group_by(CommissionEntry.agent_id, CommissionEntry.kind)
    )
    cq = _window(cq, start, end)
    for aid, kind, amount in session.execute(cq):
        amt = Decimal(amount)
        if kind == CommissionKind.DIRECT:
            out[aid]["direct"] += amt
        else:
            out[aid]["override"] += amt
        out[aid]["commission"] += amt
    return out


def _production_split(session: Session, agent_id: int,
                      start: date, end: date) -> dict:
    """AFYP plus commission split into direct vs override for one agent/window."""
    afyp = _afyp_by_agent(session, start, end, {agent_id}).get(agent_id, Decimal("0"))

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
                      "commission": float(periods_data[k][aid]["direct"]),
                      "override": float(periods_data[k][aid]["override"])}
        rows.append(row)
    return rows
