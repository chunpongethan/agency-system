"""Global left-menu settings: any agent reads them; only admins write; a PUT
replaces the whole config (keys omitted are dropped)."""
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
    for code, role in [("ADM", Role.ADMIN), ("AX", Role.AGENT)]:
        s.add(Agent(code=code, name=code, email=f"{code}@x.com", level=1, role=role,
                    company="heritree", password_hash=hash_password("pw")))
    s.commit(); s.close()

    from app import main
    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()
    main.app.dependency_overrides[main.get_db] = override_get_db
    tc = TestClient(main.app)
    yield tc
    main.app.dependency_overrides.clear()


def auth(tc, code):
    r = tc.post("/auth/login", json={"username": code, "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_defaults_empty(client):
    assert client.get("/menu-settings", headers=auth(client, "AX")).json() == []


def test_agent_cannot_write(client):
    r = client.put("/menu-settings", headers=auth(client, "AX"),
                   json=[{"key": "leads", "enabled": False, "sort_order": 0}])
    assert r.status_code == 403


def test_admin_sets_and_reads(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    cfg = [
        {"key": "reports", "enabled": True, "sort_order": 0},
        {"key": "leads", "enabled": False, "sort_order": 1, "label": "客戶名單"},
        {"key": "clients", "enabled": True, "sort_order": 2, "label": ""},
    ]
    r = client.put("/menu-settings", headers=adm, json=cfg)
    assert r.status_code == 200
    got = client.get("/menu-settings", headers=ax).json()
    assert [g["key"] for g in got] == ["reports", "leads", "clients"]      # ordered by sort_order
    leads = next(g for g in got if g["key"] == "leads")
    assert leads["enabled"] is False and leads["label"] == "客戶名單"       # label override round-trips
    assert next(g for g in got if g["key"] == "clients")["label"] is None  # blank label -> null


def test_put_replaces_and_drops_missing(client):
    adm = auth(client, "ADM")
    client.put("/menu-settings", headers=adm,
               json=[{"key": "a", "enabled": True, "sort_order": 0},
                     {"key": "b", "enabled": True, "sort_order": 1}])
    # a second PUT without "a" drops it
    client.put("/menu-settings", headers=adm,
               json=[{"key": "b", "enabled": False, "sort_order": 0}])
    got = client.get("/menu-settings", headers=adm).json()
    assert [g["key"] for g in got] == ["b"]
    assert got[0]["enabled"] is False
