"""Human-facing content discovery, independent of agent runtime scopes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import InstrumentedAttribute, aliased

from cognis.store.models import (
    DELIVERABLE_LIVE_STATUSES,
    Agent,
    ArtifactRecordRow,
    Conversation,
    DeliverableRow,
    ManagedConversationLink,
    ProjectGrantRow,
    ProjectRow,
    Session,
    StepRun,
    Task,
)


def readable_projects(user_email: str) -> Any:
    """Projects a person may read; administrative status grants no content access."""
    grants = sa.select(ProjectGrantRow.project_id).where(
        ProjectGrantRow.grantee_type == "user",
        ProjectGrantRow.grantee_user_email == user_email,
        ProjectGrantRow.revoked_at.is_(None),
        ProjectGrantRow.permission.in_(("viewer", "member", "manager", "use")),
    )
    return sa.select(ProjectRow.project_id).where(
        ProjectRow.status != "deleted",
        sa.or_(ProjectRow.owner_email == user_email, ProjectRow.project_id.in_(grants)),
    )


def human_content_clause(model: Any, user_email: str) -> Any:
    """SQL equivalent of human owner/project reads, including legacy source scope."""
    projects = readable_projects(user_email)
    conversations = sa.select(Conversation.conversation_id).where(
        Conversation.visibility == "project",
        Conversation.project_id.in_(projects),
        Conversation.context_type.not_in(("agent_work", "managed_agent_conversation")),
        ~sa.exists().where(
            ManagedConversationLink.target_conversation_id == Conversation.conversation_id
        ),
    )
    shared = sa.or_(model.project_id.in_(projects), model.conversation_id.in_(conversations))
    if model is DeliverableRow:
        shared = sa.or_(
            shared,
            model.step_run_id.in_(
                sa.select(StepRun.step_run_id)
                .join(Task, Task.task_id == StepRun.task_id)
                .where(Task.visibility == "project", Task.project_id.in_(projects))
            ),
        )
        shared = sa.and_(
            shared,
            ~sa.exists().where(
                ManagedConversationLink.target_conversation_id == model.conversation_id
            ),
        )
    return sa.or_(model.owner_email == user_email, shared)


def discoverable_content_clause(model: Any, *, exact: bool = False) -> Any:
    """Current Library revisions, shared by browsing and lightweight name search."""
    if model is DeliverableRow:
        successor_d = aliased(DeliverableRow)
        return (
            sa.true()
            if exact
            else sa.and_(
                model.status.in_(DELIVERABLE_LIVE_STATUSES),
                ~sa.exists().where(
                    successor_d.supersedes_deliverable_id == model.deliverable_id,
                    successor_d.status.in_(DELIVERABLE_LIVE_STATUSES),
                ),
            )
        )
    successor_a = aliased(ArtifactRecordRow)

    def live(row: Any) -> Any:
        return sa.and_(
            row.status != "deleted",
            row.deleted_at.is_(None),
            sa.or_(row.expires_at.is_(None), row.expires_at > datetime.now(UTC)),
            row.purpose != "conversation_deliverable",
            row.namespace.not_in(("avatars", "tool_outputs")),
        )

    return sa.and_(
        live(model),
        sa.true()
        if exact
        else sa.and_(
            model.status != "temporary",
            ~sa.exists().where(
                sa.or_(
                    successor_a.lineage_id == sa.func.coalesce(model.lineage_id, model.artifact_id),
                    sa.and_(
                        successor_a.lineage_id.is_(None),
                        successor_a.artifact_id
                        == sa.func.coalesce(model.lineage_id, model.artifact_id),
                    ),
                ),
                successor_a.revision > model.revision,
                successor_a.status != "temporary",
                live(successor_a),
            ),
        ),
    )


def content_origin_clause(model: Any) -> Any:
    """Canonical producer classification; attachment context is not authorship."""
    if model is DeliverableRow:
        return sa.literal("agent")
    return sa.case(
        (
            sa.or_(
                model.message_role == "user",
                model.purpose.in_(("chat_input", "channel_input")),
            ),
            "user",
        ),
        (
            sa.or_(model.message_role == "assistant", model.source_tool_call_id.is_not(None)),
            "agent",
        ),
        else_="other",
    )


def library_items(user_email: str, kind: str, *, exact: bool = False) -> Any:
    """Normalized metadata projection. Never reads object storage or message content."""
    model = DeliverableRow if kind == "deliverable" else ArtifactRecordRow
    # Match work_project's bounded parent-session lookup, including specialist
    # output. Keep one nearest task per producer instead of multiplying rows.
    parent = aliased(Session)
    ancestors = (
        sa.select(
            Session.session_id.label("producer_id"),
            Session.session_id,
            Session.parent_session_id,
            Session.user_email,
            sa.literal(0).label("depth"),
        )
        .where(
            Session.session_id.in_(
                sa.select(model.session_id).where(human_content_clause(model, user_email))
            )
        )
        .cte("library_session_ancestors", recursive=True)
    )
    ancestors = ancestors.union_all(
        sa.select(
            ancestors.c.producer_id,
            parent.session_id,
            parent.parent_session_id,
            parent.user_email,
            ancestors.c.depth + 1,
        )
        .join(
            parent,
            sa.and_(
                parent.session_id == ancestors.c.parent_session_id,
                parent.user_email == ancestors.c.user_email,
            ),
        )
        .where(ancestors.c.depth < 15)
    )
    session_task_id = (
        sa.select(StepRun.task_id)
        .join(ancestors, ancestors.c.session_id == StepRun.session_id)
        .join(Task, Task.task_id == StepRun.task_id)
        .where(
            ancestors.c.producer_id == model.session_id,
            ancestors.c.user_email == model.owner_email,
            Task.created_by == model.owner_email,
        )
        .order_by(ancestors.c.depth, StepRun.step_run_id)
        .limit(1)
        .correlate(model)
        .scalar_subquery()
    )
    ref = DeliverableRow.deliverable_id if kind == "deliverable" else ArtifactRecordRow.artifact_id
    projects = readable_projects(user_email)
    source_readable = sa.or_(
        Conversation.user_email == user_email,
        sa.and_(
            Conversation.visibility == "project",
            Conversation.project_id.in_(projects),
            Conversation.context_type.not_in(("agent_work", "managed_agent_conversation")),
        ),
    )
    task_readable = sa.or_(
        Task.created_by == user_email,
        sa.and_(Task.visibility == "project", Task.project_id.in_(projects)),
    )
    project_id = sa.case(
        (model.project_id.in_(projects), model.project_id),
        else_=sa.func.coalesce(Conversation.project_id, Task.project_id),
    )
    source_id = sa.case(
        (Task.task_id.is_not(None), sa.literal("task:") + Task.task_id),
        else_=Conversation.conversation_id,
    )
    source_title = sa.case(
        (
            Task.task_id.is_not(None),
            sa.literal("Task: ") + sa.func.coalesce(Task.title, "Untitled task"),
        ),
        else_=Conversation.title,
    )
    # Only readable provenance is joined: document access alone does not expose
    # a private source's title, task ID, or project metadata.
    fields: list[sa.ColumnElement[Any] | InstrumentedAttribute[Any]] = [
        ref.label("id"),
        sa.literal(kind).label("kind"),
        (DeliverableRow.title if kind == "deliverable" else ArtifactRecordRow.filename).label(
            "title"
        ),
        (DeliverableRow.format if kind == "deliverable" else ArtifactRecordRow.mime_type).label(
            "format"
        ),
        model.owner_email,
        model.owner_agent_id.label("agent_id"),
        sa.func.coalesce(Agent.display_name, Agent.name).label("agent_name"),
        project_id.label("project_id"),
        ProjectRow.name.label("project_name"),
        Conversation.conversation_id,
        Conversation.title.label("conversation_title"),
        Task.task_id,
        Task.title.label("task_title"),
        source_id.label("source_id"),
        source_title.label("source_title"),
        model.lineage_id,
        model.revision,
        model.created_at,
        model.updated_at,
        (
            DeliverableRow.content_size if kind == "deliverable" else ArtifactRecordRow.size_bytes
        ).label("size_bytes"),
        model.status,
        content_origin_clause(model).label("origin"),
    ]
    stmt = (
        sa.select(*fields)
        .select_from(model)
        .outerjoin(
            Conversation,
            sa.and_(Conversation.conversation_id == model.conversation_id, source_readable),
        )
    )
    if kind == "deliverable":
        stmt = stmt.outerjoin(StepRun, StepRun.step_run_id == DeliverableRow.step_run_id).outerjoin(
            Task,
            sa.and_(
                Task.task_id == sa.func.coalesce(StepRun.task_id, session_task_id), task_readable
            ),
        )
    else:
        stmt = stmt.outerjoin(Task, sa.and_(Task.task_id == session_task_id, task_readable))
    stmt = (
        stmt.outerjoin(
            ProjectRow,
            sa.and_(ProjectRow.project_id == project_id, ProjectRow.project_id.in_(projects)),
        )
        .outerjoin(Agent, Agent.agent_id == model.owner_agent_id)
        .where(human_content_clause(model, user_email))
    )
    stmt = stmt.where(discoverable_content_clause(model, exact=exact))
    return stmt.subquery()
