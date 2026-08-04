"""
Phase 1 tests: agent validation, effective-dated override rules, trail accrual
over N periods, and clawback netting.
"""
from decimal import Decimal
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, Agent, AgentLevel, Client, Product, ProductType,
    OverrideRule, Transaction, TxnStatus, CommissionEntry, CommissionKind,
    CommissionSchedule, TrailFrequency,
)
from app.services import commission_engine, agent_service


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    l1 = Agent(code="A1", name="L1", email="l1@x.com", level=AgentLevel.L1)
    session.add(l1); session.flush()
    l2 = Agent(code="A2", name="L2", email="l2@x.com", level=AgentLevel.L2, upline_id=l1.id)
    session.add(l2); session.flush()
    l3 = Agent(code="A3", name="L3", email="l3@x.com", level=AgentLevel.L3, upline_id=l2.id)
    session.add(l3); session.flush()
    l4 = Agent(code="A4", name="L4", email="l4@x.com", level=AgentLevel.L4, upline_id=l3.id)
    session.add(l4); session.flush()

    client = Client(ref="C1", name="Client", agent_id=l4.id)
    session.add(client); session.flush()
    session.commit()
    session._agents = {"l1": l1, "l2": l2, "l3": l3, "l4": l4}
    session._client = client
    yield session
    session.close()


def _insurance_rules(db, gap_rates, valid_from=date(1900, 1, 1), valid_to=None):
    for gap, rate in gap_rates:
        db.add(OverrideRule(product_type=ProductType.INSURANCE, level_gap=gap,
                            override_rate=Decimal(rate),
                            valid_from=valid_from, valid_to=valid_to))
    db.flush()


# --------------------------------------------------------------------------- #
# Agent validation
# --------------------------------------------------------------------------- #
def test_validation_rejects_out_of_range_level(db):
    with pytest.raises(agent_service.ValidationError):
        agent_service.validate_agent(db, level=5, upline_id=None)
    with pytest.raises(agent_service.ValidationError):
        agent_service.validate_agent(db, level=0, upline_id=None)


def test_validation_rejects_wrong_upline_level(db):
    # An L4 whose "upline" is also L4 (gap != 1) must be rejected.
    with pytest.raises(agent_service.ValidationError):
        agent_service.validate_agent(db, level=4, upline_id=db._agents["l1"].id)


def test_validation_accepts_correct_upline(db):
    # A new L4 under the existing L3 is valid.
    agent_service.validate_agent(db, level=4, upline_id=db._agents["l3"].id)


def test_validation_requires_upline_for_non_root(db):
    with pytest.raises(agent_service.ValidationError):
        agent_service.validate_agent(db, level=3, upline_id=None)


def test_validation_rejects_cycle(db):
    # Trying to set l2's upline to l4 (its own descendant) is a cycle.
    l2, l4 = db._agents["l2"], db._agents["l4"]
    with pytest.raises(agent_service.ValidationError):
        agent_service.validate_agent(db, level=int(l2.level), upline_id=l4.id,
                                     agent_id=l2.id)


# --------------------------------------------------------------------------- #
# Effective-dated override rules
# --------------------------------------------------------------------------- #
def test_effective_dated_rule_selection(db):
    prod = Product(code="P1", name="Plan", type=ProductType.INSURANCE,
                   base_commission_rate=Decimal("0.05"))
    db.add(prod); db.flush()
    # Old rule (until 2023-12-31) then a new higher rule from 2024-01-01.
    db.add(OverrideRule(product_type=ProductType.INSURANCE, level_gap=1,
                        override_rate=Decimal("0.010"),
                        valid_from=date(2000, 1, 1), valid_to=date(2023, 12, 31)))
    db.add(OverrideRule(product_type=ProductType.INSURANCE, level_gap=1,
                        override_rate=Decimal("0.020"),
                        valid_from=date(2024, 1, 1), valid_to=None))
    db.flush()

    old = Transaction(ref="OLD", client_id=db._client.id, product_id=prod.id,
                      agent_id=db._agents["l4"].id, notional=Decimal("100000"),
                      status=TxnStatus.SETTLED, trade_date=date(2023, 6, 1))
    new = Transaction(ref="NEW", client_id=db._client.id, product_id=prod.id,
                      agent_id=db._agents["l4"].id, notional=Decimal("100000"),
                      status=TxnStatus.SETTLED, trade_date=date(2024, 6, 1))
    db.add_all([old, new]); db.flush()

    old_entries = commission_engine.compute_for_transaction(db, old)
    new_entries = commission_engine.compute_for_transaction(db, new)

    gap1_old = next(e for e in old_entries if e.level_gap == 1)
    gap1_new = next(e for e in new_entries if e.level_gap == 1)
    assert gap1_old.rate == Decimal("0.010")   # 1% pre-2024
    assert gap1_old.amount == Decimal("1000.00")
    assert gap1_new.rate == Decimal("0.020")   # 2% from 2024
    assert gap1_new.amount == Decimal("2000.00")


