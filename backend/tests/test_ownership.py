"""
Ownership model: clients & their transactions are owner-only; admins are not
sellers (no client access) but hold authority over transaction data.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import (
    Base, Agent, AgentLevel, Role, Client, Product, ProductType, OverrideRule,
)
from app.security import hash_password


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    s = Session()

    def mk(code, level, role, upline=None):
        a = Agent(code=code, name=code, email=f"{code}@x.com", level=level, role=role,
                  upline_id=(upline.id if upline else None), password_hash=hash_password("pw"))
        s.add(a); s.flush()
        return a

    adm = mk("ADM", 1, Role.ADMIN)
    top = mk("TOP", 1, Role.MANAGER)
    ax = mk("AX", 2, Role.AGENT, top)
    ay = mk("AY", 2, Role.AGENT, top)
    prod = Product(code="P", name="Plan", type=ProductType.INSURANCE,
                   base_commission_rate=Decimal("0.05"))
    s.add(prod)
    s.add(OverrideRule(product_type=ProductType.INSURANCE, level_gap=1,
                       override_rate=Decimal("0.25")))
    cx = Client(ref="CX", name="X-client", agent_id=ax.id)
    cy = Client(ref="CY", name="Y-client", agent_id=ay.id)
    s.add_all([cx, cy]); s.commit()
    ids = {"ax": ax.id, "ay": ay.id, "cx": cx.id, "cy": cy.id, "prod": prod.id}
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
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_client_is_owner_only(client):
    ids = client._ids
    ax, ay = auth(client, "AX"), auth(client, "AY")
    assert client.get(f"/clients/{ids['cx']}", headers=ax).status_code == 200
    assert client.get(f"/clients/{ids['cx']}", headers=ay).status_code == 403


def test_admin_has_no_client_access(client):
    ids = client._ids
    adm = auth(client, "ADM")
    assert client.get(f"/clients/{ids['cx']}", headers=adm).status_code == 403
    assert client.get("/clients", headers=adm).json() == []
    # admin cannot create a client either
    r = client.post("/clients", headers=adm, json={"ref": "Z", "name": "z", "agent_id": ids["ax"]})
    assert r.status_code == 403


def test_agent_cannot_book_for_others_client(client):
    ids = client._ids
    ax = auth(client, "AX")
    r = client.post("/transactions", headers=ax, json={
        "ref": "T-BAD", "client_id": ids["cy"], "product_id": ids["prod"],
        "agent_id": ids["ay"], "notional": "1000",
    })
    assert r.status_code == 403


def test_admin_has_transaction_authority(client):
    ids = client._ids
    adm = auth(client, "ADM")
    # Admin books a transaction on AX's client (transaction authority) ...
    r = client.post("/transactions", headers=adm, json={
        "ref": "T-ADM", "client_id": ids["cx"], "product_id": ids["prod"],
        "agent_id": ids["ax"], "notional": "100000",
    })
    assert r.status_code == 200, r.text
    txn_id = r.json()["id"]
    # ... settles and cancels it ...
    assert client.post(f"/transactions/{txn_id}/settle", headers=adm).status_code == 200
    assert client.post(f"/transactions/{txn_id}/cancel", headers=adm).status_code == 200
    # ... and may read the client's transactions (but still not the client itself).
    assert client.get(f"/clients/{ids['cx']}/transactions", headers=adm).status_code == 200
    assert client.get(f"/clients/{ids['cx']}", headers=adm).status_code == 403
