"""Authoritative choices shared by agent-management discovery and execution."""

from __future__ import annotations

from typing import Any

from cognis.core.workflow_registry import SYSTEM_WORKFLOWS
from cognis.store.queries import get_agent, list_knowledgebases, list_workflows


async def available_workflows(session: Any, actor_email: str) -> list[Any]:
    """Include shipped workflows even when they have no database row."""
    rows = await list_workflows(session, owner_email=actor_email, include_system=False)
    return [*SYSTEM_WORKFLOWS.values(), *rows]


async def assignable_knowledgebases(
    session: Any,
    *,
    actor_email: str,
    caller_agent_id: str | None,
    allowed_ids: set[str] | None = None,
) -> list[Any]:
    """Read current caller assignments without modifying the turn's authority snapshot."""
    if caller_agent_id is not None:
        caller = await get_agent(session, caller_agent_id)
        if caller is None or caller.owner_email != actor_email or caller.status != "active":
            return []
        assigned = set((caller.permissions or {}).get("allowed_knowledgebases", []))
        allowed_ids = assigned if allowed_ids is None else assigned & allowed_ids
    rows = await list_knowledgebases(session, owner_email=actor_email)
    return [
        row
        for row in rows
        if row.status == "active" and (allowed_ids is None or row.knowledgebase_id in allowed_ids)
    ]
