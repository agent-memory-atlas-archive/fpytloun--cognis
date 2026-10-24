"""Informational inbox ownership and post-commit delivery.

Producers stage rows in the same transaction as the operation they describe.
Read state is monotonic and recipient-scoped. Realtime and push are best-effort
post-commit hints; the database inbox is authoritative on reconnect and refresh.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognis.core.events import Event, EventBus, EventType
from cognis.store.models import InboxNotificationRow


class InboxItem(BaseModel):
    """Public, recipient-safe notification projection."""

    notification_id: str
    kind: str
    title: str
    body: str
    href: str
    created_at: datetime
    read_at: datetime | None = None

    @classmethod
    def from_row(cls, row: InboxNotificationRow) -> InboxItem:
        """Project a durable row without exposing recipient identity."""
        values = {name: getattr(row, name) for name in cls.model_fields}
        # SQLite drops timezone information from TIMESTAMP columns.
        for name in ("created_at", "read_at"):
            value = values[name]
            if value is not None and value.tzinfo is None:
                values[name] = value.replace(tzinfo=UTC)
        return cls(**values)


class InboxPage(BaseModel):
    """Bounded inbox page with an authoritative total unread count."""

    items: list[InboxItem]
    unread_count: int
    next_cursor: str | None = None


def stage_notification(
    session: AsyncSession,
    *,
    user_email: str,
    kind: str,
    title: str,
    body: str,
    href: str,
) -> InboxNotificationRow:
    """Stage an entry without committing the caller's work."""
    if (
        not href.startswith("/")
        or href.startswith("//")
        or "\\" in href
        or any(ord(c) < 32 for c in href)
    ):
        raise ValueError("Inbox targets must be app-relative URLs")
    row = InboxNotificationRow(
        notification_id=f"inbox_{uuid.uuid4().hex}",
        user_email=user_email,
        kind=kind,
        title=title[:200],
        body=body[:2000],
        href=href,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    return row


def stage_share_notification(
    session: AsyncSession,
    *,
    recipient: str | None,
    actor: str,
    resource_type: Literal["agent", "project", "knowledgebase"],
    resource_id: str,
    resource_name: str,
    change: Literal["shared", "updated", "revoked"],
) -> InboxNotificationRow | None:
    """Describe an effective access transition, excluding self notifications."""
    if not recipient or recipient == actor:
        return None
    label = {"agent": "agent", "project": "project", "knowledgebase": "knowledge base"}[
        resource_type
    ]
    title = {
        "shared": f"{label.capitalize()} shared with you",
        "updated": f"{label.capitalize()} access updated",
        "revoked": f"{label.capitalize()} access removed",
    }[change]
    action = {
        "shared": "shared",
        "updated": "updated your access to",
        "revoked": "removed your access to",
    }[change]
    prefix = {"agent": "agents", "project": "projects", "knowledgebase": "knowledge"}[resource_type]
    return stage_notification(
        session,
        user_email=recipient,
        kind=f"sharing.{resource_type}.{change}",
        title=title,
        body=f"{actor} {action} {label} “{resource_name}”.",
        href="/notifications"
        if change == "revoked"
        else f"/{prefix}/{quote(resource_id, safe='')}",
    )


async def publish_notification(
    event_bus: EventBus | None, row: InboxNotificationRow | None
) -> None:
    """Emit the committed pointer; the inbox owner handles realtime delivery."""
    if event_bus is not None and row is not None:
        await event_bus.publish(
            Event(
                type=EventType.INBOX_CREATED,
                data={"user_email": row.user_email, "notification_id": row.notification_id},
            )
        )


class InboxService:
    """Recipient-scoped inbox reads, acknowledgement, and delivery hints."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], event_bus: EventBus
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus
        self.cluster_signals: Any = None
        event_bus.subscribe(EventType.INBOX_CREATED, self._handle_created)

    async def publish(self, row: InboxNotificationRow | None) -> None:
        """Publish after the producer has committed and released its session."""
        await publish_notification(self._event_bus, row)

    async def _handle_created(self, event: Event) -> None:
        async with self._session_factory() as session:
            row = await session.get(InboxNotificationRow, event.data.get("notification_id"))
            if row is None or row.user_email != event.data.get("user_email"):
                return
            user_email = row.user_email
        await self._publish_change(user_email)

    async def _publish_change(self, user_email: str) -> None:
        await self._event_bus.publish(
            Event(type=EventType.INBOX_CHANGED, data={"user_email": user_email})
        )
        if self.cluster_signals is not None:
            from cognis.core.cluster_signals import ClusterSignalKind, ClusterSignalScope

            await self.cluster_signals.publish(
                ClusterSignalKind.INBOX_CHANGED,
                scope=ClusterSignalScope(owner_token=self.cluster_signals.owner_token(user_email)),
                revision=uuid.uuid4().hex,
            )

    async def list_page(
        self, user_email: str, *, cursor: str | None = None, unread: bool = False, limit: int = 30
    ) -> InboxPage:
        """Read newest-first; cursors never cross recipient boundaries."""
        async with self._session_factory() as session:
            predicates = [InboxNotificationRow.user_email == user_email]
            if unread:
                predicates.append(InboxNotificationRow.read_at.is_(None))
            if cursor:
                anchor = await session.scalar(
                    select(InboxNotificationRow).where(
                        InboxNotificationRow.user_email == user_email,
                        InboxNotificationRow.notification_id == cursor,
                    )
                )
                if anchor is None:
                    raise ValueError("Invalid inbox cursor")
                predicates.append(
                    or_(
                        InboxNotificationRow.created_at < anchor.created_at,
                        and_(
                            InboxNotificationRow.created_at == anchor.created_at,
                            InboxNotificationRow.notification_id < anchor.notification_id,
                        ),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        select(InboxNotificationRow)
                        .where(*predicates)
                        .order_by(
                            InboxNotificationRow.created_at.desc(),
                            InboxNotificationRow.notification_id.desc(),
                        )
                        .limit(limit + 1)
                    )
                ).all()
            )
            unread_count = await session.scalar(
                select(func.count())
                .select_from(InboxNotificationRow)
                .where(
                    InboxNotificationRow.user_email == user_email,
                    InboxNotificationRow.read_at.is_(None),
                )
            )
            return InboxPage(
                items=[InboxItem.from_row(row) for row in rows[:limit]],
                unread_count=unread_count or 0,
                next_cursor=rows[limit - 1].notification_id if len(rows) > limit else None,
            )

    async def mark_read(self, user_email: str, ids: list[str]) -> None:
        """Acknowledge explicit visible IDs, preserving concurrently arriving items."""
        async with self._session_factory() as session:
            await session.execute(
                update(InboxNotificationRow)
                .where(
                    InboxNotificationRow.user_email == user_email,
                    InboxNotificationRow.notification_id.in_(ids),
                    InboxNotificationRow.read_at.is_(None),
                )
                .values(read_at=datetime.now(UTC))
            )
            await session.commit()
        await self._publish_change(user_email)
