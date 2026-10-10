"""
課程考核 (MC quiz): admins build a quiz linked to a 商學院課程; agents/學員 take it,
submit, and get a scored result; admins see a per-taker scoring report. Quizzes inherit
the linked course's company visibility, and retakes keep the latest attempt.
"""
from app.models.models import Agent, Role
from app.security import hash_password

# Reuse the training fixture/helpers (same in-memory app + seeded agents).
from tests.test_training_materials import client, auth, mk_material, _mk_bschool  # noqa: F401


QUESTIONS = [
    {"text": "2 + 2 = ?", "options": ["3", "4", "5"], "correct_index": 1, "explanation": "Basic math."},
    {"text": "Sky colour?", "options": ["Green", "Blue"], "correct_index": 1, "explanation": "It's blue."},
]


def _mk_quiz(client, headers, material_id, **kw):
    payload = {"title": "考核 A", "material_id": material_id, "pass_pct": 60,
               "is_active": True, "questions": QUESTIONS}
    payload.update(kw)
    return client.post("/admin/quizzes", headers=headers, json=payload)


def test_quiz_crud_and_taker_hides_answers(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]

    # Agents cannot create; admins can.
    assert _mk_quiz(client, ax, mid).status_code == 403
    r = _mk_quiz(client, adm, mid)
    assert r.status_code == 201, r.text
    qid = r.json()["id"]
    assert r.json()["questions"][0]["correct_index"] == 1   # admin sees answers

    # Taker view carries questions but NO correct answer / explanation.
    take = client.get(f"/quizzes/{qid}", headers=ax).json()
    assert take["pass_pct"] == 60 and len(take["questions"]) == 2
    assert take["questions"][0]["options"] == ["3", "4", "5"]
    assert "correct_index" not in take["questions"][0]
    assert "explanation" not in take["questions"][0]


def test_submit_scores_passes_and_keeps_latest(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]
    qid = _mk_quiz(client, adm, mid).json()["id"]

    # All correct → 100% → 合格, with full per-question breakdown.
    res = client.post(f"/quizzes/{qid}/submit", headers=ax, json={"answers": [1, 1]}).json()
    assert res["score"] == 2 and res["total"] == 2 and res["pct"] == 100 and res["passed"] is True
    assert res["questions"][0]["correct_index"] == 1 and res["questions"][0]["is_correct"] is True
    assert res["questions"][0]["explanation"] == "Basic math."

    # Retake, worse → 50% → 不合格. Latest replaces; one attempt row, count == 2.
    res2 = client.post(f"/quizzes/{qid}/submit", headers=ax, json={"answers": [0, 1]}).json()
    assert res2["score"] == 1 and res2["pct"] == 50 and res2["passed"] is False

    rep = client.get("/admin/quiz-results", headers=adm).json()
    assert rep["total_attempts"] == 1 and rep["pass_count"] == 0
    row = rep["rows"][0]
    assert row["agent_code"] == "AX" and row["pct"] == 50 and row["passed"] is False
    assert row["attempt_count"] == 2 and row["quiz_title"] == "考核 A"


def test_quiz_visibility_by_company(client):
    adm = auth(client, "ADM")
    _mk_bschool(client, "b1")
    b, ax = auth(client, "b1"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]

    # A quiz limited to bschool → 404 for a heritree agent, takeable by bschool + 學員.
    qid = _mk_quiz(client, adm, mid, companies=["bschool"]).json()["id"]
    assert client.get(f"/quizzes/{qid}", headers=ax).status_code == 404
    assert client.post(f"/quizzes/{qid}/submit", headers=ax, json={"answers": [1, 1]}).status_code == 404
    assert client.get(f"/quizzes/{qid}", headers=b).status_code == 200
    assert qid in [q["id"] for q in client.get("/quizzes", headers=b).json()]
    assert qid not in [q["id"] for q in client.get("/quizzes", headers=ax).json()]

    # A quiz with no company list (null) is visible to ALL companies.
    qall = _mk_quiz(client, adm, mid).json()["id"]
    assert client.get(f"/quizzes/{qall}", headers=ax).status_code == 200
    assert qall in [q["id"] for q in client.get("/quizzes", headers=ax).json()]

    # A 學員 (student) may take the bschool quiz too.
    s = client._Session()
    s.add(Agent(code="b500", name="stu", email="stu@x.com", level=1, role=Role.STUDENT,
                company="bschool", password_hash=hash_password("pw")))
    s.commit(); s.close()
    stu = auth(client, "b500")
    assert client.post(f"/quizzes/{qid}/submit", headers=stu, json={"answers": [1, 1]}).json()["passed"] is True


def test_quiz_results_delete_admin_only(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]
    qid = _mk_quiz(client, adm, mid).json()["id"]
    client.post(f"/quizzes/{qid}/submit", headers=ax, json={"answers": [1, 1]})
    aid = client.get("/admin/quiz-results", headers=adm).json()["rows"][0]["id"]

    assert client.delete(f"/admin/quiz-results/{aid}", headers=ax).status_code == 403
    assert client.delete(f"/admin/quiz-results/{aid}", headers=adm).status_code == 204
    assert client.get("/admin/quiz-results", headers=adm).json()["total_attempts"] == 0
