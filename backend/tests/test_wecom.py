"""
Admin → send a WeChat message to agents via the 企業微信「客戶聯繫」bridge.

The WeCom service is always monkeypatched — tests never hit the real WeChat API.
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
    adm = Agent(code="ADM", name="Admin", email="adm@x.com", level=1, role=Role.ADMIN,
                company="heritree", password_hash=hash_password("pw"))
    a1 = Agent(code="A1", name="One", email="a1@x.com", level=1, role=Role.AGENT,
               company="heritree", password_hash=hash_password("pw"))
    a2 = Agent(code="A2", name="Two", email="a2@x.com", level=2, role=Role.AGENT,
               company="heritree", wecom_external_userid="wm_two",
               password_hash=hash_password("pw"))
    cpm1 = Agent(code="cpm1", name="CpmOne", email="c1@x.com", level=1, role=Role.AGENT,
                 company="cpm", wecom_external_userid="wm_cpm",
                 password_hash=hash_password("pw"))
    s.add_all([adm, a1, a2, cpm1]); s.commit()
    ids = {"a1": a1.id, "a2": a2.id, "cpm1": cpm1.id}
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


def _enable(monkeypatch, sent):
    """Enable the bridge and capture the ids/text send_text is called with."""
    from app import main
    monkeypatch.setattr(main.wecom, "_enabled", lambda: True)

    def fake_send(external_userids, content):
        sent["ids"] = list(external_userids)
        sent["text"] = content
        return {"errcode": 0, "msgid": "MSG1"}
    monkeypatch.setattr(main.wecom, "send_text", fake_send)


def test_broadcast_not_configured_returns_503(client, monkeypatch):
    from app import main
    monkeypatch.setattr(main.wecom, "_enabled", lambda: False)
    r = client.post("/agents/wecom/broadcast", headers=auth(client, "ADM"),
                    json={"agent_ids": [client._ids["a2"]], "text": "hi"})
    assert r.status_code == 503
    assert r.headers.get("X-Error-Code") == "wecom_not_configured"


def test_broadcast_admin_only(client, monkeypatch):
    sent = {}
    _enable(monkeypatch, sent)
    r = client.post("/agents/wecom/broadcast", headers=auth(client, "A1"),
                    json={"agent_ids": [client._ids["a2"]], "text": "hi"})
    assert r.status_code == 403


def test_broadcast_sends_and_skips(client, monkeypatch):
    sent = {}
    _enable(monkeypatch, sent)
    a1, a2 = client._ids["a1"], client._ids["a2"]
    r = client.post("/agents/wecom/broadcast", headers=auth(client, "ADM"),
                    json={"agent_ids": [a1, a2], "text": "hello team"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] == [a2]                 # a2 has a bound WeChat id
    assert body["skipped_no_wechat"] == [a1]    # a1 has none
    assert body["msgid"] == "MSG1"
    # send_text got only the bound external id + the message text
    assert sent["ids"] == ["wm_two"]
    assert sent["text"] == "hello team"


def test_broadcast_all_skipped_does_not_call_wecom(client, monkeypatch):
    sent = {}
    _enable(monkeypatch, sent)
    a1 = client._ids["a1"]
    r = client.post("/agents/wecom/broadcast", headers=auth(client, "ADM"),
                    json={"agent_ids": [a1], "text": "hi"})
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] == [] and body["skipped_no_wechat"] == [a1]
    assert body["msgid"] is None
    assert sent == {}                           # send_text never called


def test_broadcast_empty_message_rejected(client, monkeypatch):
    sent = {}
    _enable(monkeypatch, sent)
    r = client.post("/agents/wecom/broadcast", headers=auth(client, "ADM"),
                    json={"agent_ids": [client._ids["a2"]], "text": "   "})
    assert r.status_code == 400
    assert r.headers.get("X-Error-Code") == "empty_message"


def test_broadcast_cross_company_blocked(client, monkeypatch):
    sent = {}
    _enable(monkeypatch, sent)
    # heritree admin may not target a CPM agent.
    r = client.post("/agents/wecom/broadcast", headers=auth(client, "ADM"),
                    json={"agent_ids": [client._ids["cpm1"]], "text": "hi"})
    assert r.status_code == 403
    assert sent == {}


def test_service_send_text_disabled_raises(monkeypatch):
    from app.services import wecom
    monkeypatch.delenv("WECOM_CORP_ID", raising=False)
    with pytest.raises(wecom.WecomError):
        wecom.send_text(["x"], "hi")


def test_service_send_text_builds_single_chat_payload(monkeypatch):
    from app.services import wecom
    monkeypatch.setenv("WECOM_CORP_ID", "corp")
    monkeypatch.setenv("WECOM_CONTACT_SECRET", "sec")
    monkeypatch.setenv("WECOM_SENDER_USERID", "boss")
    captured = {}

    def fake_post(path, json):
        captured["path"] = path
        captured["json"] = json
        return {"errcode": 0, "msgid": "M"}
    monkeypatch.setattr(wecom, "_post", fake_post)

    out = wecom.send_text(["e1", "e2"], "yo")
    assert out["msgid"] == "M"
    assert captured["path"] == "externalcontact/add_msg_template"
    assert captured["json"]["chat_type"] == "single"
    assert captured["json"]["external_userid"] == ["e1", "e2"]
    assert captured["json"]["sender"] == "boss"
    assert captured["json"]["text"]["content"] == "yo"


def test_wecom_id_roundtrips_through_agent_api(client):
    admin = auth(client, "ADM")
    a1 = client._ids["a1"]
    r = client.patch(f"/agents/{a1}", headers=admin, json={"wecom_external_userid": "wm_new"})
    assert r.status_code == 200, r.text
    assert r.json()["wecom_external_userid"] == "wm_new"
    got = next(a for a in client.get("/agents", headers=admin).json() if a["id"] == a1)
    assert got["wecom_external_userid"] == "wm_new"
