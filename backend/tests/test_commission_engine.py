"""Tests for the commission engine: direct pay, override chain, idempotency, cancellation."""
from decimal import Decimal
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, Agent, AgentLevel, Client, Product, ProductType,
    OverrideRule, Transaction, TxnStatus, CommissionEntry, CommissionKind,
)
from app.services import commission_engine


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

    prod = Product(code="P1", name="Plan", type=ProductType.INSURANCE,
                   base_commission_rate=Decimal("0.05"))
    session.add(prod)
    # Overrides are a % of the closer's commission: gap1 25%, gap2 20%, gap3 4%.
    for gap, rate in [(1, "0.25"), (2, "0.20"), (3, "0.04"), (4, "0.01")]:
        session.add(OverrideRule(product_type=ProductType.INSURANCE,
                                 level_gap=gap, override_rate=Decimal(rate)))
    client = Client(ref="C1", name="Client", agent_id=l4.id)
    session.add(client); session.flush()
    session.commit()
    session._agents = {"l1": l1, "l2": l2, "l3": l3, "l4": l4}
    session._prod = prod
    session._client = client
    yield session
    session.close()


def _txn(db, notional="100000", agent=None):
    t = Transaction(ref="T1", client_id=db._client.id, product_id=db._prod.id,
                    agent_id=(agent or db._agents["l4"]).id,
                    notional=Decimal(notional), status=TxnStatus.APPROVED,
                    trade_date=date.today())
    db.add(t); db.flush()
    return t


def test_direct_and_override_chain(db):
    t = _txn(db)
    entries = commission_engine.compute_for_transaction(db, t)
    by_agent = {e.agent_id: e for e in entries}

    assert len(entries) == 4  # closer + 3 uplines
    assert by_agent[db._agents["l4"].id].kind == CommissionKind.DIRECT
    assert by_agent[db._agents["l4"].id].amount == Decimal("5000.00")   # 5% of 100k
    assert by_agent[db._agents["l3"].id].amount == Decimal("1250.00")   # gap1: 25% of 5000
    assert by_agent[db._agents["l2"].id].amount == Decimal("1000.00")   # gap2: 20% of 5000
    assert by_agent[db._agents["l1"].id].amount == Decimal("200.00")    # gap3: 4% of 5000


def test_idempotent_recompute(db):
    t = _txn(db)
    commission_engine.compute_for_transaction(db, t)
    commission_engine.compute_for_transaction(db, t)
    count = db.query(CommissionEntry).filter_by(transaction_id=t.id).count()
    assert count == 4  # not doubled


def test_top_agent_gets_no_override(db):
    # L2 closes: only L1 (gap 1) qualifies as upline.
    t = _txn(db, agent=db._agents["l2"])
    entries = commission_engine.compute_for_transaction(db, t)
    kinds = sorted(e.kind.value for e in entries)
    assert kinds == ["direct", "override"]
    assert len(entries) == 2


def test_cancelled_txn_clears_entries(db):
    t = _txn(db)
    commission_engine.compute_for_transaction(db, t)
    t.status = TxnStatus.CANCELLED
    entries = commission_engine.compute_for_transaction(db, t)
    assert entries == []
    assert db.query(CommissionEntry).filter_by(transaction_id=t.id).count() == 0


def test_per_year_trail_insurance(db):
    """An insurance product with a Yr1..Yr3 schedule set to 分期 (TRAIL) pays each
    year's rate as an annual installment (period 0 = Yr1 at settle, then yearly)."""
    from app.models.models import CommissionSchedule
    p = Product(code="PY", name="PerYear", type=ProductType.INSURANCE,
                base_commission_rate=Decimal("0.20"),
                commission_schedule=CommissionSchedule.TRAIL,
                year_commissions=["0.20", "0.10", "0.05"])
    db.add(p); db.flush()
    t = Transaction(ref="TPY", client_id=db._client.id, product_id=p.id,
                    agent_id=db._agents["l4"].id, notional=Decimal("1000000"),
                    status=TxnStatus.APPROVED, trade_date=date(2024, 1, 1))
    db.add(t); db.flush()

    # At settle only period 0 (Yr1) is due.
    e0 = commission_engine.compute_for_transaction(db, t, as_of=date(2024, 1, 1))
    d0 = [e for e in e0 if e.kind == CommissionKind.DIRECT and not e.is_reversal]
    assert len(d0) == 1 and d0[0].period_index == 0 and d0[0].amount == Decimal("200000.00")

    # Three years on, Yr1..Yr3 have all come due: 200k, 100k, 50k.
    e3 = commission_engine.compute_for_transaction(db, t, as_of=date(2026, 6, 1))
    d3 = sorted([e for e in e3 if e.kind == CommissionKind.DIRECT and not e.is_reversal],
                key=lambda e: e.period_index)
    assert [e.period_index for e in d3] == [0, 1, 2]
    assert [float(e.amount) for e in d3] == [200000.0, 100000.0, 50000.0]
