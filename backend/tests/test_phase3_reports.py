"""
Phase 3 tests: period locking (freeze + 409 + admin adjustment routing),
idempotent payout runs, and CSV/PDF export generation over seed-like data.
"""
from decimal import Decimal
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, Agent, AgentLevel, Role, Client, Product, ProductType,
    OverrideRule, Transaction, TxnStatus, CommissionEntry, now_utc,
)
from app.services import commission_engine, reports, periods, payouts, exports
from app.security import hash_password


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()

    l1 = Agent(code="A1", name="Grace", email="a1@x.com", level=AgentLevel.L1,
               role=Role.MANAGER, password_hash=hash_password("pw"))
    s.add(l1); s.flush()
    l2 = Agent(code="A2", name="Leo", email="a2@x.com", level=AgentLevel.L2,
               upline_id=l1.id, role=Role.MANAGER)
    s.add(l2); s.flush()
    l3 = Agent(code="A3", name="Priya", email="a3@x.com", level=AgentLevel.L3,
               upline_id=l2.id, role=Role.MANAGER)
    s.add(l3); s.flush()
    l4 = Agent(code="A4", name="Tom", email="a4@x.com", level=AgentLevel.L4,
               upline_id=l3.id, role=Role.AGENT)
    s.add(l4); s.flush()

    prod = Product(code="P1", name="Plan", type=ProductType.INSURANCE,
                   base_commission_rate=Decimal("0.05"))
    s.add(prod)
    for gap, rate in [(1, "0.25"), (2, "0.20"), (3, "0.04")]:
        s.add(OverrideRule(product_type=ProductType.INSURANCE, level_gap=gap,
                           override_rate=Decimal(rate)))
    client = Client(ref="C1", name="Client", agent_id=l4.id)
    s.add(client); s.flush()
    s.commit()
    s._a = {"l1": l1, "l2": l2, "l3": l3, "l4": l4}
    s._prod = prod
    s._client = client
    yield s
    s.close()


def _settle(db, ref, trade_date, notional="100000"):
    t = Transaction(ref=ref, client_id=db._client.id, product_id=db._prod.id,
                    agent_id=db._a["l4"].id, notional=Decimal(notional),
                    status=TxnStatus.SETTLED, trade_date=trade_date, settled_at=now_utc())
    db.add(t); db.flush()
    commission_engine.compute_for_transaction(db, t, as_of=trade_date)
    db.commit()
    return t


# --------------------------------------------------------------------------- #
# Period locking
# --------------------------------------------------------------------------- #
def test_period_lock_and_snapshot(db):
    _settle(db, "T1", date(2024, 3, 10))
    period = periods.lock_period(db, 2024, 3)
    assert period.is_locked
    snap = periods.period_snapshot(db, 2024, 3)
    assert snap is not None
    # snapshot totals reflect the settled sale (5000 + 1250 + 1000 + 200)
    assert sum(r["total"] for r in snap) == 7450.0


def test_locked_period_rejects_trade(db):
    periods.lock_period(db, 2024, 3)
    with pytest.raises(periods.PeriodLockedError):
        periods.assert_open_for_trade(db, date(2024, 3, 15))


def test_admin_adjustment_routes_to_next_open(db):
    periods.lock_period(db, 2024, 3)
    routed = periods.assert_open_for_trade(db, date(2024, 3, 15), allow_adjust=True)
    assert routed == date(2024, 4, 1)  # next open month's start


def test_open_period_unaffected(db):
    assert periods.assert_open_for_trade(db, date(2024, 5, 1)) == date(2024, 5, 1)


# --------------------------------------------------------------------------- #
# Payout runs
# --------------------------------------------------------------------------- #
def test_payout_run_marks_paid_and_is_idempotent(db):
    _settle(db, "T1", date(2024, 3, 10))
    result = payouts.run_payout(db, 2024, 3)
    assert result["new_entries_paid"] == 4
    assert result["total"] == 7450.0
    # all entries in the period now marked paid
    unpaid = [e for e in db.query(CommissionEntry).all()
              if not e.paid and (e.accrual_date or date(2024, 3, 1)).month == 3]
    assert unpaid == []

    # Re-run: nothing new, same totals (idempotent).
    again = payouts.run_payout(db, 2024, 3)
    assert again["new_entries_paid"] == 0
    assert again["total"] == 7450.0
    assert again["payout_id"] == result["payout_id"]


def test_payout_reversal_becomes_next_adjustment(db):
    t = _settle(db, "T1", date(2024, 3, 10))
    payouts.run_payout(db, 2024, 3)
    # Cancel after payout -> reversal entries are unpaid negatives.
    t.status = TxnStatus.CANCELLED
    commission_engine.compute_for_transaction(db, t, as_of=date(2024, 3, 10))
    db.commit()
    result = payouts.run_payout(db, 2024, 3)
    # net for the period is now zero (originals + reversals)
    assert result["total"] == 0.0
    assert result["new_entries_paid"] == 4  # the four reversals


# --------------------------------------------------------------------------- #
# Exports
# --------------------------------------------------------------------------- #
def test_csv_exports_generate(db):
    _settle(db, "T1", date(2024, 3, 10))
    statement = reports.agent_statement(db, db._a["l4"].id)
    csv_text = exports.statement_to_csv(statement)
    assert "Grand total" in csv_text and "5,000.00" in csv_text

    summary = reports.agency_summary(db)
    summary_csv = exports.agency_summary_to_csv(summary)
    assert "agent_id" in summary_csv


def test_pdf_exports_generate(db):
    _settle(db, "T1", date(2024, 3, 10))
    statement = reports.agent_statement(db, db._a["l4"].id)
    pdf = exports.statement_to_pdf(statement)
    assert pdf[:4] == b"%PDF"

    summary = reports.agency_summary(db)
    summary_pdf = exports.agency_summary_to_pdf(summary)
    assert summary_pdf[:4] == b"%PDF"
