"""
問答特訓 progress: the public Q&A pages post open / finish / exam events without
logging in; admins see a per-learner summary and the full history.
"""
import pytest

from tests.test_training_materials import client, auth  # noqa: F401

V1, V2 = "v-aaaaaaaa-1111", "v-bbbbbbbb-2222"
PAGE = "crs-tax-qa"


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    import app.main as main
    main._QA_HITS.clear()
    yield
    main._QA_HITS.clear()


def ev(client, event, visitor=V1, name="陳大文", page=PAGE, **kw):
    body = {"visitor_id": visitor, "name": name, "page": page,
            "page_title": "CRS与境外保单税务问答特训", "event": event, "module_total": 7, **kw}
    return client.post("/public/qa-events", json=body)


def test_public_events_and_admin_summary(client):
    assert ev(client, "open", module_id="m0", module_name="开篇").status_code == 204
    assert ev(client, "open", module_id="m1", module_name="三步方案").status_code == 204
    assert ev(client, "finish", module_id="m0", module_name="开篇").status_code == 204
    assert ev(client, "exam", score=8, total=10).status_code == 204
    assert ev(client, "exam", score=6, total=10).status_code == 204
    assert ev(client, "open", visitor=V2, name="李小明", module_id="m0").status_code == 204

    adm = auth(client, "ADM")
    d = client.get("/admin/qa-training", headers=adm).json()
    assert d["total_events"] == 6
    assert [e["event"] for e in d["events"]][:2] == ["open", "exam"]     # newest first
    s = {x["visitor_id"]: x for x in d["learners"]}
    a = s[V1]
    assert a["learner_name"] == "陳大文" and a["page"] == PAGE and a["module_total"] == 7
    assert a["opened"] == ["开篇", "三步方案"] and a["finished"] == ["开篇"]
    assert (a["best_score"], a["last_score"], a["exam_total"]) == (8, 6, 10)
    assert s[V2]["learner_name"] == "李小明"


def test_validation(client):
    assert ev(client, "hack", module_id="m0").status_code == 422
    assert ev(client, "open").status_code == 422                          # chapter needs a module
    assert ev(client, "open", name="  ", module_id="m0").status_code == 422
    assert ev(client, "open", page="../etc/passwd", module_id="m0").status_code == 422
    assert ev(client, "open", visitor="x", module_id="m0").status_code == 422
    # over-long text is trimmed, not stored whole
    assert ev(client, "open", name="名" * 200, module_id="m0", module_name="章" * 300).status_code == 204
    e = client.get("/admin/qa-training", headers=auth(client, "ADM")).json()["events"][0]
    assert len(e["learner_name"]) == 60 and len(e["module_name"]) == 80


def test_admin_only_and_delete(client):
    ev(client, "open", module_id="m0")
    ev(client, "open", visitor=V2, module_id="m0")
    assert client.get("/admin/qa-training", headers=auth(client, "AX")).status_code == 403
    assert client.get("/admin/qa-training").status_code in (401, 403)
    adm = auth(client, "ADM")
    assert client.delete(f"/admin/qa-training/learners/{V1}", headers=adm).status_code == 204
    assert [x["visitor_id"] for x in client.get("/admin/qa-training", headers=adm).json()["learners"]] == [V2]
    assert client.delete("/admin/qa-training", headers=adm).status_code == 204
    assert client.get("/admin/qa-training", headers=adm).json()["total_events"] == 0


def test_rate_limited(client):
    import app.main as main
    main._QA_HITS["testclient"] = [__import__("time").time()] * 60
    assert ev(client, "open", module_id="m0").status_code == 429


def test_video_course_events(client):
    """视频课 folders (/training/<slug>-video/) report with the same endpoint: chapters
    opened / finished (watched), plus each chapter's quiz result."""
    VP = "crs-video"
    vid = dict(page=VP, page_title="CRS 与境外保单税务 · 视频课", module_total=5)
    assert ev(client, "open", module_id="ch1", module_name="第1章 · 香港保险要交税了？", **vid).status_code == 204
    assert ev(client, "finish", module_id="ch1", module_name="第1章 · 香港保险要交税了？", **vid).status_code == 204
    assert ev(client, "quiz", module_id="ch1", module_name="第1章 · 香港保险要交税了？", score=1, total=3, **vid).status_code == 204
    assert ev(client, "quiz", module_id="ch1", module_name="第1章 · 香港保险要交税了？", score=3, total=3, **vid).status_code == 204
    assert ev(client, "quiz", module_id="ch2", module_name="第2章 · 哪些保单会被申报", score=2, total=3, **vid).status_code == 204
    assert ev(client, "quiz", **vid).status_code == 422                       # quiz needs a chapter
    ev(client, "open", module_id="m0", module_name="开篇")                     # a Q&A page too

    d = client.get("/admin/qa-training", headers=auth(client, "ADM")).json()
    s = {x["page"]: x for x in d["learners"]}
    v = s[VP]
    assert v["kind"] == "video" and v["module_total"] == 5
    assert v["finished"] == ["第1章 · 香港保险要交税了？"]
    assert (v["quiz_right"], v["quiz_total"], v["quiz_chapters"]) == (5, 6, 2)   # latest per chapter
    assert v["best_score"] is None
    assert s[PAGE]["kind"] == "qa" and s[PAGE]["quiz_right"] is None
    q = [e for e in d["events"] if e["event"] == "quiz"][0]
    assert (q["score"], q["total"]) == (2, 3)
