"""
Phase 6 end-to-end scenario, driven through the HTTP API exactly as the frontend
would. Covers the full lifecycle:

  1. A 4-level agency with one upfront and one trail product (two lines).
  2. An agent logs in, creates a client, books and settles an insurance sale.
  3. The ledger shows direct-to-closer + overrides at gaps 1/2/3 at the right rates.
  4. A trail fund is settled; accruals run forward N periods -> per-period entries.
  5. Cancelling the insurance sale nets that statement line to zero (clawback).
  6. Locking the period and running a payout marks entries paid with a payable summary.
  7. A manager sees the whole subtree; a sibling agent cannot see another line's client.
"""
from decimal import Decimal
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import (
    Base, Agent, AgentLevel, Role, Product, ProductType, OverrideRule,
    CommissionSchedule, TrailFrequency,
)
from app.security import hash_password

# Anchor the scenario to the first day of the current month so that, on settle
# (which accrues everything due up to "today"), only period 0 of a quarterly
# trail product is due; later quarters fall in future months.
TRADE = date.today().replace(day=1)
YM = f"{TRADE.year}-{TRADE.month:02d}"
ACCRUE_ASOF = (TRADE + timedelta(days=210)).isoformat()  # ~7 months -> periods 0,1,2


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    s = Session()

    def mk(code, level, role, upline=None):
        a = Agent(code=code, name=code, email=f"{code}@x.com", level=level, role=role,
                  upline_id=(upline.id if upline else None),
                  password_hash=hash_password("pw"))
        s.add(a); s.flush()
        return a

    # A-line + a sibling B-line under the same L1.
    a1 = mk("A1", AgentLevel.L1, Role.ADMIN)
    a2 = mk("A2", AgentLevel.L2, Role.MANAGER, a1)
    a3 = mk("A3", AgentLevel.L3, Role.MANAGER, a2)
    a4 = mk("A4", AgentLevel.L4, Role.AGENT, a3)
    b2 = mk("B2", AgentLevel.L2, Role.MANAGER, a1)
    b3 = mk("B3", AgentLevel.L3, Role.MANAGER, b2)
    b4 = mk("B4", AgentLevel.L4, Role.AGENT, b3)

    insurance = Product(code="INS", name="Whole Life", type=ProductType.INSURANCE,
                        base_commission_rate=Decimal("0.05"))
    trail = Product(code="TRL", name="Income Fund", type=ProductType.FUND,
                    base_commission_rate=Decimal("0.0025"),
                    commission_schedule=CommissionSchedule.TRAIL,
                    trail_frequency=TrailFrequency.QUARTERLY, trail_periods=4)
    s.add_all([insurance, trail]); s.flush()
    for gap, rate in [(1, "0.015"), (2, "0.0075"), (3, "0.0025")]:
        s.add(OverrideRule(product_type=ProductType.INSURANCE, level_gap=gap,
                           override_rate=Decimal(rate)))
    for gap, rate in [(1, "0.0010"), (2, "0.0005")]:
        s.add(OverrideRule(product_type=ProductType.FUND, level_gap=gap,
                           override_rate=Decimal(rate)))
    s.commit()
    ids = {"a1": a1.id, "a2": a2.id, "a3": a3.id, "a4": a4.id, "b4": b4.id,
           "insurance": insurance.id, "trail": trail.id}
    s.close()

    from app import main
    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()
    main.app.dependency_overrides[main.get_db] = override_get_db
    tc = TestClient(main.app)
    tc._ids = ids
    yield tc
    main.app.dependency_overrides.clear()


