"""
Row-level scoping.

Two distinct layers of access:

1. **Production visibility** (`visible_agent_ids` / `assert_visible`) — used for
   commission *reports* and the org tree:
     - agent   -> just their own id
     - manager -> their id plus their entire downline subtree (one recursive CTE)
     - admin   -> all agents

2. **Client/transaction ownership** (`assert_owns_client`) — client details and
   their transactions are strictly owner-only: only the agent who owns a client
   may read or edit that client and its transactions. Managers do NOT get their
   downlines' client/transaction details; admins get none (admin is not a seller).
   Admins retain a separate authority over transactions (see `is_admin`).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Agent, Client, Case, Role


def is_admin(current: Agent) -> bool:
    return current.role == Role.ADMIN


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
    """Raise PermissionError if `agent_id` is outside `current`'s production scope."""
    if agent_id not in visible_agent_ids(session, current):
        raise PermissionError(
            f"agent {current.id} may not access data for agent {agent_id}"
        )


def assert_owns_client(current: Agent, client: Client) -> None:
    """
    Editing a client profile is allowed for its owning agent, or for an admin
    (admins maintain client records on behalf of agents alongside transactions).
    """
    if not is_admin(current) and current.id != client.agent_id:
        raise PermissionError("only the client's own agent or an admin may edit this client")


def assert_can_read_client(current: Agent, client: Client) -> None:
    """
    Reading a client is allowed for its owning agent or for an admin (admins are
    the sole transaction operators and must see clients to book for them).
    """
    if not is_admin(current) and current.id != client.agent_id:
        raise PermissionError("only the client's own agent or an admin may read this client")


def assert_can_access_txn(current: Agent, txn_agent_id: int) -> None:
    """
    Transactions are readable/editable by the owning agent, or by an admin
    (admins have authority over transaction data).
    """
    if not is_admin(current) and current.id != txn_agent_id:
        raise PermissionError("only the owning agent or an admin may access this transaction")


def _case_agent_ids(case: Case) -> set[int]:
    return {aid for aid in (case.lead_agent_id, case.sdr_agent_id, case.closer_agent_id)
            if aid is not None}


def assert_can_view_case(session: Session, current: Agent, case: Case) -> None:
    """
    A case is viewable by an admin, or by anyone whose production scope
    (self for an agent, self+downline subtree for a manager) includes one of the
    case's assigned agents. Uses the *visibility* layer so managers see downlines'
    cases (unlike client/transaction ownership, which is owner-only).
    """
    if is_admin(current):
        return
    if _case_agent_ids(case) & visible_agent_ids(session, current):
        return
    raise PermissionError("only an assigned agent, their manager, or an admin may view this case")


def assert_can_edit_case(current: Agent, case: Case) -> None:
    """
    Editing a case is limited to its assigned agents (Lead / SDR / Closer) or an
    admin. Managers who merely oversee a downline's case get read-only access.
    """
    if not is_admin(current) and current.id not in _case_agent_ids(case):
        raise PermissionError("only an assigned agent or an admin may edit this case")
