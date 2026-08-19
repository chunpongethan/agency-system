"""
Period locking.

A Period is a (year, month). Locking freezes its statements: once locked, a
transaction dated into that month is rejected (409) unless an admin routes it to
the next open period as an adjustment. A locked period serves a stored snapshot
of its agency summary so re-reads are stable regardless of later ledger edits.
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Period, Agent, now_utc
from app.services import reports


class PeriodLockedError(Exception):
    """Raised when a mutation targets a locked period (-> HTTP 409)."""


def parse_ym(ym: str) -> tuple[int, int]:
    """'2024-03' -> (2024, 3)."""
    try:
        y, m = ym.split("-")
        year, month = int(y), int(m)
    except (ValueError, AttributeError):
        raise ValueError(f"invalid period '{ym}', expected YYYY-MM")
    if not 1 <= month <= 12:
        raise ValueError(f"invalid month in '{ym}'")
    return year, month


def get_period(session: Session, year: int, month: int,
               company: str = "heritree") -> Period | None:
    return session.execute(
        select(Period).where(Period.year == year, Period.month == month,
                             Period.company == company)
    ).scalars().first()


def get_or_create_period(session: Session, year: int, month: int,
                         company: str = "heritree") -> Period:
    period = get_period(session, year, month, company)
    if period is None:
        period = Period(year=year, month=month, company=company, is_locked=False)
        session.add(period)
        session.flush()
    return period


def is_locked(session: Session, year: int, month: int, company: str = "heritree") -> bool:
    period = get_period(session, year, month, company)
    return bool(period and period.is_locked)


def lock_period(session: Session, year: int, month: int,
                company: str = "heritree") -> Period:
    """Lock a period for one company, snapshotting that company's agency summary."""
    period = get_or_create_period(session, year, month, company)
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    # end-exclusive: use the last day of the month for the inclusive window.
    last_day = date.fromordinal(end.toordinal() - 1)
    ids = {row[0] for row in session.execute(select(Agent.id).where(Agent.company == company))}
    snapshot = reports.agency_summary(session, start, last_day, agent_ids=ids)
    period.snapshot = json.dumps(snapshot)
    period.is_locked = True
    period.locked_at = now_utc()
    session.commit()
    return period


def unlock_period(session: Session, year: int, month: int,
                  company: str = "heritree") -> Period:
    period = get_or_create_period(session, year, month, company)
    period.is_locked = False
    period.snapshot = None
    period.locked_at = None
    session.commit()
    return period


def period_snapshot(session: Session, year: int, month: int,
                    company: str = "heritree") -> list | None:
    """The frozen agency summary for a locked period, or None if open."""
    period = get_period(session, year, month, company)
    if period and period.is_locked and period.snapshot:
        return json.loads(period.snapshot)
    return None


def next_open_month_start(session: Session, from_date: date,
                          company: str = "heritree") -> date:
    """First day of the next open month at/after `from_date`'s month."""
    year, month = from_date.year, from_date.month
    for _ in range(120):  # up to 10 years ahead, defensive bound
        if not is_locked(session, year, month, company):
            return date(year, month, 1)
        month += 1
        if month > 12:
            month, year = 1, year + 1
    raise ValueError("no open period found in the next 10 years")


def assert_open_for_trade(session: Session, trade_date: date,
                          allow_adjust: bool = False,
                          company: str = "heritree") -> date:
    """
    Ensure `trade_date` lands in an open period for `company`. Returns the
    (possibly adjusted) trade_date. If locked and allow_adjust, routes to the next
    open month's start; otherwise raises PeriodLockedError.
    """
    if not is_locked(session, trade_date.year, trade_date.month, company):
        return trade_date
    if not allow_adjust:
        raise PeriodLockedError(
            f"period {trade_date.year}-{trade_date.month:02d} is locked"
        )
    return next_open_month_start(session, trade_date, company)