def auth(tc, code):
    r = tc.post("/auth/login", json={"username": code, "password": "pw"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def line(statement, kind, ptype):
    for ln in statement["lines"]:
        if ln["kind"] == kind and ln["product_type"] == ptype:
            return ln
    return None


def test_full_scenario(client):
    ids = client._ids
    admin = auth(client, "A1")
    agent = auth(client, "A4")

    # --- 2. Agent creates a client and books+settles an insurance sale ---------
    r = client.post("/clients", headers=agent, json={
        "ref": "E2E-C1", "name": "Scenario Client", "agent_id": ids["a4"],
    })
    assert r.status_code == 200, r.text
    client_id = r.json()["id"]

    r = client.post("/transactions", headers=agent, json={
        "ref": "E2E-INS", "client_id": client_id, "product_id": ids["insurance"],
        "agent_id": ids["a4"], "notional": "200000", "trade_date": TRADE.isoformat(),
    })
    assert r.status_code == 200, r.text
    ins_txn = r.json()["id"]
    assert client.post(f"/transactions/{ins_txn}/settle", headers=agent).status_code == 200

    # --- 3. Ledger: direct to closer + overrides at gaps 1/2/3 -----------------
    win = f"?start={TRADE.isoformat()}&end={TRADE.isoformat()}"
    st_a4 = client.get(f"/reports/agent/{ids['a4']}{win}", headers=admin).json()
    st_a3 = client.get(f"/reports/agent/{ids['a3']}{win}", headers=admin).json()
    st_a2 = client.get(f"/reports/agent/{ids['a2']}{win}", headers=admin).json()
    st_a1 = client.get(f"/reports/agent/{ids['a1']}{win}", headers=admin).json()
    assert line(st_a4, "direct", "insurance")["amount"] == 10000.0   # 5% of 200k
    assert line(st_a3, "override", "insurance")["amount"] == 3000.0  # gap 1: 1.5%
    assert line(st_a2, "override", "insurance")["amount"] == 1500.0  # gap 2: 0.75%
    assert line(st_a1, "override", "insurance")["amount"] == 500.0   # gap 3: 0.25%

    # --- 4. Trail fund: settle then accrue forward -----------------------------
    r = client.post("/transactions", headers=agent, json={
        "ref": "E2E-TRL", "client_id": client_id, "product_id": ids["trail"],
        "agent_id": ids["a4"], "notional": "100000", "trade_date": TRADE.isoformat(),
    })
    assert r.status_code == 200
    trail_txn = r.json()["id"]
    assert client.post(f"/transactions/{trail_txn}/settle", headers=agent).status_code == 200

    # On settle only period 0 exists -> one direct fund entry.
    st = client.get(f"/reports/agent/{ids['a4']}", headers=admin).json()
    assert line(st, "direct", "fund")["count"] == 1
    # Accrue two quarters forward -> periods 0,1,2 (three direct fund entries).
    r = client.post(f"/accruals/run?as_of={ACCRUE_ASOF}", headers=admin)
    assert r.status_code == 200
    st = client.get(f"/reports/agent/{ids['a4']}", headers=admin).json()
    assert line(st, "direct", "fund")["count"] == 3
    assert line(st, "direct", "fund")["amount"] == 750.0  # 3 × (0.25% of 100k)

    # --- 5. Cancel the insurance sale -> statement line nets to zero -----------
    assert client.post(f"/transactions/{ins_txn}/cancel", headers=agent).status_code == 200
    st_a4 = client.get(f"/reports/agent/{ids['a4']}{win}", headers=admin).json()
    ins_line = line(st_a4, "direct", "insurance")
    assert ins_line["amount"] == 0.0     # 10000 + (-10000)
    assert ins_line["count"] == 2        # original + reversal both visible

    # --- 6. Lock the period, run a payout --------------------------------------
    assert client.post(f"/periods/{YM}/lock", headers=admin).status_code == 200
    # A new sale into the locked period is rejected (409).
    r = client.post("/transactions", headers=agent, json={
        "ref": "E2E-LATE", "client_id": client_id, "product_id": ids["insurance"],
        "agent_id": ids["a4"], "notional": "50000", "trade_date": TRADE.isoformat(),
    })
    assert r.status_code == 409

    payout = client.post(f"/payouts/run?period={YM}", headers=admin).json()
    assert payout["new_entries_paid"] > 0
    assert isinstance(payout["payable"], list) and len(payout["payable"]) > 0
    # Idempotent: a second run pays nothing new.
    again = client.post(f"/payouts/run?period={YM}", headers=admin).json()
    assert again["new_entries_paid"] == 0
    assert again["total"] == payout["total"]

    # --- 7. Manager sees subtree; sibling agent is isolated --------------------
    mgr = auth(client, "A2")
    assert client.get(f"/clients/{client_id}", headers=mgr).status_code == 200
    sibling = auth(client, "B4")
    assert client.get(f"/clients/{client_id}", headers=sibling).status_code == 403
