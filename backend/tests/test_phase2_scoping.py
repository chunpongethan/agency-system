"""
Phase 2 tests: row-level scoping helper (agent isolation, manager subtree,
admin-all) and JWT auth + endpoint enforcement.

Tree used here (two lines under one L1 admin):

    A1 (admin, L1)
    ├── A2 (manager, L2)
    │   └── A3 (manager, L3)
    │       └── A4 (agent, L4)
    └── B2 (manager, L2)
        └── B3 (manager, L3)
            └── B4 (agent, L4)
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import (
    Base, Agent, AgentLevel, Role, Client,
)
from app.services import scoping
from app.security import hash_password


def _build_tree(session):
    def mk(code, level, role, upline=None):
        a = Agent(code=code, name=code, email=f"{code}@x.com", level=level, role=role,
                  upline_id=(upline.id if upline else None),
                  password_hash=hash_password("pw"))
        session.add(a); session.flush()
        return a

    a1 = mk("A1", AgentLevel.L1, Role.ADMIN)
    a2 = mk("A2", AgentLevel.L2, Role.MANAGER, a1)
    a3 = mk("A3", AgentLevel.L3, Role.MANAGER, a2)
    a4 = mk("A4", AgentLevel.L4, Role.AGENT, a3)
    b2 = mk("B2", AgentLevel.L2, Role.MANAGER, a1)
    b3 = mk("B3", AgentLevel.L3, Role.MANAGER, b2)
    b4 = mk("B4", AgentLevel.L4, Role.AGENT, b3)
    session.commit()
    return {"a1": a1, "a2": a2, "a3": a3, "a4": a4, "b2": b2, "b3": b3, "b4": b4}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session._tree = _build_tree(session)
    yield session
    session.close()


# --------------------------------------------------------------------------- #
# Scoping helper in isolation
# --------------------------------------------------------------------------- #
def test_scope_agent_sees_only_self(db):
    t = db._tree
    assert scoping.visible_agent_ids(db, t["a4"]) == {t["a4"].id}


def test_scope_manager_sees_subtree(db):
    t = db._tree
    ids = scoping.visible_agent_ids(db, t["a2"])
    assert ids == {t["a2"].id, t["a3"].id, t["a4"].id}
    # does NOT include the sibling B-line
    assert t["b3"].id not in ids and t["b4"].id not in ids


def test_scope_mid_manager_subtree(db):
    t = db._tree
    ids = scoping.visible_agent_ids(db, t["a3"])
    assert ids == {t["a3"].id, t["a4"].id}


def test_scope_admin_sees_all(db):
    t = db._tree
    ids = scoping.visible_agent_ids(db, t["a1"])
    assert ids == {a.id for a in t.values()}


def test_scope_assert_visible_raises(db):
    t = db._tree
    with pytest.raises(PermissionError):
        scoping.assert_visible(db, t["a4"], t["b4"].id)
    # in-scope does not raise
    scoping.assert_visible(db, t["a2"], t["a4"].id)


# --------------------------------------------------------------------------- #
# Auth + endpoint enforcement (via TestClient with a shared DB)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False)

    from app import main
    tree_session = TestingSession()
    tree = _build_tree(tree_session)
    # Give A4's line a client so we can test cross-line isolation.
    ca = Client(ref="CA", name="A-client", agent_id=tree["a4"].id)
    cb = Client(ref="CB", name="B-client", agent_id=tree["b4"].id)
    tree_session.add_all([ca, cb]); tree_session.commit()
    ids = {k: v.id for k, v in tree.items()}
    client_ids = {"ca": ca.id, "cb": cb.id}
    tree_session.close()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[main.get_db] = override_get_db
    tc = TestClient(main.app)
    tc._ids = ids
    tc._clients = client_ids
    yield tc
    main.app.dependency_overrides.clear()


def _token(tc, code):
    r = tc.post("/auth/login", json={"username": code, "password": "pw"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tc, code):
    return {"Authorization": f"Bearer {_token(tc, code)}"}


def test_auth_login_and_me(client):
    r = client.get("/auth/me", headers=_auth(client, "A4"))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "A4" and body["role"] == "agent"


def test_auth_bad_password_rejected(client):
    r = client.post("/auth/login", json={"username": "A4", "password": "wrong"})
    assert r.status_code == 401


def test_auth_missing_token_rejected(client):
    r = client.get("/auth/me")
    assert r.status_code in (401, 403)


def test_scope_agent_cannot_see_other_line_client(client):
    # A4 requesting B4's client -> 403, not empty.
    cb = client._clients["cb"]
    r = client.get(f"/clients/{cb}", headers=_auth(client, "A4"))
    assert r.status_code == 403


def test_scope_manager_cannot_see_downline_client(client):
    # Clients are owner-only: even a manager may NOT read a downline's client.
    ca = client._clients["ca"]  # owned by A4, in A2's subtree
    r = client.get(f"/clients/{ca}", headers=_auth(client, "A2"))
    assert r.status_code == 403
    cb = client._clients["cb"]
    r = client.get(f"/clients/{cb}", headers=_auth(client, "A2"))
    assert r.status_code == 403


def test_scope_admin_can_read_clients(client):
    # Admin is the transaction operator and may READ any client (to book for them).
    cb = client._clients["cb"]
    r = client.get(f"/clients/{cb}", headers=_auth(client, "A1"))
    assert r.status_code == 200
    ca = client._clients["ca"]
    r = client.get(f"/clients/{ca}", headers=_auth(client, "A1"))
    assert r.status_code == 200


def test_owner_can_see_own_client(client):
    ca = client._clients["ca"]  # owned by A4
    r = client.get(f"/clients/{ca}", headers=_auth(client, "A4"))
    assert r.status_code == 200


def test_scope_write_out_of_scope_rejected(client):
    # A4 tries to create a client under B4 -> 403.
    b4 = client._ids["b4"]
    r = client.post("/clients", headers=_auth(client, "A4"),
                    json={"ref": "X1", "name": "hack", "agent_id": b4})
    assert r.status_code == 403


def test_scope_write_in_scope_ok(client):
    a4 = client._ids["a4"]
    r = client.post("/clients", headers=_auth(client, "A4"),
                    json={"ref": "X2", "name": "mine", "agent_id": a4})
    assert r.status_code == 200


def test_admin_only_product_creation(client):
    payload = {"code": "PZ", "name": "P", "type": "insurance",
               "base_commission_rate": "0.05"}
    # agent forbidden
    r = client.post("/products", headers=_auth(client, "A4"), json=payload)
    assert r.status_code == 403
    # admin allowed
    r = client.post("/products", headers=_auth(client, "A1"), json=payload)
    assert r.status_code == 200
