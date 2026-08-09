"""
AFYP conversion on products and the team-production report (AFYP + commission
per agent across YTD / last month / current month).
"""
from decimal import Decimal
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, Agent, AgentLevel, Role, Client, Product, ProductType, OverrideRule,
    Transaction, TxnStatus, now_utc,
)
from app.services import commission_engine, reports


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    mgr = Agent(code="M", name="Mgr", email="m@x.com", level=1, role=Role.MANAGER,
                unit_code="U-M")
    s.add(mgr); s.flush()
    ag = Agent(code="A", name="Ag", email="a@x.com", level=2, role=Role.AGENT, upline_id=mgr.id)
    s.add(ag); s.flush()
    prod = Product(code="INS", name="Plan", type=ProductType.INSURANCE,
                   base_commission_rate=Decimal("0.05"), afyp_conversion=Decimal("0.10"))
    s.add(prod)
    s.add(OverrideRule(product_type=ProductType.INSURANCE, level_gap=1,
                       override_rate=Decimal("0.25")))
    cl = Client(ref="C", name="C", agent_id=ag.id)
    s.add(cl); s.flush()
    s.commit()
    s._ids = {"mgr": mgr.id, "ag": ag.id, "prod": prod.id, "client": cl.id}
    yield s
    s.close()


def _settle(db, notional, trade_date):
    t = Transaction(ref=f"T{trade_date}", client_id=db._ids["client"],
                    product_id=db._ids["prod"], agent_id=db._ids["ag"],
                    notional=Decimal(notional), status=TxnStatus.SETTLED,
                    trade_date=trade_date, settled_at=now_utc())
    db.add(t); db.flush()
    commission_engine.compute_for_transaction(db, t, as_of=trade_date)
    db.commit()
    return t


def test_afyp_is_notional_times_conversion(db):
    today = date.today()
    _settle(db, "1000000", today)  # AFYP = 1,000,000 × 0.10 = 100,000
    prod = reports.production_by_agent(db, {db._ids["ag"]}, date(today.year, 1, 1), today)
    assert prod[db._ids["ag"]]["afyp"] == Decimal("100000.00")
    # closer earns 5% direct = 50,000
    assert prod[db._ids["ag"]]["commission"] == Decimal("50000.00")


def test_team_production_three_periods(db):
    today = date.today()
    _settle(db, "1000000", today)  # falls in YTD + current month
    rows = {r["agent_id"]: r for r in reports.team_production(db, {db._ids["mgr"], db._ids["ag"]})}
    ag = rows[db._ids["ag"]]
    assert ag["ytd"]["afyp"] == 100000.0
    assert ag["current_month"]["afyp"] == 100000.0
    assert ag["last_month"]["afyp"] == 0.0
    # the manager writes nothing of their own but earns the gap-1 override (25% of 50k)
    mgr = rows[db._ids["mgr"]]
    assert mgr["ytd"]["afyp"] == 0.0
    assert mgr["ytd"]["commission"] == 12500.0
