"""User-scoped navigation counts without page-size-dependent totals."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cognis.api.dashboard_issues import collect_dashboard_issues
from cognis.api.models import NavigationChatGroup, NavigationSummaryResponse
from cognis.store.models import Conversation, NotificationRow, Session, Task
from cognis.store.notification_expiry import notification_is_expired
from cognis.store.queries import conversation_list_filters, topic_conversation_clause


async def collect_navigation_summary(
    session: AsyncSession,
    *,
    user_email: str,
    resolve_active_ids: Callable[[list[str]], Awaitable[set[str]]] | None = None,
) -> NavigationSummaryResponse:
    """Aggregate metadata only; conversation color policy remains in the UI."""
    # Workflow step histories belong to Tasks, not the Chat attention badge.
    # Agent-direct chats have their own sticky avatars, outside the Waiting lane.
    chat_filters = conversation_list_filters(
        user_email, include_task_execution=False, include_agent_direct=False
    )
    chat_filters.append(topic_conversation_clause())
    pending: dict[str, set[str]] = defaultdict(set)
    now = datetime.now(UTC)
    for notification in (
        await session.execute(
            sa.select(NotificationRow)
            .join(Conversation, Conversation.conversation_id == NotificationRow.conversation_id)
            .where(
                NotificationRow.user_email == user_email,
                NotificationRow.status == "pending",
                NotificationRow.notification_type != "agent_question",
                *chat_filters,
            )
        )
    ).scalars():
        if not notification_is_expired(notification, now=now):
            pending[notification.conversation_id].add(notification.notification_type)

    # Group identical attention inputs, not conversation IDs or message data.
    groups: Counter[tuple[str | None, str | None, bool, bool, bool, tuple[str, ...]]] = Counter()
    rows = await session.execute(
        sa.select(
            Conversation.conversation_id,
            Session.status,
            Session.completion_reason,
            sa.and_(
                Session.updated_at.is_not(None),
                Conversation.last_read_at >= Session.updated_at,
            ).label("session_observed"),
            sa.and_(
                Conversation.last_message_at.is_not(None),
                sa.or_(
                    Conversation.last_read_at.is_(None),
                    Conversation.last_message_at > Conversation.last_read_at,
                ),
            ).label("has_unread"),
        )
        .outerjoin(
            Session,
            sa.and_(
                Session.session_id == Conversation.active_session_id,
                Session.user_email == user_email,
                Session.conversation_id == Conversation.conversation_id,
            ),
        )
        .where(*chat_filters)
    )
    inputs = rows.all()
    active_ids = (
        await resolve_active_ids([row[0] for row in inputs]) if resolve_active_ids else set()
    )
    for conversation_id, status, reason, observed, unread in inputs:
        groups[
            (
                status,
                reason,
                bool(observed),
                bool(unread),
                conversation_id in active_ids,
                tuple(sorted(pending.get(conversation_id, ()))),
            )
        ] += 1

    issues = await collect_dashboard_issues(
        session, user_email=user_email, candidate_limit=None, issue_limit=None
    )
    paused_tasks = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Task)
        .where(Task.created_by == user_email, Task.status == "paused")
    )
    return NavigationSummaryResponse(
        chat_groups=[
            NavigationChatGroup(
                active_session_status=status,
                active_session_completion_reason=reason,
                session_observed=observed,
                has_unread=unread,
                is_active=is_active,
                pending_notification_types=list(types),
                count=count,
            )
            for (status, reason, observed, unread, is_active, types), count in groups.items()
        ],
        dashboard=issues.summary,
        schedules=sum(issue.resource.type == "schedule" for issue in issues.issues),
        tasks=paused_tasks or 0,
    )
