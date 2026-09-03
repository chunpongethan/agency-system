"""
Admin may move an agent's upline. Reparenting recomputes the agent's depth and
shifts its whole subtree; cycles (self / own-descendant) are rejected.
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
    mid = mk("MID", 2, Role.MANAGER, top)
    leaf = mk("LEAF", 3, Role.AGENT, mid)
    br = mk("BR", 1, Role.MANAGER)
    brsub = mk("BRSUB", 2, Role.MANAGER, br)
    s.commit()
    ids = {"adm": adm.id, "top": top.id, "mid": mid.id, "leaf": leaf.id,
           "br": br.id, "brsub": brsub.id}
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


def agent(tc, headers, aid):
    return next(a for a in tc.get("/agents", headers=headers).json() if a["id"] == aid)


def test_reparent_relevels_subtree(client):
    ids, adm = client._ids, auth(client, "ADM")
    # Move MID (L2, child LEAF L3) under BRSUB (L2) → MID becomes L3, LEAF becomes L4.
    r = client.patch(f"/agents/{ids['mid']}", headers=adm, json={"upline_id": ids["brsub"]})
    assert r.status_code == 200, r.text
    assert r.json()["upline_id"] == ids["brsub"] and r.json()["level"] == 3
    assert agent(client, adm, ids["leaf"])["level"] == 4        # subtree shifted +1


def test_reparent_to_root(client):
    ids, adm = client._ids, auth(client, "ADM")
    # Detach MID to a root (L1); LEAF follows from L3 to L2.
    r = client.patch(f"/agents/{ids['mid']}", headers=adm, json={"upline_id": None})
    assert r.status_code == 200, r.text
    assert r.json()["upline_id"] is None and r.json()["level"] == 1
    assert agent(client, adm, ids["leaf"])["level"] == 2


def test_cycle_via_descendant_rejected(client):
    ids, adm = client._ids, auth(client, "ADM")
    # TOP under LEAF (LEAF is TOP's descendant) → cycle.
    r = client.patch(f"/agents/{ids['top']}", headers=adm, json={"upline_id": ids["leaf"]})
    assert r.status_code == 422 and r.headers.get("X-Error-Code") == "invalid_upline"


def test_self_as_upline_rejected(client):
    ids, adm = client._ids, auth(client, "ADM")
    r = client.patch(f"/agents/{ids['mid']}", headers=adm, json={"upline_id": ids["mid"]})
    assert r.status_code == 422 and r.headers.get("X-Error-Code") == "invalid_upline"


def test_reparent_requires_admin(client):
    ids = client._ids
    r = client.patch(f"/agents/{ids['leaf']}", headers=auth(client, "LEAF"),
                     json={"upline_id": ids["top"]})
    assert r.status_code == 403


def test_edit_without_upline_leaves_tree_untouched(client):
    ids, adm = client._ids, auth(client, "ADM")
    # A plain rename must not disturb levels/upline (upline_id not in payload).
    r = client.patch(f"/agents/{ids['mid']}", headers=adm, json={"name": "Renamed"})
    assert r.status_code == 200
    assert agent(client, adm, ids["mid"])["level"] == 2
    assert agent(client, adm, ids["leaf"])["level"] == 3
