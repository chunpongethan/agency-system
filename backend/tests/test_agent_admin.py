"""
Admin agent maintenance: edit details, terminate (deactivate), reactivate.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base, Agent, Role
from app.security import hash_password


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    s = Session()
    adm = Agent(code="ADM", name="Admin", email="adm@x.com", level=1, role=Role.ADMIN,
                password_hash=hash_password("pw"))
    a1 = Agent(code="A1", name="One", email="a1@x.com", level=1, role=Role.MANAGER,
               password_hash=hash_password("pw"))
    a2 = Agent(code="A2", name="Two", email="a2@x.com", level=2, role=Role.AGENT,
               password_hash=hash_password("pw"))
    s.add_all([adm, a1, a2]); s.commit()
    ids = {"a1": a1.id, "a2": a2.id}
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


def test_admin_edits_agent(client):
    admin = auth(client, "ADM")
    r = client.patch(f"/agents/{client._ids['a2']}", headers=admin, json={
        "name": "Renamed", "email": "new@x.com", "role": "manager", "title": "district_manager",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Renamed" and body["email"] == "new@x.com"
    assert body["role"] == "manager" and body["title"] == "district_manager"


def test_email_clash_rejected(client):
    admin = auth(client, "ADM")
    # a2 -> a1's email should 409
    r = client.patch(f"/agents/{client._ids['a2']}", headers=admin, json={"email": "a1@x.com"})
    assert r.status_code == 409


def test_terminate_blocks_login_then_reactivate(client):
    admin = auth(client, "ADM")
    # A2 can log in initially
    assert client.post("/auth/login", json={"username": "A2", "password": "pw"}).status_code == 200
    # terminate
    r = client.patch(f"/agents/{client._ids['a2']}", headers=admin, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    # login now blocked (account disabled)
    assert client.post("/auth/login", json={"username": "A2", "password": "pw"}).status_code == 403
    # reactivate -> login works again
    client.patch(f"/agents/{client._ids['a2']}", headers=admin, json={"is_active": True})
    assert client.post("/auth/login", json={"username": "A2", "password": "pw"}).status_code == 200


def test_non_admin_cannot_edit_agents(client):
    agent = auth(client, "A2")
    assert client.patch(f"/agents/{client._ids['a1']}", headers=agent,
                        json={"name": "hax"}).status_code == 403
