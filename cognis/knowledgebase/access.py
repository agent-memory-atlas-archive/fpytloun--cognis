"""Knowledgebase access resolution for owner and agent-bound use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from cognis.core.project_access import resolve_agent_use_grant
from cognis.models.agent import AgentPermissions
from cognis.store.models import Agent, KnowledgebaseRow
from cognis.store.project_knowledge import list_project_knowledgebases
from cognis.store.project_queries import get_project_agent_use_assignment
from cognis.store.queries import (
    get_active_knowledgebase_grant,
    get_agent,
    get_knowledgebase_by_id,
    list_knowledgebases_for_user,
)

KnowledgebaseAccessMode = Literal["view", "use", "manage"]


@dataclass(frozen=True, slots=True)
class KnowledgebaseAccessContext:
    actor_email: str
    agent_id: str | None = None
    agent_owner_email: str | None = None
    project_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedKnowledgebaseAccess:
    knowledgebase: KnowledgebaseRow
    actor_email: str
    owner_email: str
    via_agent_id: str | None = None
    is_owner: bool = False
    is_agent_grantee: bool = False
    is_direct_user_grantee: bool = False
    is_project_grantee: bool = False


async def resolve_knowledgebase_access(
    session: AsyncSession,
    *,
    knowledgebase_id: str,
    context: KnowledgebaseAccessContext,
    mode: KnowledgebaseAccessMode,
) -> ResolvedKnowledgebaseAccess | None:
    """Resolve KB access server-side.

    Owner-only ``manage`` is intentionally separate from agent-bound ``use``.
    When an active agent context is present, view/use requires the KB to be
    assigned to that agent, including for the owner.
    """

    kb = await get_knowledgebase_by_id(session, knowledgebase_id=knowledgebase_id)
    if kb is None:
        return None
    is_owner = context.actor_email == kb.owner_email
    if mode == "manage":
        if not is_owner:
            return None
        return ResolvedKnowledgebaseAccess(
            knowledgebase=kb,
            actor_email=context.actor_email,
            owner_email=kb.owner_email,
            is_owner=True,
        )

    if context.agent_id:
        agent = await get_agent(session, context.agent_id)
        if agent is None or agent.status != "active":
            return None
        if context.agent_owner_email and context.agent_owner_email != agent.owner_email:
            return None
        if context.project_id and await get_project_agent_use_assignment(
            session,
            agent_id=agent.agent_id,
            user_email=context.actor_email,
            project_id=context.project_id,
        ):
            rows = await list_project_knowledgebases(
                session, user_email=context.actor_email, project_id=context.project_id
            )
            if any(row.knowledgebase_id == knowledgebase_id for row in rows):
                return ResolvedKnowledgebaseAccess(
                    knowledgebase=kb,
                    actor_email=context.actor_email,
                    owner_email=kb.owner_email,
                    via_agent_id=agent.agent_id,
                    is_project_grantee=True,
                    is_owner=is_owner,
                )
        if agent.owner_email != kb.owner_email:
            return None
        if knowledgebase_id not in _allowed_knowledgebases(agent):
            return None
        if context.actor_email != agent.owner_email:
            agent_grant = await resolve_agent_use_grant(
                session,
                agent_id=agent.agent_id,
                user_email=context.actor_email,
                project_id=context.project_id,
            )
            if agent_grant is None:
                return None
            return ResolvedKnowledgebaseAccess(
                knowledgebase=kb,
                actor_email=context.actor_email,
                owner_email=kb.owner_email,
                via_agent_id=agent.agent_id,
                is_owner=False,
                is_agent_grantee=True,
            )
        return ResolvedKnowledgebaseAccess(
            knowledgebase=kb,
            actor_email=context.actor_email,
            owner_email=kb.owner_email,
            via_agent_id=agent.agent_id,
            is_owner=True,
        )

    if is_owner:
        return ResolvedKnowledgebaseAccess(
            knowledgebase=kb,
            actor_email=context.actor_email,
            owner_email=kb.owner_email,
            is_owner=True,
        )
    knowledgebase_grant = await get_active_knowledgebase_grant(
        session, knowledgebase_id, context.actor_email
    )
    if knowledgebase_grant is not None:
        return ResolvedKnowledgebaseAccess(
            knowledgebase=kb,
            actor_email=context.actor_email,
            owner_email=kb.owner_email,
            is_direct_user_grantee=True,
        )
    if any(
        row.knowledgebase_id == knowledgebase_id
        for row in await list_project_knowledgebases(session, user_email=context.actor_email)
    ):
        return ResolvedKnowledgebaseAccess(
            knowledgebase=kb,
            actor_email=context.actor_email,
            owner_email=kb.owner_email,
            is_project_grantee=True,
        )
    return None


async def list_available_knowledgebases(
    session: AsyncSession,
    *,
    context: KnowledgebaseAccessContext,
) -> list[KnowledgebaseRow]:
    """List KB rows available for the current direct or active-agent context."""

    if not context.agent_id:
        return await list_knowledgebases_for_user(session, context.actor_email)
    agent = await get_agent(session, context.agent_id)
    if agent is None or agent.status != "active":
        return []
    if context.agent_owner_email and context.agent_owner_email != agent.owner_email:
        return []
    if context.actor_email != agent.owner_email:
        grant = await resolve_agent_use_grant(
            session,
            agent_id=agent.agent_id,
            user_email=context.actor_email,
            project_id=context.project_id,
        )
        if grant is None:
            return []
    ids = _allowed_knowledgebases(agent)
    from cognis.store.queries import list_knowledgebases_by_ids

    rows = await list_knowledgebases_by_ids(
        session,
        owner_email=agent.owner_email,
        knowledgebase_ids=ids,
    )
    if context.project_id and await get_project_agent_use_assignment(
        session,
        agent_id=agent.agent_id,
        user_email=context.actor_email,
        project_id=context.project_id,
    ):
        rows += await list_project_knowledgebases(
            session, user_email=context.actor_email, project_id=context.project_id
        )
    return list({row.knowledgebase_id: row for row in rows}.values())


def _allowed_knowledgebases(agent: Agent) -> list[str]:
    permissions = AgentPermissions.model_validate(agent.permissions or {})
    return list(dict.fromkeys(permissions.allowed_knowledgebases))
