"""Fresh project authorization for cross-user conversation tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cognis.core.project_access import can_read_conversation
from cognis.store.project_queries import get_project_agent_use_assignment
from cognis.store.queries import get_agent, get_conversation


async def require_project_agent(
    session: AsyncSession, *, actor: str, project_id: str, runtime_access: Any
) -> None:
    """Only the server-selected active project and assigned active agent qualify."""
    access = runtime_access if isinstance(runtime_access, dict) else {}
    if access.get("project_id") != project_id:
        raise ValueError("Project is not active in this agent session")
    agent_id = access.get("agent_id")
    agent = await get_agent(session, agent_id) if isinstance(agent_id, str) else None
    if (
        agent is None
        or agent.status != "active"
        or (access.get("agent_owner_email") and access["agent_owner_email"] != agent.owner_email)
        or not await get_project_agent_use_assignment(
            session, project_id=project_id, agent_id=agent.agent_id, user_email=actor
        )
    ):
        raise ValueError("Project agent access is unavailable")


async def readable_project_conversation(
    session: AsyncSession, *, actor: str, conversation_id: str, runtime_access: Any
) -> Any:
    """Read explicit project-visible topic history, never another user's private chat."""
    access = runtime_access if isinstance(runtime_access, dict) else {}
    project_id = access.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("Conversation not found")
    await require_project_agent(session, actor=actor, project_id=project_id, runtime_access=access)
    row = await get_conversation(session, conversation_id)
    if (
        row is None
        or row.status == "deleted"
        or row.project_id != project_id
        or row.visibility != "project"
        or not await can_read_conversation(session, row, actor)
    ):
        raise ValueError("Conversation not found")
    return row
