"""
Minimal SMTP mailer for transactional email (password resets).

Configured entirely from the environment:
  SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD,
  SMTP_FROM (sender address), SMTP_TLS ("true"/"false", default true = STARTTLS).

If SMTP_HOST is not set, email is not sent — the message is logged instead, so
password-reset works in development without a mail server (copy the link from the
API logs). Set the SMTP_* vars in production to actually deliver mail.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("mailer")


def _enabled() -> bool:
    return bool(os.getenv("SMTP_HOST"))


def send_email(to: str, subject: str, body: str) -> None:
    if not _enabled():
        log.warning("SMTP not configured — email not sent. To=%s Subject=%s\n%s",
                    to, subject, body)
        return

    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", user or "no-reply@localhost")
    use_tls = os.getenv("SMTP_TLS", "true").lower() != "false"

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=20) as server:
        if use_tls:
            server.starttls()
        if user and password:
            server.login(user, password)
        server.send_message(msg)
    log.info("password-reset email sent to %s", to)


def send_login_alert(to: str, name: str, code: str, role: str, when: str) -> None:
    """Notify the admin that a user signed in. Best-effort: never raises, so a
    mail failure can't affect the login it is reporting on."""
    subject = f"登入通知 Login alert：{name}（{code}）"
    body = (
        f"{name}（{code}）以「{role}」身分登入系統。\n"
        f"時間（UTC）：{when}\n\n"
        f"{name} ({code}) signed in as {role}.\n"
        f"Time (UTC): {when}\n\n"
        f"— 承瑞家辦代理系統 (Chengrui Family Office Agency System)\n"
    )
    try:
        send_email(to, subject, body)
    except Exception:  # noqa: BLE001 — alerting must not break the request
        log.warning("failed to send login alert to %s", to, exc_info=True)


def send_password_reset(to: str, name: str, reset_url: str) -> None:
    subject = "Reset your password / 重設密碼"
    body = (
        f"Hi {name},\n\n"
        f"We received a request to reset your password. Use the link below to set "
        f"a new one (it expires shortly):\n\n{reset_url}\n\n"
        f"If you didn't request this, you can ignore this email.\n\n"
        f"— 承瑞家辦代理系統 (Chengrui Family Office Agency System)\n\n"
        f"———\n"
        f"你好 {name}，\n\n我們收到重設密碼的要求。請使用以下連結設定新密碼"
        f"（連結將於短時間後失效）：\n\n{reset_url}\n\n若非你本人操作，可忽略此電郵。\n"
    )
    send_email(to, subject, body)
