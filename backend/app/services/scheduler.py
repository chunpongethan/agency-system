"""
In-process daily scheduler for follow-up WeChat reminders.

The API runs as a single uvicorn process (see backend/entrypoint.sh), so a single
in-process APScheduler runs the daily job exactly once — no external cron needed
and no multi-worker duplication. The reminder run is also idempotent per day
(app.services.reminders claims a ReminderRun row), which guards against a same-day
re-fire after a container restart.

Started from a FastAPI startup hook. It is a no-op when WeCom is not configured or
when DISABLE_SCHEDULER is set, and it never starts under pytest (tests use
TestClient without a lifespan context, so startup hooks don't fire).
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("scheduler")

_scheduler = None  # module-level so it isn't garbage-collected


def _run_job() -> None:
    from app.main import SessionLocal
    from app.services import reminders
    db = SessionLocal()
    try:
        result = reminders.run_daily_reminders(db)
        log.info("daily follow-up reminders: %s", result)
    except Exception:  # noqa: BLE001 — a scheduled job must never crash the process
        log.warning("daily follow-up reminder run failed", exc_info=True)
    finally:
        db.close()


def start() -> None:
    """Start the daily reminder scheduler (idempotent; safe to call once at startup)."""
    global _scheduler
    if _scheduler is not None:
        return
    if os.getenv("DISABLE_SCHEDULER"):
        log.info("scheduler disabled via DISABLE_SCHEDULER")
        return
    from app.services import wecom
    if not wecom._enabled():
        log.info("WeCom not configured — follow-up reminder scheduler not started")
        return
    try:
        hour = int(os.getenv("WECOM_REMINDER_HOUR", "9"))
    except ValueError:
        hour = 9
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception:  # noqa: BLE001 — missing dep must not break API startup
        log.warning("APScheduler not available — reminder scheduler not started", exc_info=True)
        return
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(_run_job, CronTrigger(hour=hour, minute=0),
                  id="daily_follow_up_reminders", replace_existing=True)
    sched.start()
    _scheduler = sched
    log.info("follow-up reminder scheduler started (daily at %02d:00)", hour)
