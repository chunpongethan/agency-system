"""AI Knowledge Base: article/document CRUD (admin-gated), document text
extraction, keyword search + training-material company visibility, and the
/kb/ask endpoint (AI call monkeypatched — no real Anthropic request)."""
import io
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base, Agent, Role, TrainingMaterial, Product, ProductType
from app.security import hash_password

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    s = Session()

    def mk(code, role, company="heritree"):
        a = Agent(code=code, name=code, email=f"{code}@x.com", level=1, role=role,
                  company=company, password_hash=hash_password("pw"))
        s.add(a); s.flush(); return a

    mk("ADM", Role.ADMIN)
    mk("AX", Role.AGENT, "heritree")
    mk("cpm1", Role.AGENT, "cpm")
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
    tc._Session = Session
    yield tc
    main.app.dependency_overrides.clear()


def auth(tc, code):
    r = tc.post("/auth/login", json={"username": code, "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _real_pdf(text: str) -> bytes:
    try:
        import pymupdf as fitz
    except Exception:
        fitz = pytest.importorskip("fitz")
    doc = fitz.open(); page = doc.new_page(); page.insert_text((72, 72), text)
    return doc.tobytes()


# --- status ------------------------------------------------------------------
def test_status_ai_disabled_without_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.get("/kb/status", headers=auth(client, "AX"))
    assert r.status_code == 200 and r.json()["ai_enabled"] is False


# --- articles ----------------------------------------------------------------
def test_article_crud_admin_only(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    # agent cannot create
    assert client.post("/kb/articles", headers=ax,
                       json={"title": "X", "body": "<p>hi</p>"}).status_code == 403
    # admin creates; body sanitised
    r = client.post("/kb/articles", headers=adm, json={
        "title": "退保費用 Surrender charge", "category": "FAQ",
        "body": "<p>退保會有費用</p><script>alert(1)</script>"})
    assert r.status_code == 200, r.text
    art = r.json()
    assert "<script>" not in art["body"] and "退保" in art["body"]
    aid = art["id"]
    # everyone sees active articles
    assert any(a["id"] == aid for a in client.get("/kb/articles", headers=ax).json())
    # deactivate -> hidden from agents, still visible to admin
    client.patch(f"/kb/articles/{aid}", headers=adm, json={"is_active": False})
    assert all(a["id"] != aid for a in client.get("/kb/articles", headers=ax).json())
    assert any(a["id"] == aid for a in client.get("/kb/articles", headers=adm).json())
    # delete
    assert client.delete(f"/kb/articles/{aid}", headers=adm).status_code == 200


# --- documents ---------------------------------------------------------------
def test_document_upload_extracts_text_and_serves(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    pdf = _real_pdf("underwriting guideline 核保指引")
    up = client.post("/kb/documents", headers=adm,
                     data={"title": "核保指引"},
                     files={"file": ("guide.pdf", pdf, "application/pdf")})
    assert up.status_code == 200, up.text
    did = up.json()["id"]
    # agent can list + fetch
    assert any(d["id"] == did for d in client.get("/kb/documents", headers=ax).json())
    dl = client.get(f"/kb/documents/{did}", headers=ax)
    assert dl.status_code == 200 and dl.content[:4] == b"%PDF"
    # extraction fed search
    hits = client.get("/kb/search", headers=ax, params={"q": "核保指引"}).json()
    assert any(h["source_type"] == "document" and h["ref_id"] == did for h in hits)
    # admin-only delete
    assert client.delete(f"/kb/documents/{did}", headers=auth(client, "AX")).status_code == 403
    assert client.delete(f"/kb/documents/{did}", headers=adm).status_code == 200


def test_document_rejects_non_admin_upload(client):
    ax = auth(client, "AX")
    r = client.post("/kb/documents", headers=ax, data={"title": "x"},
                    files={"file": ("a.pdf", b"%PDF x", "application/pdf")})
    assert r.status_code == 403


# --- search + training visibility --------------------------------------------
def test_search_respects_training_company_visibility(client):
    with client._Session() as db:
        db.add(TrainingMaterial(title="Heritree Only 分紅險策略", category="策略",
                                description="<p>heritree secret 分紅險</p>",
                                companies=["heritree"]))
        db.commit()
    # heritree agent finds it; cpm agent does not
    q = {"q": "分紅險"}
    h_hits = client.get("/kb/search", headers=auth(client, "AX"), params=q).json()
    c_hits = client.get("/kb/search", headers=auth(client, "cpm1"), params=q).json()
    assert any(h["source_type"] == "training" for h in h_hits)
    assert all(h["source_type"] != "training" for h in c_hits)


def test_search_includes_products(client):
    with client._Session() as db:
        db.add(Product(code="INS-CC-1", name="CriticalCare 危疾保障",
                       type=list(ProductType)[0]))
        db.commit()
    hits = client.get("/kb/search", headers=auth(client, "AX"),
                      params={"q": "CriticalCare"}).json()
    assert any(h["source_type"] == "product" for h in hits)


def test_search_empty_query_returns_empty(client):
    assert client.get("/kb/search", headers=auth(client, "AX"), params={"q": ""}).json() == []


# --- ask (AI monkeypatched) --------------------------------------------------
def test_ask_disabled_without_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/kb/ask", headers=auth(client, "AX"), json={"question": "退保費用?"})
    assert r.status_code == 503
    assert r.headers.get("X-Error-Code") == "ai_unavailable"


def test_ask_returns_answer_and_sources(client, monkeypatch):
    from app.services import kb_ai
    monkeypatch.setattr(kb_ai, "ai_enabled", lambda: True)

    captured = {}
    def fake_answer(question, history, chunks):
        captured["q"] = question
        captured["n_chunks"] = len(chunks)
        return {"text": "退保首年會扣費。",
                "sources": [{"n": 1, "title": "退保費用", "source_type": "article",
                             "link": "#/knowledge-base", "ref_id": 1}]}
    monkeypatch.setattr(kb_ai, "answer", fake_answer)

    # seed an article so retrieval has something to pass through
    adm = auth(client, "ADM")
    client.post("/kb/articles", headers=adm, json={
        "title": "退保費用", "body": "<p>退保 surrender charge 首年扣費</p>"})

    r = client.post("/kb/ask", headers=auth(client, "AX"),
                    json={"question": "退保有費用嗎?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == "退保首年會扣費。"
    assert body["sources"][0]["source_type"] == "article"
    assert captured["q"] == "退保有費用嗎?"


def test_ask_validates_question(client, monkeypatch):
    from app.services import kb_ai
    monkeypatch.setattr(kb_ai, "ai_enabled", lambda: True)
    assert client.post("/kb/ask", headers=auth(client, "AX"),
                       json={"question": "   "}).status_code == 422
