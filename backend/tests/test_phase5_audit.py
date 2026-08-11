"""
Phase 5 tests: audit entries are written for commission-affecting actions, and
the bulk-import validator accepts good hierarchies while rejecting broken ones.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import (
    Base, Agent, AgentLevel, Role, Client, Product, ProductType, AuditEntry,
)
from app.security import hash_password


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False)

    s = TestingSession()
    l1 = Agent(code="A1", name="Admin", email="a1@x.com", level=AgentLevel.L1,
               role=Role.ADMIN, password_hash=hash_password("pw"))
    s.add(l1); s.flush()
    l2 = Agent(code="A2", name="Mgr", email="a2@x.com", level=AgentLevel.L2,
               upline_id=l1.id, role=Role.AGENT, password_hash=hash_password("pw"))
    s.add(l2); s.flush()
    prod = Product(code="P1", name="Plan", type=ProductType.INSURANCE,
                   base_commission_rate=Decimal("0.05"))
    s.add(prod)
    cl = Client(ref="C1", name="Client", agent_id=l2.id)
    s.add(cl); s.commit()
    ids = {"prod": prod.id, "client": cl.id, "a2": l2.id}
    s.close()

    from app import main
    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()
    main.app.dependency_overrides[main.get_db] = override_get_db
    tc = TestClient(main.app)
    tc._ids = ids
    tc._session = TestingSession
    yield tc
    main.app.dependency_overrides.clear()


def _auth(tc, code="A1"):
    r = tc.post("/auth/login", json={"username": code, "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_audit_written_for_txn_lifecycle(client):
    h = _auth(client)
    # create
    r = client.post("/transactions", headers=h, json={
        "ref": "TX1", "client_id": client._ids["client"],
        "product_id": client._ids["prod"], "agent_id": client._ids["a2"],
        "notional": "100000",
    })
    assert r.status_code == 200
    txn_id = r.json()["id"]
    # settle
    assert client.post(f"/transactions/{txn_id}/approve", headers=h).status_code == 200
    # cancel
    assert client.post(f"/transactions/{txn_id}/cancel", headers=h).status_code == 200

    audit = client.get("/audit", headers=h).json()
    actions = {(a["entity"], a["action"]) for a in audit}
    assert ("transaction", "create") in actions
    assert ("transaction", "approve") in actions
    assert ("transaction", "cancel") in actions
    # each audit row records who did it
    assert all(a["actor_agent_id"] is not None for a in audit)


def test_audit_for_rule_and_payout(client):
    h = _auth(client)
    assert client.post("/override-rules", headers=h, json={
        "product_type": "insurance", "level_gap": 1, "override_rate": "0.02",
    }).status_code == 200
    assert client.post("/periods/2024-01/lock", headers=h).status_code == 200
    assert client.post("/payouts/run?period=2024-01", headers=h).status_code == 200

    audit = client.get("/audit", headers=h).json()
    actions = {(a["entity"], a["action"]) for a in audit}
    assert ("override_rule", "create") in actions
    assert ("period", "lock") in actions
    assert ("payout", "run") in actions


def test_bulk_import_validates_hierarchy():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    import bulk_import

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    good = [
        {"code": "Z1", "name": "Top", "email": "z1@x.com", "level": "1", "upline_code": "", "role": "admin"},
        {"code": "Z2", "name": "Sub", "email": "z2@x.com", "level": "2", "upline_code": "Z1", "role": "agent"},
    ]
    agents, errors = bulk_import.import_agents(session, good)
    assert len(agents) == 2 and errors == []

    # A level-3 under a level-1 upline (gap != 1) must be rejected.
    bad = [
        {"code": "Z3", "name": "Bad", "email": "z3@x.com", "level": "3", "upline_code": "Z1", "role": "agent"},
    ]
    _, errors2 = bulk_import.import_agents(session, bad)
    assert len(errors2) == 1
