"""Canonical agent-scoped content read authorization.

Ownership and explicit grants are agent scoped. Delegation is work scoped, never
an implicit grant to all content owned by the worker. Conversation/session IDs
describe provenance, not ownership. Callers must supply server-owned identity.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from cognis.core.content_projects import (
    ContentAccess,
    content_project_ids,
    human_may_access_project_content,
)
from cognis.store.models import (
    Agent,
    ArtifactGrantRow,
    ArtifactRecordRow,
    Conversation,
    KnowledgebaseArtifactRow,
    ManagedConversationLink,
    ProjectRow,
    Session,
    StepRun,
    Task,
)


def _work_edges(*, owner_email: str) -> Any:
    """Canonical validated provenance edges shared by reads and grant registration."""
    s, c, t, r, m = Session, Conversation, Task, StepRun, ManagedConversationLink

    def node(prefix: str, column: Any) -> Any:
        return sa.literal(prefix) + column

    controller, target = aliased(c), aliased(c)
    valid_link = (
        sa.select(
            m.link_id,
            m.parent_link_id,
            m.root_link_id,
            m.depth,
            m.controller_conversation_id,
            m.controller_agent_id,
            m.controller_session_id,
            m.target_conversation_id,
            m.target_agent_id,
        )
        .join(controller, controller.conversation_id == m.controller_conversation_id)
        .join(target, target.conversation_id == m.target_conversation_id)
        .where(
            m.user_email == owner_email,
            controller.user_email == owner_email,
            target.user_email == owner_email,
            controller.agent_id == m.controller_agent_id,
            target.agent_id == m.target_agent_id,
        )
    )
    managed = valid_link.where(
        m.parent_link_id.is_(None), m.root_link_id == m.link_id, m.depth == 1
    ).cte("content_managed_lineage", recursive=True)
    managed = managed.union_all(
        valid_link.join(managed, m.parent_link_id == managed.c.link_id).where(
            m.root_link_id == managed.c.root_link_id,
            m.depth == managed.c.depth + 1,
            m.controller_conversation_id == managed.c.target_conversation_id,
            m.controller_agent_id == managed.c.target_agent_id,
            m.depth <= 2,
        )
    )
    return sa.union(
        sa.select(
            node("c:", s.conversation_id).label("parent"), node("s:", s.session_id).label("child")
        ).where(s.user_email == owner_email),
        *(
            sa.select(node("s:", column), node("s:", s.session_id)).where(
                s.user_email == owner_email, column.is_not(None)
            )
            for column in (s.parent_session_id, s.previous_session_id, s.source_session_id)
        ),
        sa.select(
            node("c:", managed.c.controller_conversation_id),
            node("c:", managed.c.target_conversation_id),
        ),
        sa.select(node("s:", t.source_session_id), node("t:", t.task_id)).where(
            t.created_by == owner_email, t.source_session_id.is_not(None)
        ),
        sa.select(node("t:", t.task_id), node("s:", r.session_id))
        .join(r, r.task_id == t.task_id)
        .where(t.created_by == owner_email, r.session_id.is_not(None)),
        sa.select(
            node("s:", managed.c.controller_session_id),
            node("c:", managed.c.target_conversation_id),
        ).where(managed.c.controller_session_id.is_not(None)),
    ).cte("content_work_edges")


def _work_nodes(*, owner_email: str, agent_id: str, session_id: str | None) -> Any:
    """SQL closure of durable work provenance; UNION also terminates corrupt cycles."""
    s, c, t = Session, Conversation, Task
    edges = _work_edges(owner_email=owner_email)

    def node(prefix: str, column: Any) -> Any:
        return sa.literal(prefix) + column

    if agent_id.startswith("system:"):
        scope = (
            sa.select(s.artifact_scope_id)
            .where(s.user_email == owner_email, s.agent_id == agent_id, s.session_id == session_id)
            .scalar_subquery()
        )
        system_seeds = sa.select(node("s:", s.session_id).label("node")).where(
            s.user_email == owner_email,
            s.agent_id == agent_id,
            sa.or_(
                s.session_id == session_id,
                sa.and_(scope.is_not(None), s.artifact_scope_id == scope),
            ),
        )
    else:
        primary_seeds = sa.union(
            sa.select(node("c:", c.conversation_id).label("node")).where(
                c.user_email == owner_email, c.agent_id == agent_id
            ),
            sa.select(node("t:", t.task_id).label("node")).where(
                t.created_by == owner_email,
                sa.or_(t.agent_id == agent_id, t.created_by_agent_id == agent_id),
            ),
        )
    # A subquery makes the compound seed a simple SELECT for recursive UNION.
    seed_rows = (
        system_seeds.subquery() if agent_id.startswith("system:") else primary_seeds.subquery()
    )
    reachable = sa.select(seed_rows.c.node).cte("content_work_scope", recursive=True)
    return reachable.union(
        sa.select(edges.c.child).join(reachable, reachable.c.node == edges.c.parent)
    )


async def content_read_predicate(
    session: AsyncSession,
    *,
    owner_email: str | None,
    agent_id: str | None,
    conversation_id: str | None = None,
    session_id: str | None = None,
    model: Any = ArtifactRecordRow,
    access: ContentAccess = "read",
) -> Any:
    """Build the same predicate for discovery and exact reads, before pagination.

    Content is readable through the owner's agent-scoped rules, or as a document
    of a project this agent session may access (``cognis.core.content_projects``).
    """
    return await _content_read_predicate(
        session,
        owner_email=owner_email,
        agent_id=agent_id,
        conversation_id=conversation_id,
        session_id=session_id,
        model=model,
        access=access,
        include_work_provenance=True,
    )


async def readable_artifact_ids(
    session: AsyncSession,
    artifact_ids: Sequence[str],
    *,
    owner_email: str | None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
    session_id: str | None = None,
) -> set[str]:
    """Authorize exact references without computing lineage for direct grants.

    The first pass is a strict subset of the canonical predicate. Only unresolved
    IDs need its recursive provenance branch; both passes retain the same actor,
    project, knowledgebase, and grant rules. No authorization result is cached.
    """
    remaining = set(artifact_ids)
    allowed: set[str] = set()
    for include_work_provenance in (False, True):
        if not remaining:
            break
        predicate = await _content_read_predicate(
            session,
            owner_email=owner_email,
            agent_id=agent_id,
            conversation_id=conversation_id,
            session_id=session_id,
            model=ArtifactRecordRow,
            access="read",
            include_work_provenance=include_work_provenance,
        )
        found = set(
            (
                await session.scalars(
                    sa.select(ArtifactRecordRow.artifact_id).where(
                        ArtifactRecordRow.artifact_id.in_(sorted(remaining)),
                        predicate,
                        sa.or_(
                            ArtifactRecordRow.expires_at.is_(None),
                            ArtifactRecordRow.expires_at > sa.func.now(),
                        ),
                    )
                )
            ).all()
        )
        allowed.update(found)
        remaining.difference_update(found)
    return allowed


async def _content_read_predicate(
    session: AsyncSession,
    *,
    owner_email: str | None,
    agent_id: str | None,
    conversation_id: str | None,
    session_id: str | None,
    model: Any,
    access: ContentAccess,
    include_work_provenance: bool,
) -> Any:
    owned = await _owned_content_predicate(
        session,
        owner_email=owner_email,
        agent_id=agent_id,
        conversation_id=conversation_id,
        session_id=session_id,
        model=model,
        include_work_provenance=include_work_provenance,
    )
    project_ids = await content_project_ids(
        session,
        user_email=owner_email,
        agent_id=agent_id,
        conversation_id=conversation_id,
        session_id=session_id,
        access=access,
    )
    if agent_id:
        own_projects: Any = sa.false()
        if access == "read" and not agent_id.startswith("system:") and owner_email:
            # Only directly owned documents get this exception, not grants,
            # knowledgebases, or delegated work reachable by the owner predicate.
            directly_owned = sa.and_(
                owned, model.owner_email == owner_email, model.owner_agent_id == agent_id
            )
            candidates = (
                sa.select(model.project_id)
                .join(ProjectRow, ProjectRow.project_id == model.project_id)
                .where(directly_owned, ProjectRow.status == "active")
                .distinct()
            )
            readable = []
            for project_id in (await session.scalars(candidates)).all():
                if await human_may_access_project_content(
                    session, project_id=project_id, user_email=owner_email, access="read"
                ):
                    readable.append(project_id)
            own_projects = sa.and_(directly_owned, model.project_id.in_(readable))
        owned = sa.or_(sa.and_(owned, model.project_id.is_(None)), own_projects)
    if not project_ids:
        return owned
    return sa.or_(owned, model.project_id.in_(project_ids))


async def _owned_content_predicate(
    session: AsyncSession,
    *,
    owner_email: str | None,
    agent_id: str | None,
    conversation_id: str | None,
    session_id: str | None,
    model: Any,
    include_work_provenance: bool,
) -> Any:
    if not owner_email:
        return sa.false()
    conversation = None
    if conversation_id:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_email != owner_email:
            return sa.false()
        agent_id = agent_id or conversation.agent_id
        if not agent_id.startswith("system:") and conversation.agent_id != agent_id:
            return sa.false()
    if not agent_id:
        return sa.false()
    if agent_id.startswith("system:"):
        current = await session.get(Session, session_id) if session_id else None
        if current is None or current.user_email != owner_email or current.agent_id != agent_id:
            return sa.false()
        if conversation_id and current.conversation_id != conversation_id:
            return sa.false()
    else:
        agent = await session.get(Agent, agent_id)
        if agent is None or agent.status != "active":
            return sa.false()
        if agent.owner_email != owner_email:
            from cognis.core.project_access import (
                resolve_agent_use_grant,
                resolve_effective_project_id,
            )

            project_id = await resolve_effective_project_id(
                session, conversation=conversation, agent_id=agent_id, user_email=owner_email
            )
            if (
                await resolve_agent_use_grant(
                    session, agent_id=agent_id, user_email=owner_email, project_id=project_id
                )
                is None
            ):
                return sa.false()
            # The grant permits using the agent, not reading its owner's content.
            # All content rules below remain scoped to the acting user's email.
    ref_id = model.artifact_id if model is ArtifactRecordRow else model.deliverable_id
    rules = []
    if include_work_provenance:
        nodes = _work_nodes(owner_email=owner_email, agent_id=agent_id, session_id=session_id)
        provenance = sa.or_(
            (sa.literal("s:") + model.session_id).in_(sa.select(nodes.c.node)),
            sa.and_(
                model.session_id.is_(None),
                (sa.literal("c:") + model.conversation_id).in_(sa.select(nodes.c.node)),
            ),
        )
        if model is not ArtifactRecordRow:
            provenance = sa.or_(
                provenance,
                model.step_run_id.in_(
                    sa.select(StepRun.step_run_id).where(
                        (sa.literal("t:") + StepRun.task_id).in_(sa.select(nodes.c.node))
                    )
                ),
            )
        rules.append(provenance)
    if agent_id.startswith("system:"):
        assert current is not None
        scope_recipient = f"scope:{current.artifact_scope_id or current.session_id}"
        rules.append(
            sa.exists().where(
                ArtifactGrantRow.owner_email == owner_email,
                ArtifactGrantRow.content_ref == ref_id,
                ArtifactGrantRow.agent_id == scope_recipient,
            )
        )
    if not agent_id.startswith("system:"):
        rules.extend(
            [
                model.owner_agent_id == agent_id,
                sa.exists().where(
                    ArtifactGrantRow.owner_email == owner_email,
                    ArtifactGrantRow.content_ref == ref_id,
                    ArtifactGrantRow.agent_id == agent_id,
                ),
            ]
        )
    from cognis.knowledgebase.access import (
        KnowledgebaseAccessContext,
        list_available_knowledgebases,
    )

    kb_agent_id: str | None = agent_id
    if agent_id.startswith("system:"):
        assert current is not None
        from cognis.core.artifact_entitlements import effective_kb_agent

        kb_agent_id = await session.run_sync(effective_kb_agent, current)
    if kb_agent_id:
        knowledgebases = await list_available_knowledgebases(
            session,
            context=KnowledgebaseAccessContext(actor_email=owner_email, agent_id=kb_agent_id),
        )
        if knowledgebases:
            rules.append(
                sa.exists().where(
                    KnowledgebaseArtifactRow.artifact_id == ref_id,
                    KnowledgebaseArtifactRow.knowledgebase_id.in_(
                        [kb.knowledgebase_id for kb in knowledgebases]
                    ),
                    KnowledgebaseArtifactRow.status.not_in(("deleted", "detached", "removed")),
                )
            )
    return sa.and_(model.owner_email == owner_email, sa.or_(*rules))


async def artifact_authorized_for_conversation(
    session: AsyncSession,
    *,
    artifact: Any | None,
    owner_email: str | None,
    conversation_id: str | None,
    agent_id: str | None = None,
    session_id: str | None = None,
) -> bool:
    """Authorize persisted artifact bytes without loading them."""
    if artifact is None or artifact.status == "deleted" or artifact.deleted_at is not None:
        return False
    expires = artifact.expires_at
    if expires is not None and expires.replace(tzinfo=expires.tzinfo or UTC) <= datetime.now(UTC):
        return False
    allowed = await readable_artifact_ids(
        session,
        [artifact.artifact_id],
        owner_email=owner_email,
        conversation_id=conversation_id,
        agent_id=agent_id,
        session_id=session_id,
    )
    return artifact.artifact_id in allowed
