"""Durable, idempotent Intaris dispatch for executor pin transition notices."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from cognis.core.events import Event, EventType
from cognis.logging import get_logger
from cognis.models.session import SessionEvent
from cognis.store.models import (
    Conversation,
    ExecutorPinNoticeOutboxRow,
    ExecutorPinTransitionRow,
    ExecutorRecoveryNoticeRow,
)
from cognis.store.queries import get_session_row

logger = get_logger(__name__)


def recovery_notice_idempotency_key(session_id: str, notice_id: str) -> str:
    """Return a stable append identity for new and already-queued notices."""
    key = f"{session_id}:{notice_id}"
    if re.fullmatch(r"[a-zA-Z0-9._:@-]{1,256}", key):
        return key
    # Preserve keys that could have receipts. Invalid keys (notably ISO UTC
    # timestamps containing '+') are rejected by Intaris before any reservation.
    # Hash the persisted identity, not a reconstructed timestamp or payload.
    digest = hashlib.sha256(notice_id.encode()).hexdigest()
    return f"{session_id}:executor_recovery_sha256:{digest}"


class ExecutorPinNoticeDispatcher:
    """Drain the outbox using one stable Intaris idempotency key per generation."""

    def __init__(self, *, session_factory: Any, guardrails: Any, event_bus: Any = None) -> None:
        self.session_factory = session_factory
        self.guardrails = guardrails
        self.event_bus = event_bus

    async def queue_recovery_notice(
        self,
        session: Any,
        *,
        conversation_id: str | None,
        executor_id: str,
        unavailable_since: datetime,
        recovered: bool,
    ) -> None:
        """Queue feedback in the same transaction as the outage transition."""
        if not conversation_id:
            return
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or not conversation.active_session_id:
            return
        session_row = await get_session_row(session, conversation.active_session_id)
        if session_row is None:
            return
        if unavailable_since.tzinfo is None:
            unavailable_since = unavailable_since.replace(tzinfo=UTC)
        state = "recovered" if recovered else "unavailable"
        notice_id = (
            f"executor_recovery:{conversation_id}:{executor_id}:"
            f"{unavailable_since.isoformat()}:{state}"
        )
        insert = postgresql_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        await session.execute(
            insert(ExecutorRecoveryNoticeRow)
            .values(
                notice_id=notice_id,
                conversation_id=conversation_id,
                session_id=session_row.session_id,
                intaris_session_id=session_row.intaris_session_id or session_row.session_id,
                user_email=conversation.user_email,
                agent_id=conversation.agent_id,
                executor_id=executor_id,
                unavailable_since=unavailable_since,
                recovered=recovered,
            )
            .on_conflict_do_nothing(index_elements=["notice_id"])
        )

    async def dispatch_recovery_pending(self, *, limit: int = 50) -> int:
        """Retry durable feedback after failures and controller restarts."""
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(ExecutorRecoveryNoticeRow)
                        .where(ExecutorRecoveryNoticeRow.delivered_at.is_(None))
                        .order_by(
                            ExecutorRecoveryNoticeRow.created_at,
                            ExecutorRecoveryNoticeRow.recovered,
                        )
                        .limit(limit)
                    )
                ).all()
            )
        delivered = 0
        blocked_conversations: set[str] = set()
        for row in rows:
            if row.conversation_id in blocked_conversations:
                continue
            if await self._dispatch_recovery_notice(row):
                delivered += 1
            else:
                # Do not announce recovery before its unavailable notice.
                blocked_conversations.add(row.conversation_id)
        return delivered

    async def flush_recovery_notices(self) -> None:
        """Attempt prompt delivery without allowing optional I/O to stall work."""
        try:
            async with asyncio.timeout(2):
                await self.dispatch_recovery_pending()
        except TimeoutError:
            pass  # The existing periodic outbox worker will retry.

    async def _dispatch_recovery_notice(self, row: ExecutorRecoveryNoticeRow) -> bool:
        try:
            state = "recovered" if row.recovered else "unavailable"
            message = (
                f"Executor '{row.executor_id}' is available again. Recovery wait ended."
                if row.recovered
                else f"Executor '{row.executor_id}' is unavailable. Waiting "
                "for the same executor to recover; you can cancel this turn."
            )
            payload = {
                "event": "system_notice",
                "kind": "executor_recovery",
                "scope": "session",
                "notice_id": row.notice_id,
                "session_id": row.session_id,
                "executor_id": row.executor_id,
                "state": state,
                "message": message,
                "text": message,
                "content": message,
            }
            result = await self.guardrails.record_events(
                session_id=row.intaris_session_id,
                events=[SessionEvent(type="lifecycle", data=payload)],
                source="cognis_executor_recovery",
                idempotency_key=recovery_notice_idempotency_key(
                    row.intaris_session_id, row.notice_id
                ),
                user_email=row.user_email,
                agent_id=row.agent_id,
            )
            if not result.ok:
                return False
            async with self.session_factory() as session:
                updated = await session.execute(
                    update(ExecutorRecoveryNoticeRow)
                    .where(
                        ExecutorRecoveryNoticeRow.notice_id == row.notice_id,
                        ExecutorRecoveryNoticeRow.delivered_at.is_(None),
                    )
                    .values(delivered_at=datetime.now(UTC))
                )
                await session.commit()
                changed = bool(updated.rowcount)
            if not changed:
                return True
            cluster_signals = getattr(self, "cluster_signals", None)
            if cluster_signals is not None:
                await cluster_signals.publish_chat_change(
                    row.conversation_id, session_id=row.intaris_session_id
                )
            await self._publish_ui_notice(row.conversation_id, payload)
            return True
        except Exception:
            logger.warning(
                "Failed to publish executor recovery notice",
                extra={
                    "extra_data": {
                        "conversation_id": row.conversation_id,
                        "executor_id": row.executor_id,
                    }
                },
                exc_info=True,
            )
            return False

    async def dispatch_pending(self, *, limit: int = 50) -> int:
        delivered = await self.dispatch_recovery_pending(limit=limit)
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(ExecutorPinNoticeOutboxRow)
                        .where(ExecutorPinNoticeOutboxRow.delivered_at.is_(None))
                        .order_by(ExecutorPinNoticeOutboxRow.created_at)
                        .limit(limit)
                    )
                ).all()
            )
        for row in rows:
            if await self.dispatch_one(row.outbox_id):
                delivered += 1
        return delivered

    async def dispatch_one(self, outbox_id: str) -> bool:
        async with self.session_factory() as session:
            row = await session.get(ExecutorPinNoticeOutboxRow, outbox_id)
            if row is None or row.delivered_at is not None:
                return row is not None
            transition = await session.get(ExecutorPinTransitionRow, row.transition_id)
            if transition is None:
                return False
            conversation = await session.get(Conversation, row.conversation_id)
            if conversation is None:
                return False
            intaris_session_id = getattr(row, "intaris_session_id", None)
            if not intaris_session_id:
                return False
            payload = dict(row.payload or {})
            payload.setdefault("session_id", intaris_session_id)
            payload.setdefault("message", payload.get("text") or "")
            payload.setdefault("text", payload.get("message") or "")
            event = SessionEvent(type="lifecycle", data=payload)
            key = getattr(row, "idempotency_key", None) or (
                f"{intaris_session_id}:executor_failover:{transition.notice_id}"
            )
        try:
            result = await self.guardrails.record_events(
                session_id=intaris_session_id,
                events=[event],
                source="cognis_executor_failover",
                idempotency_key=key,
                user_email=getattr(row, "user_email", None),
                agent_id=getattr(row, "agent_id", None),
            )
            if not getattr(result, "ok", True):
                return False
        except Exception:
            return False
        async with self.session_factory() as session:
            now = datetime.now(UTC)
            updated = await session.execute(
                update(ExecutorPinNoticeOutboxRow)
                .where(
                    ExecutorPinNoticeOutboxRow.outbox_id == outbox_id,
                    ExecutorPinNoticeOutboxRow.delivered_at.is_(None),
                )
                .values(delivered_at=now)
            )
            await session.execute(
                update(ExecutorPinTransitionRow)
                .where(
                    ExecutorPinTransitionRow.transition_id == row.transition_id,
                    ExecutorPinTransitionRow.notice_appended_at.is_(None),
                )
                .values(notice_appended_at=now)
            )
            await session.commit()
            if updated.rowcount:
                cluster_signals = getattr(self, "cluster_signals", None)
                if cluster_signals is not None:
                    if transition.scope_type == "task":
                        await cluster_signals.publish_task_change(transition.scope_id)
                    elif transition.scope_type == "conversation":
                        await cluster_signals.publish_chat_change(
                            transition.scope_id,
                            session_id=intaris_session_id,
                            revision=transition.generation,
                        )
                await self._publish_ui_notice(row.conversation_id, payload)
            return True

    async def _publish_ui_notice(self, conversation_id: str, payload: dict[str, Any]) -> None:
        if self.event_bus is None:
            return
        with contextlib.suppress(Exception):
            await self.event_bus.publish(
                Event(
                    type=EventType.SYSTEM_NOTICE,
                    data={"conversation_id": conversation_id, **payload},
                )
            )
