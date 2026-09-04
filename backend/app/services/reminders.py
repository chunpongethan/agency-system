"""
Follow-up reminders for the sales pipeline (Cases).

A case's 跟進事項 (follow_up) can carry a deadline and an urgent flag. This module
finds the cases that need attention and pushes WeChat reminders to each case's
role agents (Lead / SDR / Closer) via the 企業微信「客戶聯繫」bridge.

Two entry points:
  * run_daily_reminders(db) — the scheduled daily digest: one grouped message per
    agent listing all their due/overdue/urgent follow-ups (respects WeChat's
    ~1 enterprise-message/customer/day cap). Idempotent per calendar day.
  * remind_one_case(db, case) — an on-demand single-case reminder to its role agents.

Both are best-effort: a WeChat failure for one agent never aborts the rest, and if
WeCom is not configured they report that instead of raising.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Agent, Case, CaseOutcome, ReminderRun
from app.services import wecom

# The "yellow" window: a deadline this many days out (or already past) is "due".
DUE_WINDOW_DAYS = 3
_APP = "FOA 家辦代理系統"


def due_cases(db: Session, today: date) -> list[Case]:
    """Open cases whose follow-up needs attention: a deadline within the next
    DUE_WINDOW_DAYS (or overdue), or an explicit urgent flag."""
    horizon = today + timedelta(days=DUE_WINDOW_DAYS)
    rows = db.execute(
        select(Case).where(
            Case.outcome == CaseOutcome.OPEN,
            (
                (Case.follow_up_deadline.is_not(None) & (Case.follow_up_deadline <= horizon))
                | (Case.follow_up_urgent.is_(True))
            ),
        ).order_by(Case.follow_up_deadline.is_(None), Case.follow_up_deadline, Case.id)
    ).scalars().all()
    return list(rows)


def _status_zh(case: Case, today: date) -> str:
    d = case.follow_up_deadline
    if d is None:
        return "緊急" if case.follow_up_urgent else "待跟進"
    if d < today:
        return f"逾期 {(today - d).days} 天（{d.isoformat()}）"
    if d == today:
        return f"今天到期（{d.isoformat()}）"
    return f"還有 {(d - today).days} 天（{d.isoformat()}）"


def _case_line(case: Case, today: date) -> str:
    parts = [case.prospect_name, _status_zh(case, today)]
    if case.follow_up_urgent and case.follow_up_deadline is not None:
        parts.append("緊急")
    if case.follow_up:
        parts.append(case.follow_up.strip())
    return "・".join(p for p in parts if p)


def _role_agent_ids(case: Case) -> list[int]:
    ids: list[int] = []
    for aid in (case.lead_agent_id, case.sdr_agent_id, case.closer_agent_id):
        if aid is not None and aid not in ids:
            ids.append(aid)
    return ids


def _agents_by_id(db: Session, ids: set[int]) -> dict[int, Agent]:
    if not ids:
        return {}
    rows = db.execute(select(Agent).where(Agent.id.in_(ids))).scalars().all()
    return {a.id: a for a in rows}


def remind_one_case(db: Session, case: Case, today: date | None = None) -> dict:
    """Send a single case's follow-up reminder to its Lead / SDR / Closer.
    Returns {sent: [agent_id...], skipped_no_wechat: [agent_id...]}. Raises
    wecom.WecomError only when WeCom is not configured."""
    if not wecom._enabled():
        raise wecom.WecomError("WeCom is not configured")
    today = today or date.today()
    role_ids = _role_agent_ids(case)
    agents = _agents_by_id(db, set(role_ids))
    sent: list[int] = []
    skipped: list[int] = []
    ext_ids: list[str] = []
    for aid in role_ids:
        a = agents.get(aid)
        if a and a.wecom_external_userid:
            ext_ids.append(a.wecom_external_userid)
            sent.append(aid)
        else:
            skipped.append(aid)
    if ext_ids:
        text = f"跟進提醒（{_APP}）\n{_case_line(case, today)}"
        try:
            wecom.send_text(ext_ids, text)
        except wecom.WecomError:
            # Report as skipped rather than crash the request.
            return {"sent": [], "skipped_no_wechat": role_ids, "error": "send_failed"}
    return {"sent": sent, "skipped_no_wechat": skipped}


def run_daily_reminders(db: Session, today: date | None = None, force: bool = False) -> dict:
    """Group due cases per role agent and send each agent one digest. Idempotent
    per calendar day unless force=True. Best-effort per agent."""
    today = today or date.today()
    if not wecom._enabled():
        return {"status": "wecom_not_configured"}
    if not force and db.get(ReminderRun, today) is not None:
        return {"status": "already_ran", "run_date": today.isoformat()}

    cases = due_cases(db, today)
    # Group cases by each role agent.
    by_agent: dict[int, list[Case]] = {}
    for c in cases:
        for aid in _role_agent_ids(c):
            by_agent.setdefault(aid, []).append(c)

    agents = _agents_by_id(db, set(by_agent.keys()))
    notified: list[int] = []
    skipped_no_wechat: list[int] = []
    for aid, agent_cases in by_agent.items():
        a = agents.get(aid)
        if not a or not a.wecom_external_userid:
            skipped_no_wechat.append(aid)
            continue
        lines = "\n".join(f"• {_case_line(c, today)}" for c in agent_cases)
        text = (f"跟進提醒（{_APP}）\n你有 {len(agent_cases)} 個跟進事項需要處理：\n{lines}")
        try:
            wecom.send_text([a.wecom_external_userid], text)
            notified.append(aid)
        except wecom.WecomError:
            skipped_no_wechat.append(aid)

    # Claim the day so a scheduler re-fire (e.g. after a restart) won't resend.
    if db.get(ReminderRun, today) is None:
        db.add(ReminderRun(run_date=today))
    db.commit()
    return {
        "status": "sent",
        "run_date": today.isoformat(),
        "cases": len(cases),
        "agents_notified": notified,
        "skipped_no_wechat": skipped_no_wechat,
    }
