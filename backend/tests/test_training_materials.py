"""
Training-materials access model: any authenticated agent may browse and download;
only admins may create / edit / delete / upload. Mirrors the test_cases fixture.
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

    def mk(code, role):
        a = Agent(code=code, name=code, email=f"{code}@x.com", level=1, role=role,
                  password_hash=hash_password("pw"))
        s.add(a); s.flush()
        return a

    adm = mk("ADM", Role.ADMIN)
    ax = mk("AX", Role.AGENT)
    s.commit()
    ids = {"adm": adm.id, "ax": ax.id}
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


def mk_material(tc, headers, **kw):
    payload = {"title": "Onboarding 101", "category": "新人入職"}
    payload.update(kw)
    return tc.post("/training-materials", headers=headers, json=payload)


def test_admin_creates_and_agent_reads(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    r = mk_material(client, adm, link_url="https://example.com/guide.pdf")
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    rows = client.get("/training-materials", headers=ax).json()
    assert any(m["id"] == mid for m in rows)
    assert rows[0]["has_file"] is False


def test_agent_cannot_write(client):
    ax = auth(client, "AX")
    assert mk_material(client, ax).status_code == 403
    # create one as admin, then confirm agent PATCH/DELETE are refused
    adm = auth(client, "ADM")
    mid = mk_material(client, adm).json()["id"]
    assert client.patch(f"/training-materials/{mid}", headers=ax,
                        json={"title": "x"}).status_code == 403
    assert client.delete(f"/training-materials/{mid}", headers=ax).status_code == 403


def test_admin_edit_and_delete(client):
    adm = auth(client, "ADM")
    mid = mk_material(client, adm).json()["id"]
    r = client.patch(f"/training-materials/{mid}", headers=adm,
                     json={"category": "產品知識"})
    assert r.status_code == 200 and r.json()["category"] == "產品知識"
    assert client.delete(f"/training-materials/{mid}", headers=adm).status_code == 200
    assert all(m["id"] != mid for m in client.get("/training-materials", headers=adm).json())


def test_file_upload_download_roundtrip(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]
    blob = b"%PDF-1.4 fake pdf bytes"
    up = client.post(f"/training-materials/{mid}/file", headers=adm,
                     files={"file": ("guide.pdf", blob, "application/pdf")})
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["has_file"] and body["file_name"] == "guide.pdf" and body["file_size"] == len(blob)
    # Any authenticated agent may download; bytes + content-type round-trip.
    dl = client.get(f"/training-materials/{mid}/file", headers=ax)
    assert dl.status_code == 200
    assert dl.content == blob
    assert dl.headers["content-type"].startswith("application/pdf")


def test_agent_cannot_upload_or_delete_file(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]
    up = client.post(f"/training-materials/{mid}/file", headers=ax,
                     files={"file": ("x.pdf", b"data", "application/pdf")})
    assert up.status_code == 403
    assert client.delete(f"/training-materials/{mid}/file", headers=ax).status_code == 403


def test_oversize_upload_rejected(client):
    import app.main as main
    adm = auth(client, "ADM")
    mid = mk_material(client, adm).json()["id"]
    too_big = b"x" * (main.TRAINING_MAX_UPLOAD_MB * 1024 * 1024 + 1)
    r = client.post(f"/training-materials/{mid}/file", headers=adm,
                    files={"file": ("big.bin", too_big, "application/octet-stream")})
    assert r.status_code == 400
    assert r.headers.get("X-Error-Code") == "file_too_large"


def test_remove_file(client):
    adm = auth(client, "ADM")
    mid = mk_material(client, adm).json()["id"]
    client.post(f"/training-materials/{mid}/file", headers=adm,
                files={"file": ("g.pdf", b"data", "application/pdf")})
    r = client.delete(f"/training-materials/{mid}/file", headers=adm)
    assert r.status_code == 200 and r.json()["has_file"] is False
    assert client.get(f"/training-materials/{mid}/file", headers=adm).status_code == 404
