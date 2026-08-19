"""
Agent hierarchy validation.

Rules:
  - level (tree depth) must be >= 1 (a manager may have unlimited depth of
    downline, so there is no upper cap)
  - if upline_id is set, the upline must exist and sit exactly one level above
    (upline.level == agent.level - 1); a rootless agent must be level 1
  - no cycles: an agent cannot be its own ancestor
Violations raise ValidationError, which the API maps to HTTP 422.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.models import Agent, AgentLevel


class ValidationError(Exception):
    """Raised when an agent would violate a hierarchy invariant (-> HTTP 422)."""


def _ancestor_ids(session: Session, agent_id: int) -> set[int]:
    """All upline ids above agent_id (walks upline_id to the top)."""
    seen: set[int] = set()
    current = session.get(Agent, agent_id)
    while current is not None and current.upline_id is not None:
        if current.upline_id in seen:
            break  # defensive: pre-existing cycle
        seen.add(current.upline_id)
        current = session.get(Agent, current.upline_id)
    return seen


def validate_agent(session: Session, level: int, upline_id: int | None,
                   agent_id: int | None = None, company: str | None = None) -> None:
    """Validate a proposed agent (create or update). Raises ValidationError."""
    if level < 1:
        raise ValidationError(f"level must be >= 1, got {level}")

    if upline_id is None:
        # Only an L1 may be rootless; lower levels need an upline.
        if level != AgentLevel.L1:
            raise ValidationError(f"level {level} agent requires an upline_id")
        return

    upline = session.get(Agent, upline_id)
    if upline is None:
        raise ValidationError(f"upline_id {upline_id} does not exist")

    # Hierarchies never cross companies, so the manager-subtree scoping stays safe.
    if company is not None and upline.company != company:
        raise ValidationError("upline must belong to the same company")

    if agent_id is not None and upline_id == agent_id:
        raise ValidationError("an agent cannot be its own upline")

    if int(upline.level) != level - 1:
        raise ValidationError(
            f"upline level must be exactly one above: upline is L{int(upline.level)}, "
            f"agent is L{level} (expected upline L{level - 1})"
        )

    # Cycle check: the chosen upline must not already sit below this agent.
    if agent_id is not None:
        if agent_id == upline_id or agent_id in _ancestor_ids(session, upline_id):
            raise ValidationError("cycle detected: upline is a descendant of this agent")
