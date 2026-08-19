"""
Two-company (Heritree / CPM) isolation. Company is derived from the agent code
prefix ("cpm..." -> cpm, else heritree). Admins are company-scoped; products and
training are shared.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base, Agent, Role, Product, ProductType
from app.security import hash_password


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    s = Session()

    def mk(code, role, level=1, upline=None):
        a = Agent(code=code, name=code, email=f"{code}@x.com", level=level, role=role,
                  company=("cpm" if code.lower().startswith("cpm") else "heritree"),
                  upline_id=(upline.id if upline else None), password_hash=hash_password("pw"))
        s.add(a); s.flush()
        return a

    hadm = mk("A000", Role.ADMIN)
    cadm = mk("cpm000", Role.ADMIN)
    hmgr = mk("A001", Role.MANAGER, level=1)      # heritree L1 manager (upline target)
    hag = mk("A002", Role.AGENT, level=2, upline=hmgr)
    cag = mk("cpm001", Role.AGENT, level=1)
    # a shared product so both companies see the same catalog
    s.add(Product(code="INS-WL", name="WL", type=ProductType.INSURANCE,
                  afyp_conversion=1, base_commission_rate="0.2"))
    s.commit()
    ids = {"hmgr": hmgr.id, "hag": hag.id, "cag": cag.id}
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


def test_company_derived_from_code(client):
    hadm, cadm = auth(client, "A000"), auth(client, "cpm000")
    r = client.post("/agents", headers=hadm, json={"code": "A010", "name": "H", "email": "h10@x.com", "level": 1})
    assert r.status_code == 200 and r.json()["company"] == "heritree"
    r = client.post("/agents", headers=cadm, json={"code": "cpm010", "name": "C", "email": "c10@x.com", "level": 1})
    assert r.status_code == 200 and r.json()["company"] == "cpm"


def test_admin_cannot_create_cross_company_code(client):
    hadm, cadm = auth(client, "A000"), auth(client, "cpm000")
    # Heritree admin may not create a cpm-prefixed agent, and vice versa.
    r = client.post("/agents", headers=hadm, json={"code": "cpm999", "name": "x", "email": "x@x.com", "level": 1})
    assert r.status_code == 400 and r.headers.get("X-Error-Code") == "wrong_company_prefix"
    r = client.post("/agents", headers=cadm, json={"code": "A999", "name": "y", "email": "y@x.com", "level": 1})
    assert r.status_code == 400


def test_cross_company_upline_rejected(client):
    cadm = auth(client, "cpm000")
    # A cpm agent cannot sit under a heritree upline (would leak the subtree).
    r = client.post("/agents", headers=cadm, json={
        "code": "cpm050", "name": "z", "email": "z@x.com", "level": 2,
        "upline_id": client._ids["hmgr"]})
    assert r.status_code == 422


def test_admin_sees_only_own_company_agents(client):
    hadm, cadm = auth(client, "A000"), auth(client, "cpm000")
    hcodes = {a["code"] for a in client.get("/agents", headers=hadm).json()}
    ccodes = {a["code"] for a in client.get("/agents", headers=cadm).json()}
    assert "A002" in hcodes and not any(c.startswith("cpm") for c in hcodes)
    assert "cpm001" in ccodes and not any(not c.startswith("cpm") for c in ccodes)


def test_directory_is_company_scoped(client):
    hag, cag = auth(client, "A002"), auth(client, "cpm001")
    hdir = {a["code"] for a in client.get("/agents/directory", headers=hag).json()}
    cdir = {a["code"] for a in client.get("/agents/directory", headers=cag).json()}
    assert hdir and all(not c.startswith("cpm") for c in hdir)
    assert cdir and all(c.startswith("cpm") for c in cdir)


def test_admin_cannot_edit_other_company_agent(client):
    hadm = auth(client, "A000")
    r = client.patch(f"/agents/{client._ids['cag']}", headers=hadm, json={"name": "hacked"})
    assert r.status_code == 403


def test_title_targets_per_company(client):
    hadm, cadm = auth(client, "A000"), auth(client, "cpm000")
    client.put("/title-targets/business_manager", headers=hadm, json={"target_afyp": 5000000})
    client.put("/title-targets/business_manager", headers=cadm, json={"target_afyp": 9000000})
    hval = {t["title"]: t["target_afyp"] for t in client.get("/title-targets", headers=hadm).json()}
    cval = {t["title"]: t["target_afyp"] for t in client.get("/title-targets", headers=cadm).json()}
    assert hval["business_manager"] == 5000000 and cval["business_manager"] == 9000000


def test_override_rules_per_company(client):
    hadm, cadm = auth(client, "A000"), auth(client, "cpm000")
    client.post("/override-rules", headers=hadm, json={
        "product_type": "insurance", "level_gap": 1, "override_rate": 0.1})
    assert len(client.get("/override-rules", headers=hadm).json()) == 1
    assert client.get("/override-rules", headers=cadm).json() == []  # not visible to CPM


def test_products_are_shared(client):
    hag, cag = auth(client, "A002"), auth(client, "cpm001")
    hp = {p["code"] for p in client.get("/products", headers=hag).json()}
    cp = {p["code"] for p in client.get("/products", headers=cag).json()}
    assert hp == cp and "INS-WL" in hp
