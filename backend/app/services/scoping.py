"""
Row-level scoping: which agents' data a principal may see.

  - agent   -> just their own id
  - manager -> their id plus their entire downline subtree (one recursive CTE
               walking upline_id downward — not N queries)
  - admin   -> all agents

`assert_visible` turns an out-of-scope access into a 403 (never a silent empty
result). Build and test this in isolation before wiring it into endpoints.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Agent, Role


def visible_agent_ids(session: Session, current: Agent) -> set[int]:
    """The set of agent ids `current` is allowed to see."""
    if current.role == Role.ADMIN:
        return {row[0] for row in session.execute(select(Agent.id))}

    if current.role == Role.AGENT:
        return {current.id}

    # manager: own id + entire subtree via a single recursive CTE.
    subtree = (
        select(Agent.id.label("id"))
        .where(Agent.id == current.id)
        .cte("subtree", recursive=True)
    )
    children = select(Agent.id).where(Agent.upline_id == subtree.c.id)
    subtree = subtree.union_all(children)
    return {row[0] for row in session.execute(select(subtree.c.id))}


def assert_visible(session: Session, current: Agent, agent_id: int) -> None:
    """Raise PermissionError if `agent_id` is outside `current`'s scope."""
    if agent_id not in visible_agent_ids(session, current):
        raise PermissionError(
            f"agent {current.id} may not access data for agent {agent_id}"
        )
