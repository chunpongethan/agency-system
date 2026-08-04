"""
Audit log for commission-affecting changes: who, when, what, and before/after.

Covered actions (Phase 5): create/settle/cancel transaction, create product,
create/edit override rule, lock/unlock period, run payout. Entries are append-only.
"""
from __future__ import annotations

import json
from decimal import Decimal
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.models import AuditEntry


def _default(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


def _dump(value) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=_default, sort_keys=True)


def record(session: Session, actor_agent_id: int | None, action: str, entity: str,
           entity_id: str | int | None = None, before=None, after=None) -> AuditEntry:
    """Append an audit entry. Caller commits."""
    entry = AuditEntry(
        actor_agent_id=actor_agent_id,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=_dump(before),
        after=_dump(after),
    )
    session.add(entry)
    session.flush()
    return entry
