"""
企業微信 (WeCom) 「客戶聯繫」bridge — push messages to an agent's *personal* WeChat.

Personal WeChat has no official send API. The only ToS-compliant way to reach a
personal 微信 account from a server is via WeCom's external-contact "enterprise
group message" (企業群發): the agent adds a WeCom member as an external contact,
and we send to their `external_userid` through that member.

Configured entirely from the environment:
  WECOM_CORP_ID         the corp id (企業ID)
  WECOM_CONTACT_SECRET  the 客戶聯繫 secret (Secret of the 客戶聯繫 API / app)
  WECOM_SENDER_USERID   the member userid that owns the external contacts and sends

If any is unset the bridge is disabled and send_text() raises WecomError so callers
can surface a clear "not configured" message (mirrors mailer.py's env-gating).

Delivery caveats (WeChat platform limits, not ours):
  * a customer can receive at most ~1 enterprise group message per day;
  * depending on the org's config the sender member may have to tap 發送 in WeCom;
  * an agent only receives messages after they've added the sender member.
"""
from __future__ import annotations

import logging
import os
import threading

import httpx

log = logging.getLogger("wecom")

_BASE = "https://qyapi.weixin.qq.com/cgi-bin"

# Cached access token (WeChat tokens last ~7200s; refresh a little early).
_token_lock = threading.Lock()
_token_cache: dict[str, float | str | None] = {"value": None, "expires_at": 0.0}


class WecomError(Exception):
    """Normalized WeCom failure (config missing or a non-zero WeChat errcode)."""

    def __init__(self, message: str, *, errcode: int | None = None):
        super().__init__(message)
        self.errcode = errcode


def _enabled() -> bool:
    return bool(
        os.getenv("WECOM_CORP_ID")
        and os.getenv("WECOM_CONTACT_SECRET")
        and os.getenv("WECOM_SENDER_USERID")
    )


def _now() -> float:
    # Wrapped so tests can monkeypatch time without touching the stdlib import site.
    import time
    return time.monotonic()


def _fetch_token() -> str:
    corp_id = os.getenv("WECOM_CORP_ID")
    secret = os.getenv("WECOM_CONTACT_SECRET")
    r = httpx.get(f"{_BASE}/gettoken",
                  params={"corpid": corp_id, "corpsecret": secret}, timeout=20)
    r.raise_for_status()
    body = r.json()
    if body.get("errcode", 0) != 0 or not body.get("access_token"):
        raise WecomError(f"gettoken failed: {body.get('errmsg')}",
                         errcode=body.get("errcode"))
    token = body["access_token"]
    ttl = int(body.get("expires_in", 7200))
    with _token_lock:
        _token_cache["value"] = token
        _token_cache["expires_at"] = _now() + max(60, ttl - 200)
    return token


def _get_token(force: bool = False) -> str:
    if not force:
        with _token_lock:
            tok = _token_cache["value"]
            exp = _token_cache["expires_at"]
        if tok and isinstance(exp, (int, float)) and _now() < exp:
            return tok  # type: ignore[return-value]
    return _fetch_token()


def _post(path: str, json: dict) -> dict:
    """POST to a WeCom endpoint with the cached token, retrying once on an expired
    or invalid token (errcode 42001 / 40014)."""
    token = _get_token()
    r = httpx.post(f"{_BASE}/{path}", params={"access_token": token},
                   json=json, timeout=20)
    r.raise_for_status()
    body = r.json()
    if body.get("errcode") in (42001, 40014):
        token = _get_token(force=True)
        r = httpx.post(f"{_BASE}/{path}", params={"access_token": token},
                       json=json, timeout=20)
        r.raise_for_status()
        body = r.json()
    return body


def send_text(external_userids: list[str], content: str) -> dict:
    """Send a plain-text enterprise group message to the given external contacts
    (personal-WeChat users). Returns the parsed WeChat response
    (errcode / msgid / fail_list). Raises WecomError if disabled or WeChat rejects.

    Note: WeChat's add_msg_template treats errcode 0 as "task created"; per-recipient
    failures come back in `fail_list`, not as a top-level error."""
    if not _enabled():
        raise WecomError("WeCom is not configured (set WECOM_CORP_ID / "
                         "WECOM_CONTACT_SECRET / WECOM_SENDER_USERID)")
    if not external_userids:
        raise WecomError("no recipients")
    payload = {
        "chat_type": "single",
        "external_userid": external_userids,
        "sender": os.getenv("WECOM_SENDER_USERID"),
        "text": {"content": content},
    }
    body = _post("externalcontact/add_msg_template", payload)
    if body.get("errcode", 0) != 0:
        raise WecomError(f"add_msg_template failed: {body.get('errmsg')}",
                         errcode=body.get("errcode"))
    return body


def list_customers() -> list[dict]:
    """External contacts (客戶) of the sender member, as [{external_userid, name}].
    Powers the admin picker so an agent can be bound without pasting an opaque id.
    Best-effort: raises WecomError on config/API failure."""
    if not _enabled():
        raise WecomError("WeCom is not configured")
    sender = os.getenv("WECOM_SENDER_USERID")
    listed = _post_get("externalcontact/list", {"userid": sender})
    ids = listed.get("external_userid", []) if listed.get("errcode", 0) == 0 else []
    if not ids:
        return []
    detail = _post("externalcontact/batch/get_by_user",
                   {"userid_list": [sender], "limit": 100})
    out: list[dict] = []
    for entry in detail.get("external_contact_list", []):
        c = entry.get("external_contact", {})
        if c.get("external_userid"):
            out.append({"external_userid": c["external_userid"],
                        "name": c.get("name", "")})
    return out


def _post_get(path: str, params: dict) -> dict:
    """GET helper (some external-contact reads are GET) with token + one retry."""
    token = _get_token()
    r = httpx.get(f"{_BASE}/{path}", params={**params, "access_token": token}, timeout=20)
    r.raise_for_status()
    body = r.json()
    if body.get("errcode") in (42001, 40014):
        token = _get_token(force=True)
        r = httpx.get(f"{_BASE}/{path}", params={**params, "access_token": token}, timeout=20)
        r.raise_for_status()
        body = r.json()
    return body
