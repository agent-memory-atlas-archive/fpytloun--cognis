"""Persistence for project agents, project roles, and project-scoped listings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from cognis.core.long_lived_chat import (
    AGENT_DIRECT_CONTEXT_REF_PREFIX,
    NON_CHANNEL_CONTEXT_TYPES,
    WEB_MAIN_CONTEXT_REF_PREFIX,
    WEB_MAIN_CONTEXT_REF_SUFFIX,
)
from cognis.store.models import (
    DELIVERABLE_LIVE_STATUSES,
    Agent,
    ArtifactRecordRow,
    Conversation,
    DeliverableRow,
    ProjectAgentRow,
    ProjectGrantRow,
    ProjectRow,
    StepRun,
    Task,
)

PROJECT_ROLE_VALUES = ("viewer", "member", "manager")


async def latest_visible_project_activity(
    session: AsyncSession, project_id: str, *, viewer_email: str
) -> datetime | None:
    """Return activity from readable resources, using canonical history queries."""
    conversations = await list_project_conversations(
        session, project_id, viewer_email=viewer_email, limit=1
    )
    tasks = await list_project_tasks(session, project_id, viewer_email=viewer_email, limit=1)
    deliverables = await list_project_deliverables(
        session, project_id, viewer_email=viewer_email, limit=1
    )
    artifacts = await list_project_artifacts(
        session, project_id, viewer_email=viewer_email, limit=1
    )
    timestamps = [
        *(row.last_message_at or row.created_at for row in conversations),
        *(row.updated_at for row in tasks),
        *(row.created_at for row, _ in deliverables),
        *(row.created_at for row in artifacts),
    ]
    from datetime import UTC

    return max(
        (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value
            for value in timestamps
            if value
        ),
        default=None,
    )


# Roles whose holders may use project agents and create project work.
PROJECT_USE_PERMISSIONS = ("member", "manager", "use")
_LISTED_ARTIFACT_PURPOSES = ("tool_artifact", "chat_input", "channel_input")
_LISTED_DELIVERABLE_STATUSES = ("approved", "delivered")
_MANAGED_CONTEXT_TYPES = ("agent_work", "managed_agent_conversation")


def shared_conversation_clause(user_email: str) -> Any:
    """Explicit shared project topics visible without permission to use their agent."""
    grants = select(ProjectGrantRow.project_id).where(
        ProjectGrantRow.grantee_type == "user",
        ProjectGrantRow.grantee_user_email == user_email,
        ProjectGrantRow.revoked_at.is_(None),
        ProjectGrantRow.permission.in_(("viewer", "member", "manager", "use")),
    )
    projects = select(ProjectRow.project_id).where(
        ProjectRow.status != "deleted",
        sa.or_(ProjectRow.owner_email == user_email, ProjectRow.project_id.in_(grants)),
    )
    from cognis.store.queries import topic_conversation_clause

    return sa.and_(
        Conversation.user_email != user_email,
        Conversation.visibility == "project",
        Conversation.project_id.in_(projects),
        topic_conversation_clause(),
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- Grants / roles ---


async def update_project_grant_permission(
    session: AsyncSession, grant_id: str, permission: str
) -> ProjectGrantRow | None:
    """Change the role of an active project grant."""

    row = await session.get(ProjectGrantRow, grant_id)
    if row is None or row.revoked_at is not None:
        return None
    row.permission = permission
    await session.flush()
    return row


async def revoke_active_project_grants_for_user(
    session: AsyncSession, project_id: str, user_email: str
) -> int:
    """Revoke every active grant a user holds on a project (leave or removal)."""

    result = await session.execute(
        update(ProjectGrantRow)
        .where(
            ProjectGrantRow.project_id == project_id,
            ProjectGrantRow.grantee_type == "user",
            ProjectGrantRow.grantee_user_email == user_email,
            ProjectGrantRow.revoked_at.is_(None),
        )
        .values(revoked_at=_utcnow())
        .execution_options(synchronize_session=False)
    )
    await session.flush()
    return int(getattr(result, "rowcount", 0) or 0)


async def list_active_project_grants(
    session: AsyncSession, project_id: str
) -> list[ProjectGrantRow]:
    """List active (non-revoked) grants for a project."""

    result = await session.execute(
        select(ProjectGrantRow)
        .where(ProjectGrantRow.project_id == project_id, ProjectGrantRow.revoked_at.is_(None))
        .order_by(ProjectGrantRow.granted_at.asc(), ProjectGrantRow.grant_id.asc())
    )
    return list(result.scalars().all())


# --- Project agents ---


async def get_project_agent(
    session: AsyncSession, project_id: str, agent_id: str
) -> ProjectAgentRow | None:
    """Return one project agent assignment."""

    return await session.get(ProjectAgentRow, {"project_id": project_id, "agent_id": agent_id})


async def list_project_agents(
    session: AsyncSession, project_id: str
) -> list[tuple[ProjectAgentRow, Agent]]:
    """List agents assigned to a project together with their agent rows."""

    result = await session.execute(
        select(ProjectAgentRow, Agent)
        .join(Agent, Agent.agent_id == ProjectAgentRow.agent_id)
        .where(ProjectAgentRow.project_id == project_id)
        .order_by(ProjectAgentRow.is_default.desc(), Agent.name.asc(), Agent.agent_id.asc())
    )
    return [(assignment, agent) for assignment, agent in result.all()]


async def list_agent_project_assignments(
    session: AsyncSession, agent_id: str
) -> list[tuple[ProjectAgentRow, ProjectRow]]:
    """List non-deleted projects an agent is assigned to."""

    result = await session.execute(
        select(ProjectAgentRow, ProjectRow)
        .join(ProjectRow, ProjectRow.project_id == ProjectAgentRow.project_id)
        .where(ProjectAgentRow.agent_id == agent_id, ProjectRow.status != "deleted")
        .order_by(ProjectAgentRow.is_default.desc(), ProjectRow.name.asc())
    )
    return [(assignment, project) for assignment, project in result.all()]


async def upsert_project_agent(
    session: AsyncSession,
    *,
    project_id: str,
    agent_id: str,
    added_by: str,
    executor_scope: str | None = None,
    is_default: bool | None = None,
) -> ProjectAgentRow:
    """Create or update an assignment.

    Setting a new default clears the agent's previous default in the same
    transaction so the partial unique index never observes two defaults.
    """

    if is_default:
        await session.execute(
            update(ProjectAgentRow)
            .where(
                ProjectAgentRow.agent_id == agent_id,
                ProjectAgentRow.project_id != project_id,
                ProjectAgentRow.is_default.is_(True),
            )
            .values(is_default=False, updated_at=_utcnow())
            .execution_options(synchronize_session=False)
        )
        await session.flush()
    row = await get_project_agent(session, project_id, agent_id)
    if row is None:
        row = ProjectAgentRow(
            project_id=project_id,
            agent_id=agent_id,
            added_by=added_by,
            executor_scope=executor_scope or "owner_executor",
            is_default=bool(is_default),
        )
        session.add(row)
    else:
        if executor_scope is not None:
            row.executor_scope = executor_scope
        if is_default is not None:
            row.is_default = is_default
        row.updated_at = _utcnow()
    await session.flush()
    return row


async def remove_project_agent(session: AsyncSession, project_id: str, agent_id: str) -> bool:
    """Remove an agent assignment from a project."""

    result = await session.execute(
        delete(ProjectAgentRow).where(
            ProjectAgentRow.project_id == project_id, ProjectAgentRow.agent_id == agent_id
        )
    )
    await session.flush()
    return int(getattr(result, "rowcount", 0) or 0) > 0


async def get_default_project_for_agent(session: AsyncSession, agent_id: str) -> ProjectRow | None:
    """Return the active default project of an agent, if any."""

    result = await session.execute(
        select(ProjectRow)
        .join(ProjectAgentRow, ProjectAgentRow.project_id == ProjectRow.project_id)
        .where(
            ProjectAgentRow.agent_id == agent_id,
            ProjectAgentRow.is_default.is_(True),
            ProjectRow.status == "active",
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_default_agent_ids_for_project(session: AsyncSession, project_id: str) -> list[str]:
    """Return agents whose default project is ``project_id``."""

    result = await session.execute(
        select(ProjectAgentRow.agent_id).where(
            ProjectAgentRow.project_id == project_id, ProjectAgentRow.is_default.is_(True)
        )
    )
    return [str(item) for item in result.scalars().all()]


def _member_project_ids(user_email: str) -> Any:
    return select(ProjectGrantRow.project_id).where(
        ProjectGrantRow.grantee_type == "user",
        ProjectGrantRow.grantee_user_email == user_email,
        ProjectGrantRow.revoked_at.is_(None),
        ProjectGrantRow.permission.in_(PROJECT_USE_PERMISSIONS),
    )


async def get_project_agent_use_assignment(
    session: AsyncSession, *, agent_id: str, user_email: str, project_id: str
) -> ProjectAgentRow | None:
    """Return the assignment that lets ``user_email`` use an agent inside a project.

    Requires an active project, the agent assigned to it, and the user being
    the project owner or holding a member/manager grant.
    """

    result = await session.execute(
        select(ProjectAgentRow)
        .join(ProjectRow, ProjectRow.project_id == ProjectAgentRow.project_id)
        .where(
            ProjectAgentRow.agent_id == agent_id,
            ProjectAgentRow.project_id == project_id,
            ProjectRow.status == "active",
            sa.or_(
                ProjectRow.owner_email == user_email,
                ProjectRow.project_id.in_(_member_project_ids(user_email)),
            ),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def user_has_any_project_agent_access(
    session: AsyncSession, *, agent_id: str, user_email: str
) -> bool:
    """Return whether any project grants the user use of an agent (display-only checks)."""

    result = await session.execute(
        select(ProjectAgentRow.project_id)
        .join(ProjectRow, ProjectRow.project_id == ProjectAgentRow.project_id)
        .where(
            ProjectAgentRow.agent_id == agent_id,
            ProjectRow.status == "active",
            sa.or_(
                ProjectRow.owner_email == user_email,
                ProjectRow.project_id.in_(_member_project_ids(user_email)),
            ),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def list_project_shared_agents_for_user(
    session: AsyncSession, user_email: str, *, project_id: str | None = None
) -> list[tuple[Agent, ProjectAgentRow, ProjectRow]]:
    """List agents usable by a user only through project assignments.

    Agents owned by the user are excluded; they never need derived access.
    """

    stmt = (
        select(Agent, ProjectAgentRow, ProjectRow)
        .join(ProjectAgentRow, ProjectAgentRow.agent_id == Agent.agent_id)
        .join(ProjectRow, ProjectRow.project_id == ProjectAgentRow.project_id)
        .where(
            ProjectRow.status == "active",
            Agent.owner_email != user_email,
            sa.or_(
                ProjectRow.owner_email == user_email,
                ProjectRow.project_id.in_(_member_project_ids(user_email)),
            ),
        )
        .order_by(ProjectRow.name.asc(), Agent.name.asc())
    )
    if project_id is not None:
        stmt = stmt.where(ProjectRow.project_id == project_id)
    result = await session.execute(stmt)
    return [(agent, assignment, project) for agent, assignment, project in result.all()]


# --- Project resource listings ---


def _visible_to(model: Any, author_column: Any, viewer_email: str) -> sa.ColumnElement[bool]:
    return sa.or_(author_column == viewer_email, model.visibility == "project")


def _exclude_task_control() -> sa.ColumnElement[bool]:
    return sa.or_(
        Conversation.context_data.is_(None),
        Conversation.context_data["kind"].as_string().is_(None),
        Conversation.context_data["kind"].as_string() != "task_control",
    )


def long_lived_conversation_clause() -> sa.ColumnElement[bool]:
    """SQL form of :func:`cognis.core.long_lived_chat.is_long_lived_chat_context`."""

    return sa.or_(
        Conversation.context_type.not_in(tuple(sorted(NON_CHANNEL_CONTEXT_TYPES))),
        sa.and_(
            Conversation.context_type == "web",
            sa.or_(
                Conversation.context_ref.like(f"{AGENT_DIRECT_CONTEXT_REF_PREFIX}%"),
                sa.and_(
                    Conversation.context_ref.like(f"{WEB_MAIN_CONTEXT_REF_PREFIX}%"),
                    Conversation.context_ref.like(f"%{WEB_MAIN_CONTEXT_REF_SUFFIX}"),
                ),
            ),
        ),
    )


def _readable_project_conversation_ids(project_id: str, viewer_email: str) -> Any:
    return select(Conversation.conversation_id).where(
        Conversation.project_id == project_id,
        Conversation.status != "deleted",
        _visible_to(Conversation, Conversation.user_email, viewer_email),
    )


async def list_project_conversations(
    session: AsyncSession,
    project_id: str,
    *,
    viewer_email: str,
    default_agent_ids: list[str] | None = None,
    agent_id: str | None = None,
    limit: int = 50,
    before: tuple[datetime, str] | None = None,
    shared_only: bool = False,
    topics_only: bool = False,
) -> list[Conversation]:
    """List project conversations readable by ``viewer_email``.

    Topic conversations match by stored ``project_id``. Long-lived chats of
    agents whose default project is this project are included for their own
    author only, because their project is derived rather than shared.
    """

    clauses: list[Any] = [
        sa.and_(
            Conversation.project_id == project_id,
            _visible_to(Conversation, Conversation.user_email, viewer_email),
        )
    ]
    if default_agent_ids:
        clauses.append(
            sa.and_(
                Conversation.project_id.is_(None),
                Conversation.user_email == viewer_email,
                Conversation.agent_id.in_(default_agent_ids),
                long_lived_conversation_clause(),
            )
        )
    stmt = select(Conversation).where(
        sa.or_(*clauses),
        Conversation.status != "deleted",
        _exclude_task_control(),
        Conversation.context_type.not_in(_MANAGED_CONTEXT_TYPES),
    )
    if agent_id:
        stmt = stmt.where(Conversation.agent_id == agent_id)
    if topics_only:
        # Filter before LIMIT/keyset boundaries so task-heavy projects cannot
        # consume the conversation page with invisible workflow/session rows.
        kind = sa.func.coalesce(Conversation.context_data["kind"].as_string(), "")
        stmt = stmt.where(
            Conversation.status == "active",
            Conversation.context_type == "web",
            sa.not_(sa.func.coalesce(long_lived_conversation_clause(), sa.false())),
            kind.not_in(("task_control", "agent_work", "managed_agent_conversation")),
        )
    if shared_only:
        stmt = stmt.where(Conversation.visibility == "project")
    if before:
        timestamp = sa.func.coalesce(Conversation.last_message_at, Conversation.created_at)
        stmt = stmt.where(
            sa.or_(
                timestamp < before[0],
                sa.and_(timestamp == before[0], Conversation.conversation_id < before[1]),
            )
        )
    stmt = stmt.order_by(
        sa.func.coalesce(Conversation.last_message_at, Conversation.created_at).desc(),
        Conversation.conversation_id.desc(),
    ).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_project_tasks(
    session: AsyncSession,
    project_id: str,
    *,
    viewer_email: str,
    limit: int = 50,
    before: tuple[datetime, str] | None = None,
) -> list[Task]:
    """List project tasks readable by ``viewer_email``."""

    stmt = select(Task).where(
        Task.project_id == project_id,
        _visible_to(Task, Task.created_by, viewer_email),
    )
    if before:
        stmt = stmt.where(
            sa.or_(
                Task.updated_at < before[0],
                sa.and_(Task.updated_at == before[0], Task.task_id < before[1]),
            )
        )
    result = await session.execute(
        stmt.order_by(Task.updated_at.desc(), Task.task_id.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def list_project_deliverables(
    session: AsyncSession,
    project_id: str,
    *,
    viewer_email: str,
    limit: int = 20,
) -> list[tuple[DeliverableRow, str | None]]:
    """Recent deliverables from readable project conversations and tasks, plus
    documents stored in the project. Only the latest revision of each lineage.

    Returns ``(deliverable, task_id)`` pairs.
    """

    successor = aliased(DeliverableRow)
    visible_tasks = select(Task.task_id).where(
        Task.project_id == project_id,
        _visible_to(Task, Task.created_by, viewer_email),
    )
    result = await session.execute(
        select(DeliverableRow, StepRun.task_id)
        .outerjoin(StepRun, StepRun.step_run_id == DeliverableRow.step_run_id)
        .where(
            sa.or_(
                sa.and_(
                    sa.or_(
                        DeliverableRow.conversation_id.in_(
                            _readable_project_conversation_ids(project_id, viewer_email)
                        ),
                        StepRun.task_id.in_(visible_tasks),
                    ),
                    DeliverableRow.status.in_(_LISTED_DELIVERABLE_STATUSES),
                ),
                sa.and_(
                    DeliverableRow.project_id == project_id,
                    DeliverableRow.status.in_(DELIVERABLE_LIVE_STATUSES),
                ),
            ),
            ~sa.exists().where(
                successor.supersedes_deliverable_id == DeliverableRow.deliverable_id,
                successor.status.in_(DELIVERABLE_LIVE_STATUSES),
            ),
        )
        .order_by(DeliverableRow.created_at.desc(), DeliverableRow.deliverable_id.desc())
        .limit(limit)
    )
    return [(row, task_id) for row, task_id in result.all()]


async def list_project_artifacts(
    session: AsyncSession,
    project_id: str,
    *,
    viewer_email: str,
    limit: int = 20,
) -> list[ArtifactRecordRow]:
    """Recent artifacts attached to readable project conversations, plus documents
    stored in the project. Only the latest revision of each lineage."""

    now = _utcnow()
    successor = aliased(ArtifactRecordRow)
    result = await session.execute(
        select(ArtifactRecordRow)
        .where(
            sa.or_(
                sa.and_(
                    ArtifactRecordRow.conversation_id.in_(
                        _readable_project_conversation_ids(project_id, viewer_email)
                    ),
                    ArtifactRecordRow.purpose.in_(_LISTED_ARTIFACT_PURPOSES),
                ),
                sa.and_(
                    ArtifactRecordRow.project_id == project_id,
                    ArtifactRecordRow.purpose != "conversation_deliverable",
                ),
            ),
            ArtifactRecordRow.status != "deleted",
            ArtifactRecordRow.deleted_at.is_(None),
            ~sa.exists().where(
                successor.supersedes_artifact_id == ArtifactRecordRow.artifact_id,
                successor.status != "deleted",
                successor.deleted_at.is_(None),
            ),
            sa.or_(ArtifactRecordRow.expires_at.is_(None), ArtifactRecordRow.expires_at > now),
        )
        .order_by(ArtifactRecordRow.created_at.desc(), ArtifactRecordRow.artifact_id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def make_author_project_resources_private(
    session: AsyncSession, project_id: str, author_email: str
) -> int:
    """Set every conversation and task an author has in a project to private."""

    changed = 0
    for stmt in (
        update(Conversation)
        .where(Conversation.project_id == project_id, Conversation.user_email == author_email)
        .values(visibility="private"),
        update(Task)
        .where(Task.project_id == project_id, Task.created_by == author_email)
        .values(visibility="private"),
    ):
        result = await session.execute(stmt.execution_options(synchronize_session=False))
        changed += int(getattr(result, "rowcount", 0) or 0)
    await session.flush()
    return changed
