"""
學員 (student) role + 商學院 (bschool) company:
  * code prefix B… -> bschool; any admin may create/see the shared student pool;
  * a student may ONLY read training materials (everything else is 403);
  * training materials are shown to students only when visible to 商學院.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base, Agent, Role
from app.security import hash_password
from app.services import scoping


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    s = Session()
    adm = Agent(code="ADM", name="Admin", email="adm@x.com", level=1, role=Role.ADMIN,
                company="heritree", password_hash=hash_password("pw"))
    s.add(adm); s.commit()
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
    tc._Session = Session
    yield tc
    main.app.dependency_overrides.clear()


def auth(tc, code):
    r = tc.post("/auth/login", json={"username": code, "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def mk_material(tc, headers, **kw):
    payload = {"title": "T", "category": "c"}
    payload.update(kw)
    return tc.post("/training-materials", headers=headers, json=payload)


def create_student(tc, admin, code="B001"):
    return tc.post("/agents", headers=admin, json={
        "code": code, "name": "Stu", "email": f"{code}@x.com", "level": 1,
        "role": "student", "password": "pw"})


# --- company prefix ------------------------------------------------------------

def test_company_for_code_prefixes():
    assert scoping.company_for_code("B001") == "bschool"
    assert scoping.company_for_code("b9") == "bschool"
    assert scoping.company_for_code("cpm1") == "cpm"
    assert scoping.company_for_code("A1") == "heritree"


# --- admin manages the shared 商學院 student pool ------------------------------

def test_admin_creates_student_in_bschool(client):
    adm = auth(client, "ADM")
    r = create_student(client, adm)                       # heritree admin, B-code
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "student" and body["company"] == "bschool"
    # The heritree admin can see the 商學院 student in the roster.
    ids = {a["id"] for a in client.get("/agents", headers=adm).json()}
    assert body["id"] in ids


# --- a student may ONLY read training ------------------------------------------

def test_student_can_read_training_but_nothing_else(client):
    adm = auth(client, "ADM")
    create_student(client, adm)
    stu = auth(client, "B001")
    assert client.get("/auth/me", headers=stu).status_code == 200      # own profile
    assert client.get("/menu-settings", headers=stu).status_code == 200
    assert client.get("/training-materials", headers=stu).status_code == 200
    # Everything else is blocked for a student.
    for path in ("/clients", "/agents", "/cases", "/products"):
        assert client.get(path, headers=stu).status_code == 403, path


def test_training_visibility_for_student(client):
    adm = auth(client, "ADM")
    create_student(client, adm)
    stu = auth(client, "B001")
    mk_material(client, adm, title="ForBschool", companies=["bschool"])
    mk_material(client, adm, title="ForHeritree", companies=["heritree"])
    mk_material(client, adm, title="ForAll")              # companies omitted = all
    titles = {m["title"] for m in client.get("/training-materials", headers=stu).json()}
    assert "ForBschool" in titles
    assert "ForAll" in titles
    assert "ForHeritree" not in titles


def test_bschool_visibility_option_is_accepted(client):
    adm = auth(client, "ADM")
    r = mk_material(client, adm, title="X", companies=["bschool"])
    assert r.status_code == 200
    assert r.json()["companies"] == ["bschool"]           # not stripped by _clean_companies
