"""
建議書 generation: agents queue requests, a token-authenticated worker claims them and
uploads the PDF, the backend writes an AI analysis; admins can upload a PDF by hand.
"""
from datetime import timedelta

import pytest

from app.models.models import ProposalRequest, KbUsage, now_utc
from tests.test_training_materials import client, auth  # noqa: F401

TOKEN = "test-worker-token"
W = {"X-Worker-Token": TOKEN}
PDF = b"%PDF-1.4 fake proposal"
BODY = {"age": 30, "gender": "F", "product": "飛揚·88", "premium": 50000,
        "term_years": 2, "currency": "USD"}


@pytest.fixture(autouse=True)
def _env(client, monkeypatch):
    import app.main as main
    monkeypatch.setenv("PROPOSAL_WORKER_TOKEN", TOKEN)
    # Background analysis opens its own session — point it at the test DB.
    monkeypatch.setattr(main, "SessionLocal", client._Session)
    monkeypatch.setattr(main.kb_ai, "ai_enabled", lambda: True)
    monkeypatch.setattr(main.proposal_ai, "analyze", lambda pdf, text, inputs: {
        "text": "## 計劃摘要\nok", "usage": {"model": "claude-sonnet-5-5",
                                         "input_tokens": 10, "output_tokens": 5}})


def _claim(client, wid="w1"):
    return client.post("/worker/proposals/claim", headers=W, json={"worker_id": wid})


def test_create_validate_and_visibility(client):
    adm, ax, cpm = auth(client, "ADM"), auth(client, "AX"), auth(client, "cpm1")
    r = client.post("/proposals", headers=ax, json=BODY)
    assert r.status_code == 201 and r.json()["status"] == "queued" and r.json()["queue_position"] == 1
    pid = r.json()["id"]
    assert client.post("/proposals", headers=ax, json={**BODY, "gender": "X"}).status_code == 422
    assert client.post("/proposals", headers=ax, json={**BODY, "currency": "EUR"}).status_code == 422
    # owner and admin see it; another agent doesn't
    assert [p["id"] for p in client.get("/proposals", headers=ax).json()] == [pid]
    assert client.get("/proposals", headers=cpm).json() == []
    assert client.get(f"/proposals/{pid}", headers=cpm).status_code == 404
    assert client.get(f"/proposals/{pid}", headers=adm).status_code == 200


def test_worker_auth_required(client):
    assert client.post("/worker/proposals/claim", json={"worker_id": "w"}).status_code == 403
    assert client.post("/worker/proposals/claim", headers={"X-Worker-Token": "nope"},
                       json={"worker_id": "w"}).status_code == 403
    assert client.post("/worker/heartbeat", headers=W, json={"worker_id": "w1"}).status_code == 200
    assert client.get("/proposals/worker-status", headers=auth(client, "AX")).json()["online"] is True


def test_claim_result_and_analysis(client):
    ax = auth(client, "AX")
    pid = client.post("/proposals", headers=ax, json=BODY).json()["id"]
    job = _claim(client).json()
    assert job["id"] == pid and job["inputs"]["product"] == "飛揚·88"
    assert "client_id" not in job["inputs"]                 # nothing identifying goes to the worker
    assert _claim(client, "w2").status_code == 204          # only one job, already claimed
    # a different worker can't post the result
    assert client.post(f"/worker/proposals/{pid}/result", headers=W, data={"worker_id": "w2"},
                       files={"file": ("p.pdf", PDF, "application/pdf")}).status_code == 409
    r = client.post(f"/worker/proposals/{pid}/result", headers=W, data={"worker_id": "w1"},
                    files={"file": ("飛揚88.pdf", PDF, "application/pdf")})
    assert r.status_code == 200
    p = client.get(f"/proposals/{pid}", headers=ax).json()
    assert p["status"] == "done" and p["has_pdf"] and p["analysis_status"] == "done"
    assert p["analysis"].startswith("## 計劃摘要")
    pdf = client.get(f"/proposals/{pid}/pdf", headers=ax)
    assert pdf.status_code == 200 and pdf.content == PDF
    s = client._Session()
    assert s.query(KbUsage).filter_by(feature="proposal").count() == 1
    s.close()


def test_rejects_non_pdf(client):
    ax = auth(client, "AX")
    pid = client.post("/proposals", headers=ax, json=BODY).json()["id"]
    _claim(client)
    assert client.post(f"/worker/proposals/{pid}/result", headers=W, data={"worker_id": "w1"},
                       files={"file": ("x.pdf", b"hello", "application/pdf")}).status_code == 400


def test_fail_requeues_then_fails(client):
    ax = auth(client, "AX")
    pid = client.post("/proposals", headers=ax, json=BODY).json()["id"]
    for attempt in range(1, 4):
        assert _claim(client).json()["attempt"] == attempt
        st = client.post(f"/worker/proposals/{pid}/fail", headers=W,
                         data={"error": "button not found", "worker_id": "w1"},
                         files={"screenshot": ("s.png", b"\x89PNG", "image/png")}).json()["status"]
        assert st == ("queued" if attempt < 3 else "failed")
    p = client.get(f"/proposals/{pid}", headers=ax).json()
    assert p["status"] == "failed" and p["error"] == "button not found" and p["has_screenshot"]
    # retry resets attempts
    assert client.post(f"/proposals/{pid}/retry", headers=ax).json()["status"] == "queued"
    assert _claim(client).json()["attempt"] == 1


def test_stale_claim_requeued(client):
    ax = auth(client, "AX")
    pid = client.post("/proposals", headers=ax, json=BODY).json()["id"]
    _claim(client)
    s = client._Session()
    r = s.get(ProposalRequest, pid)
    r.claimed_at = now_utc() - timedelta(minutes=30)
    s.commit(); s.close()
    assert _claim(client, "w2").json()["id"] == pid        # stale claim went back to the queue


def test_cancel_and_admin_upload(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    pid = client.post("/proposals", headers=ax, json=BODY).json()["id"]
    # agents can't upload by hand; admin can
    assert client.post(f"/proposals/{pid}/upload", headers=ax,
                       files={"file": ("p.pdf", PDF, "application/pdf")}).status_code == 403
    r = client.post(f"/proposals/{pid}/upload", headers=adm,
                    files={"file": ("p.pdf", PDF, "application/pdf")})
    assert r.status_code == 200 and r.json()["status"] == "done"
    pid2 = client.post("/proposals", headers=ax, json=BODY).json()["id"]
    assert client.post(f"/proposals/{pid2}/cancel", headers=ax).json()["status"] == "cancelled"
    assert _claim(client).status_code == 204               # cancelled jobs aren't handed out


def test_analysis_skipped_without_ai(client, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main.kb_ai, "ai_enabled", lambda: False)
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    pid = client.post("/proposals", headers=ax, json=BODY).json()["id"]
    client.post(f"/proposals/{pid}/upload", headers=adm, files={"file": ("p.pdf", PDF, "application/pdf")})
    p = client.get(f"/proposals/{pid}", headers=ax).json()
    assert p["status"] == "done" and p["analysis_status"] == "skipped"
