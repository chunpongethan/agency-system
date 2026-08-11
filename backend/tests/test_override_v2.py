"""
Override model v2: an upline earns a percentage of the closing agent's *commission*
(not the notional), reaching up to 4 levels — gap1 25%, gap2 20%, gap3 4%, gap4 1%,
gap5+ 0%. Hierarchy depth is unlimited.
"""
from decimal import Decimal
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, Agent, Client, Product, ProductType, OverrideRule,
    Transaction, TxnStatus, CommissionKind, Title,
)
from app.services import commission_engine


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()

    # A 6-deep chain: L1 (top) ... L6 (frontline closer).
    chain = []
    upline = None
    titles = [Title.PRINCIPAL_PARTNER, Title.DISTRICT_DIRECTOR, Title.DISTRICT_MANAGER,
              Title.BUSINESS_MANAGER, Title.BUSINESS_MANAGER, Title.BUSINESS_MANAGER]
    for depth in range(1, 7):
        a = Agent(code=f"L{depth}", name=f"L{depth}", email=f"l{depth}@x.com",
                  level=depth, title=titles[depth - 1],
                  upline_id=(upline.id if upline else None))
        s.add(a); s.flush()
        chain.append(a)
        upline = a

    prod = Product(code="P", name="Plan", type=ProductType.INSURANCE,
                   base_commission_rate=Decimal("0.10"))
    s.add(prod)
    for gap, rate in [(1, "0.25"), (2, "0.20"), (3, "0.04"), (4, "0.01")]:
        s.add(OverrideRule(product_type=ProductType.INSURANCE, level_gap=gap,
                           override_rate=Decimal(rate)))
    client = Client(ref="C", name="C", agent_id=chain[-1].id)
    s.add(client); s.flush()
    s.commit()
    s._chain = chain
    s._prod = prod
    s._client = client
    yield s
    s.close()


def test_override_is_percent_of_commission_up_to_four_levels(db):
    chain = db._chain  # [L1..L6]; L6 closes
    closer = chain[-1]
    txn = Transaction(ref="T", client_id=db._client.id, product_id=db._prod.id,
                      agent_id=closer.id, notional=Decimal("100000"),
                      status=TxnStatus.APPROVED, trade_date=date(2024, 1, 1))
    db.add(txn); db.flush()
    entries = commission_engine.compute_for_transaction(db, txn)
    by_agent = {e.agent_id: e for e in entries}

    commission = Decimal("10000.00")  # 10% of 100k
    assert by_agent[closer.id].kind == CommissionKind.DIRECT
    assert by_agent[closer.id].amount == commission
    # gaps 1..4 up the chain: L5, L4, L3, L2
    assert by_agent[chain[4].id].amount == Decimal("2500.00")  # gap1 25%
    assert by_agent[chain[3].id].amount == Decimal("2000.00")  # gap2 20%
    assert by_agent[chain[2].id].amount == Decimal("400.00")   # gap3 4%
    assert by_agent[chain[1].id].amount == Decimal("100.00")   # gap4 1%
    # gap5 (L1) earns nothing — no entry.
    assert chain[0].id not in by_agent
    assert len(entries) == 5  # closer + 4 overrides


def test_deep_downline_beyond_four_gaps_earns_zero(db):
    # The top agent (L1) is 5 gaps above the L6 closer -> 0%.
    chain = db._chain
    txn = Transaction(ref="T2", client_id=db._client.id, product_id=db._prod.id,
                      agent_id=chain[-1].id, notional=Decimal("100000"),
                      status=TxnStatus.APPROVED, trade_date=date(2024, 1, 1))
    db.add(txn); db.flush()
    entries = commission_engine.compute_for_transaction(db, txn)
    assert all(e.agent_id != chain[0].id for e in entries)
