"""
Case (sales pipeline) access model: agents self-serve the cases they're assigned
to; managers view *and edit* their downlines' cases via the visibility layer;
admins do everything.
"""
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

    def mk(code, level, role, upline=None):
        a = Agent(code=code, name=code, email=f"{code}@x.com", level=level, role=role,
                  upline_id=(upline.id if upline else None), password_hash=hash_password("pw"))
        s.add(a); s.flush()
        return a

    adm = mk("ADM", 1, Role.ADMIN)
    top = mk("TOP", 1, Role.MANAGER)
    ax = mk("AX", 2, Role.AGENT, top)
    ay = mk("AY", 2, Role.AGENT, top)
    other = mk("OTH", 1, Role.AGENT)  # unrelated agent, outside TOP's subtree
    s.commit()
    ids = {"adm": adm.id, "top": top.id, "ax": ax.id, "ay": ay.id, "other": other.id}
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


def mk_case(tc, headers, lead_id, **kw):
    payload = {"prospect_name": "P", "lead_agent_id": lead_id}
    payload.update(kw)
    return tc.post("/cases", headers=headers, json=payload)


def test_agent_creates_and_sees_own_case(client):
    ids = client._ids
    ax = auth(client, "AX")
    r = mk_case(client, ax, ids["ax"])
    assert r.status_code == 200, r.text
    case = r.json()
    assert case["stage"] == "lead" and case["outcome"] == "open"
    rows = client.get("/cases", headers=ax).json()
    assert any(c["id"] == case["id"] for c in rows)


def test_agent_cannot_create_case_for_others(client):
    ids = client._ids
    ax = auth(client, "AX")
    # AX assigns only AY (AX not on the case) -> 403.
    assert mk_case(client, ax, ids["ay"]).status_code == 403


def test_peer_agent_cannot_see_or_edit(client):
    ids = client._ids
    ax, ay = auth(client, "AX"), auth(client, "AY")
    case = mk_case(client, ax, ids["ax"]).json()
    assert all(c["id"] != case["id"] for c in client.get("/cases", headers=ay).json())
    assert client.patch(f"/cases/{case['id']}", headers=ay, json={"stage": "m1"}).status_code == 403


def test_manager_sees_and_edits_downline_case(client):
    ids = client._ids
    ax, top = auth(client, "AX"), auth(client, "TOP")
    case = mk_case(client, ax, ids["ax"]).json()
    rows = client.get("/cases", headers=top).json()
    assert any(c["id"] == case["id"] for c in rows)          # manager VIEWS downline case
    r = client.patch(f"/cases/{case['id']}", headers=top, json={"stage": "m1"})
    assert r.status_code == 200 and r.json()["stage"] == "m1"  # ... and may edit it


def test_manager_cannot_edit_case_outside_subtree(client):
    ids = client._ids
    top, other = auth(client, "TOP"), auth(client, "OTH")
    # A case owned by an unrelated agent outside TOP's subtree stays off-limits.
    case = mk_case(client, other, ids["other"]).json()
    assert client.patch(f"/cases/{case['id']}", headers=top,
                        json={"stage": "m1"}).status_code == 403


def test_admin_sees_all_and_can_edit(client):
    ids = client._ids
    ax, adm = auth(client, "AX"), auth(client, "ADM")
    case = mk_case(client, ax, ids["ax"]).json()
    assert any(c["id"] == case["id"] for c in client.get("/cases", headers=adm).json())
    assert client.patch(f"/cases/{case['id']}", headers=adm,
                        json={"stage": "m2"}).status_code == 200


def test_stage_and_outcome_transitions(client):
    ids = client._ids
    ax = auth(client, "AX")
    case = mk_case(client, ax, ids["ax"]).json()
    r = client.patch(f"/cases/{case['id']}", headers=ax, json={"stage": "m2"})
    assert r.status_code == 200 and r.json()["stage"] == "m2"
    r = client.patch(f"/cases/{case['id']}", headers=ax, json={"outcome": "won"})
    assert r.status_code == 200
    assert r.json()["outcome"] == "won" and r.json()["closed_at"] is not None
    # An open-only board no longer shows a won case.
    open_rows = client.get("/cases?outcome=open", headers=ax).json()
    assert all(c["id"] != case["id"] for c in open_rows)


def test_unrelated_agent_isolated(client):
    ids = client._ids
    ax, other = auth(client, "AX"), auth(client, "OTH")
    case = mk_case(client, ax, ids["ax"]).json()
    assert all(c["id"] != case["id"] for c in client.get("/cases", headers=other).json())
