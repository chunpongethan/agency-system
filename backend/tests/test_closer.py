"""
Closer eligibility + case assignment scope:
  * agents carry an is_closer flag (editable by admin);
  * /agents/assignable is scoped (agent → self; manager → self+downline; admin → all);
  * the Closer pool is company-wide (any is_closer agent);
  * case Lead/SDR must be in the caller's scope; the Closer must be is_closer.
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

    def mk(code, level, role, upline=None, is_closer=False):
        a = Agent(code=code, name=code, email=f"{code}@x.com", level=level, role=role,
                  upline_id=(upline.id if upline else None), is_closer=is_closer,
                  password_hash=hash_password("pw"))
        s.add(a); s.flush()
        return a

    adm = mk("ADM", 1, Role.ADMIN)
    mgr = mk("MGR", 1, Role.MANAGER)
    a1 = mk("A1", 2, Role.AGENT, mgr)
    a2 = mk("A2", 2, Role.AGENT, mgr)
    cl = mk("CL", 1, Role.AGENT, is_closer=True)   # company-wide closer, outside MGR's tree
    out = mk("OUT", 1, Role.AGENT)                  # unrelated agent
    s.commit()
    ids = {"adm": adm.id, "mgr": mgr.id, "a1": a1.id, "a2": a2.id, "cl": cl.id, "out": out.id}
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


# --- is_closer flag round-trip -------------------------------------------------

def test_is_closer_roundtrips_through_agent_api(client):
    adm = auth(client, "ADM")
    a1 = client._ids["a1"]
    assert next(a for a in client.get("/agents", headers=adm).json() if a["id"] == a1)["is_closer"] is False
    r = client.patch(f"/agents/{a1}", headers=adm, json={"is_closer": True})
    assert r.status_code == 200 and r.json()["is_closer"] is True


def test_create_agent_with_is_closer(client):
    adm = auth(client, "ADM")
    r = client.post("/agents", headers=adm, json={
        "code": "A9", "name": "Niner", "email": "a9@x.com", "level": 1,
        "role": "agent", "is_closer": True, "password": "pw"})
    assert r.status_code == 200, r.text
    assert r.json()["is_closer"] is True


# --- /agents/assignable scoping + /directory closer flag -----------------------

def test_assignable_agent_sees_only_self(client):
    ids = client._ids
    got = {a["id"] for a in client.get("/agents/assignable", headers=auth(client, "A1")).json()}
    assert got == {ids["a1"]}


def test_assignable_manager_sees_self_and_downline(client):
    ids = client._ids
    got = {a["id"] for a in client.get("/agents/assignable", headers=auth(client, "MGR")).json()}
    assert got == {ids["mgr"], ids["a1"], ids["a2"]}   # not CL/OUT (outside subtree)


def test_assignable_admin_sees_all_non_admin(client):
    ids = client._ids
    got = {a["id"] for a in client.get("/agents/assignable", headers=auth(client, "ADM")).json()}
    assert got == {ids["mgr"], ids["a1"], ids["a2"], ids["cl"], ids["out"]}   # no admin


def test_directory_exposes_is_closer(client):
    rows = client.get("/agents/directory", headers=auth(client, "A1")).json()
    closer = next(a for a in rows if a["id"] == client._ids["cl"])
    assert closer["is_closer"] is True
    assert all("is_closer" in a for a in rows)


# --- Case closer eligibility ---------------------------------------------------

def test_case_closer_must_be_is_closer(client):
    ids = client._ids
    a1 = auth(client, "A1")
    # A1 (agent) may pick the company-wide closer CL even though CL is outside A1's scope.
    ok = mk_case(client, a1, ids["a1"], closer_agent_id=ids["cl"])
    assert ok.status_code == 200, ok.text
    # A non-closer agent may not be the closer.
    bad = mk_case(client, a1, ids["a1"], closer_agent_id=ids["a2"])
    assert bad.status_code == 400
    assert bad.headers.get("X-Error-Code") == "not_closer"


def test_case_lead_scope_agent_self_only(client):
    ids = client._ids
    a1 = auth(client, "A1")
    # An agent may not assign another agent as Lead.
    r = mk_case(client, a1, ids["a2"])
    assert r.status_code == 403 and r.headers.get("X-Error-Code") == "not_assignable"


def test_case_lead_scope_manager_downline_ok(client):
    ids = client._ids
    mgr = auth(client, "MGR")
    # A manager may assign a downline as Lead without being assigned themselves.
    r = mk_case(client, mgr, ids["a1"], sdr_agent_id=ids["a2"])
    assert r.status_code == 200, r.text


def test_case_sdr_outside_scope_rejected(client):
    ids = client._ids
    mgr = auth(client, "MGR")
    # OUT is outside the manager's subtree → not assignable as SDR.
    r = mk_case(client, mgr, ids["a1"], sdr_agent_id=ids["out"])
    assert r.status_code == 403 and r.headers.get("X-Error-Code") == "not_assignable"


def test_update_case_closer_validation(client):
    ids = client._ids
    a1 = auth(client, "A1")
    case = mk_case(client, a1, ids["a1"]).json()
    bad = client.patch(f"/cases/{case['id']}", headers=a1, json={"closer_agent_id": ids["a2"]})
    assert bad.status_code == 400 and bad.headers.get("X-Error-Code") == "not_closer"
    ok = client.patch(f"/cases/{case['id']}", headers=a1, json={"closer_agent_id": ids["cl"]})
    assert ok.status_code == 200 and ok.json()["closer_agent_id"] == ids["cl"]
