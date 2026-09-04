"""
Follow-up reminders: due-case selection, the daily per-agent digest (grouping,
skip-no-wechat, idempotency), and the manual per-case reminder endpoint.
The WeCom service is always monkeypatched — no real WeChat calls.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base, Agent, Role, Case, CaseOutcome, PipelineStage
from app.security import hash_password

TODAY = date(2026, 9, 2)


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    s = Session()

    def mk(code, role, wecom=None, is_closer=False, upline=None):
        a = Agent(code=code, name=code, email=f"{code}@x.com", level=1, role=role,
                  wecom_external_userid=wecom, is_closer=is_closer,
                  upline_id=(upline.id if upline else None), password_hash=hash_password("pw"))
        s.add(a); s.flush()
        return a

    adm = mk("ADM", Role.ADMIN)
    lead = mk("L", Role.AGENT, wecom="wx_L")
    sdr = mk("S", Role.AGENT)                       # no WeChat id
    closer = mk("C", Role.AGENT, wecom="wx_C", is_closer=True)
    outsider = mk("OUT", Role.AGENT)
    s.add_all([adm, lead, sdr, closer, outsider]); s.flush()
    ids = {"adm": adm.id, "lead": lead.id, "sdr": sdr.id, "closer": closer.id, "out": outsider.id}

    def mk_case(ref, deadline=None, urgent=False, outcome=CaseOutcome.OPEN):
        c = Case(ref=ref, prospect_name=ref, lead_agent_id=lead.id, sdr_agent_id=sdr.id,
                 closer_agent_id=closer.id, follow_up=f"do {ref}", follow_up_deadline=deadline,
                 follow_up_urgent=urgent, stage=PipelineStage.LEAD, outcome=outcome)
        s.add(c); s.flush()
        return c.id

    caseids = {
        "overdue": mk_case("OVERDUE", TODAY - timedelta(days=1)),
        "soon": mk_case("SOON", TODAY + timedelta(days=2)),
        "far": mk_case("FAR", TODAY + timedelta(days=10)),
        "urgent": mk_case("URGENT", None, urgent=True),
        "closed": mk_case("CLOSED", TODAY - timedelta(days=1), outcome=CaseOutcome.WON),
    }
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
    tc._ids = ids; tc._caseids = caseids; tc._Session = Session
    yield tc
    main.app.dependency_overrides.clear()


def auth(tc, code):
    r = tc.post("/auth/login", json={"username": code, "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _enable(monkeypatch, sent):
    from app.services import wecom
    monkeypatch.setattr(wecom, "_enabled", lambda: True)
    def fake(ext_ids, content):
        sent.append((list(ext_ids), content))
        return {"errcode": 0, "msgid": "M"}
    monkeypatch.setattr(wecom, "send_text", fake)


def test_due_cases_selection(client):
    from app.services import reminders
    db = client._Session()
    try:
        refs = {c.ref for c in reminders.due_cases(db, TODAY)}
    finally:
        db.close()
    assert "OVERDUE" in refs and "SOON" in refs and "URGENT" in refs
    assert "FAR" not in refs      # deadline beyond the 3-day window
    assert "CLOSED" not in refs   # not open


def test_daily_digest_groups_and_skips_and_is_idempotent(client, monkeypatch):
    from app.services import reminders
    sent = []
    _enable(monkeypatch, sent)
    db = client._Session()
    try:
        res = reminders.run_daily_reminders(db, today=TODAY)
        assert res["status"] == "sent"
        # Lead + Closer have WeChat ids and are notified; SDR is skipped.
        assert set(res["agents_notified"]) == {client._ids["lead"], client._ids["closer"]}
        assert client._ids["sdr"] in res["skipped_no_wechat"]
        # One digest per notified agent (2 sends), each to a single external id.
        assert len(sent) == 2 and all(len(ext) == 1 for ext, _ in sent)
        # Second run the same day is a no-op (idempotent).
        again = reminders.run_daily_reminders(db, today=TODAY)
        assert again["status"] == "already_ran"
        assert len(sent) == 2
        # Force re-runs.
        forced = reminders.run_daily_reminders(db, today=TODAY, force=True)
        assert forced["status"] == "sent" and len(sent) == 4
    finally:
        db.close()


def test_daily_digest_noop_when_wecom_off(client):
    from app.services import reminders
    db = client._Session()
    try:
        assert reminders.run_daily_reminders(db, today=TODAY)["status"] == "wecom_not_configured"
    finally:
        db.close()


def test_remind_endpoint_member_allowed(client, monkeypatch):
    sent = []
    _enable(monkeypatch, sent)
    cid = client._caseids["soon"]
    r = client.post(f"/cases/{cid}/remind", headers=auth(client, "L"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert client._ids["lead"] in body["sent"] and client._ids["closer"] in body["sent"]
    assert client._ids["sdr"] in body["skipped_no_wechat"]
    # one send to the case's bound recipients
    assert len(sent) == 1 and set(sent[0][0]) == {"wx_L", "wx_C"}


def test_remind_endpoint_outsider_forbidden(client, monkeypatch):
    sent = []
    _enable(monkeypatch, sent)
    cid = client._caseids["soon"]
    assert client.post(f"/cases/{cid}/remind", headers=auth(client, "OUT")).status_code == 403


def test_remind_endpoint_503_when_wecom_off(client):
    cid = client._caseids["soon"]
    r = client.post(f"/cases/{cid}/remind", headers=auth(client, "L"))
    assert r.status_code == 503 and r.headers.get("X-Error-Code") == "wecom_not_configured"


def test_run_endpoint_admin_only(client, monkeypatch):
    sent = []
    _enable(monkeypatch, sent)
    assert client.post("/cases/reminders/run", headers=auth(client, "L")).status_code == 403
    r = client.post("/cases/reminders/run", headers=auth(client, "ADM"))
    assert r.status_code == 200 and r.json()["status"] == "sent"