# --------------------------------------------------------------------------- #
# Trail accrual over N periods
# --------------------------------------------------------------------------- #
def test_trail_accrual_over_periods(db):
    _insurance_rules(db, [(1, "0.010")])
    trail = Product(code="TRAIL", name="Trail Fund", type=ProductType.INSURANCE,
                    base_commission_rate=Decimal("0.01"),
                    commission_schedule=CommissionSchedule.TRAIL,
                    trail_frequency=TrailFrequency.MONTHLY, trail_periods=4)
    db.add(trail); db.flush()

    txn = Transaction(ref="TR", client_id=db._client.id, product_id=trail.id,
                      agent_id=db._agents["l4"].id, notional=Decimal("100000"),
                      status=TxnStatus.SETTLED, trade_date=date(2024, 1, 15))
    db.add(txn); db.flush()

    # On settle only period 0 is due.
    commission_engine.compute_for_transaction(db, txn, as_of=date(2024, 1, 15))
    periods = {e.period_index for e in txn.commissions}
    assert periods == {0}

    # Roll forward two months: periods 0,1,2 due.
    commission_engine.run_accruals(db, as_of=date(2024, 3, 20))
    db.refresh(txn)
    periods = {e.period_index for e in txn.commissions}
    assert periods == {0, 1, 2}

    # Roll to the end: all 4 periods.
    commission_engine.run_accruals(db, as_of=date(2024, 5, 20))
    db.refresh(txn)
    direct = [e for e in txn.commissions if e.kind == CommissionKind.DIRECT]
    assert len(direct) == 4                       # one per period
    assert all(e.amount == Decimal("1000.00") for e in direct)  # 1% each period
    # Never over-accrues beyond trail_periods.
    commission_engine.run_accruals(db, as_of=date(2030, 1, 1))
    db.refresh(txn)
    assert len({e.period_index for e in txn.commissions}) == 4


def test_upfront_product_single_period(db):
    _insurance_rules(db, [(1, "0.010")])
    prod = Product(code="UP", name="Upfront", type=ProductType.INSURANCE,
                   base_commission_rate=Decimal("0.05"))  # default UPFRONT
    db.add(prod); db.flush()
    txn = Transaction(ref="UPF", client_id=db._client.id, product_id=prod.id,
                      agent_id=db._agents["l4"].id, notional=Decimal("100000"),
                      status=TxnStatus.SETTLED, trade_date=date(2024, 1, 1))
    db.add(txn); db.flush()
    commission_engine.compute_for_transaction(db, txn)
    commission_engine.run_accruals(db, as_of=date(2030, 1, 1))
    db.refresh(txn)
    assert {e.period_index for e in txn.commissions} == {0}


# --------------------------------------------------------------------------- #
# Clawback netting
# --------------------------------------------------------------------------- #
def test_clawback_nets_to_zero(db):
    _insurance_rules(db, [(1, "0.015"), (2, "0.0075"), (3, "0.0025")])
    prod = Product(code="P1", name="Plan", type=ProductType.INSURANCE,
                   base_commission_rate=Decimal("0.05"))
    db.add(prod); db.flush()
    from app.models.models import now_utc
    txn = Transaction(ref="X", client_id=db._client.id, product_id=prod.id,
                      agent_id=db._agents["l4"].id, notional=Decimal("100000"),
                      status=TxnStatus.SETTLED, trade_date=date(2024, 1, 1),
                      settled_at=now_utc())
    db.add(txn); db.flush()

    commission_engine.compute_for_transaction(db, txn)
    settled_total = sum(e.amount for e in txn.commissions)
    assert settled_total == Decimal("7500.00")  # 5000 + 1500 + 750 + 250
    assert all(not e.is_reversal for e in txn.commissions)

    # Cancel -> reversals appear, ledger nets to zero, originals still visible.
    txn.status = TxnStatus.CANCELLED
    commission_engine.compute_for_transaction(db, txn)
    db.refresh(txn)
    total = sum(e.amount for e in txn.commissions)
    assert total == Decimal("0.00")
    assert any(e.is_reversal for e in txn.commissions)
    assert any(not e.is_reversal for e in txn.commissions)
    assert len(txn.commissions) == 8  # 4 original + 4 reversals

    # Re-settle -> reversals gone, net back to original.
    txn.status = TxnStatus.SETTLED
    commission_engine.compute_for_transaction(db, txn)
    db.refresh(txn)
    assert sum(e.amount for e in txn.commissions) == Decimal("7500.00")
    assert all(not e.is_reversal for e in txn.commissions)


def test_cancel_never_settled_produces_nothing(db):
    _insurance_rules(db, [(1, "0.015")])
    prod = Product(code="P1", name="Plan", type=ProductType.INSURANCE,
                   base_commission_rate=Decimal("0.05"))
    db.add(prod); db.flush()
    txn = Transaction(ref="NS", client_id=db._client.id, product_id=prod.id,
                      agent_id=db._agents["l4"].id, notional=Decimal("100000"),
                      status=TxnStatus.CANCELLED, trade_date=date(2024, 1, 1))
    db.add(txn); db.flush()  # settled_at stays None -> never settled
    entries = commission_engine.compute_for_transaction(db, txn)
    assert entries == []
