from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from cognis.api.websocket import WebSocketConnectionManager
from cognis.core.context import events_to_messages
from cognis.core.executor_pin_notice_dispatch import (
    ExecutorPinNoticeDispatcher,
    recovery_notice_idempotency_key,
)
from cognis.core.executor_recovery import begin_executor_recovery, clear_executor_recovery
from cognis.store.models import ExecutorRecoveryNoticeRow
from cognis.store.queries import create_session, get_conversation
from tests.unit.test_direct_turn_runtime import _stores


class _Result:
    ok = True


class _Session:
    def __init__(self, row: Any, transition: Any, conversation: Any, active: Any) -> None:
        self.row = row
        self.transition = transition
        self.conversation = conversation
        self.active = active
        self.committed = False
        self.open = False

    async def __aenter__(self) -> _Session:
        self.open = True
        return self

    async def __aexit__(self, *_args: Any) -> None:
        self.open = False
        return None

    async def get(self, model: Any, key: str) -> Any:
        name = getattr(model, "__name__", "")
        if name == "ExecutorPinNoticeOutboxRow":
            return self.row
        if name == "ExecutorPinTransitionRow":
            return self.transition
        if name == "Conversation":
            return self.conversation
        return self.active

    async def execute(self, _statement: Any) -> Any:
        self.row.delivered_at = object()
        self.transition.notice_appended_at = object()
        return SimpleNamespace(rowcount=1)

    async def commit(self) -> None:
        self.committed = True


class _Factory:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def __call__(self) -> _Session:
        return self.session


@pytest.mark.asyncio
async def test_notice_dispatch_uses_stable_key_and_exactly_once() -> None:
    row = SimpleNamespace(
        outbox_id="outbox",
        delivered_at=None,
        transition_id="transition",
        payload={
            "event": "system_notice",
            "notice_id": "executor_failover:conv:2",
        },
        conversation_id="conv",
        intaris_session_id="intaris",
        idempotency_key="intaris:executor_failover:executor_failover:conv:2",
        user_email="u",
        agent_id="a",
    )
    transition = SimpleNamespace(notice_id="executor_failover:conv:2", notice_appended_at=None)
    conversation = SimpleNamespace(active_session_id="session")
    active = SimpleNamespace(intaris_session_id="intaris", user_email="u", agent_id="a")
    session = _Session(row, transition, conversation, active)
    keys: list[str | None] = []

    class Guardrails:
        async def record_events(self, **kwargs: Any) -> _Result:
            assert not session.open
            keys.append(kwargs["idempotency_key"])
            assert len(kwargs["events"]) == 1
            assert kwargs["events"][0].type == "lifecycle"
            assert kwargs["events"][0].data["event"] == "system_notice"
            return _Result()

    published: list[Any] = []

    class EventBus:
        async def publish(self, event: Any) -> None:
            published.append(event)

    dispatcher = ExecutorPinNoticeDispatcher(
        session_factory=_Factory(session),
        guardrails=Guardrails(),
        event_bus=EventBus(),
    )
    assert await dispatcher.dispatch_one("outbox") is True
    assert await dispatcher.dispatch_one("outbox") is True
    assert keys == ["intaris:executor_failover:executor_failover:conv:2"]
    assert len(published) == 1
    assert events_to_messages(
        [{"type": "lifecycle", "data": {**row.payload, "message": "Executor changed."}}]
    ) == [{"role": "system", "content": "Executor changed."}]


@pytest.mark.asyncio
async def test_append_failure_keeps_outbox_recoverable() -> None:
    row = SimpleNamespace(
        outbox_id="outbox",
        delivered_at=None,
        transition_id="transition",
        payload={
            "event": "system_notice",
            "notice_id": "n",
        },
        conversation_id="conv",
        intaris_session_id="intaris",
        idempotency_key="intaris:executor_failover:n",
        user_email="u",
        agent_id="a",
    )
    transition = SimpleNamespace(notice_id="n", notice_appended_at=None)
    session = _Session(
        row,
        transition,
        SimpleNamespace(active_session_id="session"),
        SimpleNamespace(intaris_session_id="intaris", user_email="u", agent_id="a"),
    )

    class Guardrails:
        async def record_events(self, **kwargs: Any) -> _Result:
            assert not session.open
            raise RuntimeError("Intaris unavailable")

    dispatcher = ExecutorPinNoticeDispatcher(
        session_factory=_Factory(session),
        guardrails=Guardrails(),
    )
    assert await dispatcher.dispatch_one("outbox") is False
    assert row.delivered_at is None
    assert transition.notice_appended_at is None


@pytest.mark.asyncio
async def test_recovery_notice_is_durable_idempotent_and_retried_after_restart(
    tmp_path: Path,
) -> None:
    engine, store, _ = await _stores(tmp_path)
    factory = store._session_factory  # noqa: SLF001
    async with factory() as session:
        active = await create_session(session, "conv-a", "user@example.com", "agent-1")
        conversation = await get_conversation(session, "conv-a")
        conversation.active_session_id = active.session_id
        conversation.active_executor_id = "maitrea_riker"
        await session.commit()
    keys = set()
    events = []

    async def record_events(**kwargs):
        key = kwargs["idempotency_key"]
        assert re.fullmatch(r"[a-zA-Z0-9._:@-]{1,256}", key)
        assert key.startswith(f"{kwargs['session_id']}:")
        if key in keys:
            return SimpleNamespace(ok=True, count=0)
        keys.add(key)
        events.extend(kwargs["events"])
        return SimpleNamespace(ok=True, count=1)

    manager = WebSocketConnectionManager(
        SimpleNamespace(state=SimpleNamespace(session_factory=factory))
    )
    manager.send_chat_v2_runtime_to_conversation = AsyncMock()
    bus = SimpleNamespace(publish=AsyncMock(side_effect=manager._handle_event))  # noqa: SLF001
    guardrails = SimpleNamespace(record_events=AsyncMock(side_effect=RuntimeError("offline")))
    dispatcher = ExecutorPinNoticeDispatcher(
        session_factory=factory,
        guardrails=guardrails,
        event_bus=bus,
    )
    kwargs = {
        "conversation_id": "conv-a",
        "task_id": None,
        "executor_id": "maitrea_riker",
        "notice_dispatcher": dispatcher,
    }
    try:
        first = await begin_executor_recovery(factory, **kwargs)
        repeated = await begin_executor_recovery(factory, **kwargs)
        assert first.deadline == repeated.deadline
        await clear_executor_recovery(factory, **kwargs)
        async with factory() as session:
            rows = list((await session.scalars(select(ExecutorRecoveryNoticeRow))).all())
            assert len(rows) == 2
            assert all(row.delivered_at is None for row in rows)
            conversation = await get_conversation(session, "conv-a")
            assert conversation.active_executor_unavailable_since is None
        # A new dispatcher must recover delivery even though the marker is cleared.
        dispatcher = ExecutorPinNoticeDispatcher(
            session_factory=factory,
            guardrails=SimpleNamespace(record_events=record_events),
            event_bus=bus,
        )
        dispatcher.cluster_signals = SimpleNamespace(publish_chat_change=AsyncMock())
        assert await dispatcher.dispatch_recovery_pending() == 2
        assert await dispatcher.dispatch_recovery_pending() == 0
        assert len(keys) == len(events) == 2
        assert [event.data["state"] for event in events] == ["unavailable", "recovered"]
        assert bus.publish.await_count == 2
        runtime = manager.send_chat_v2_runtime_to_conversation
        assert runtime.await_count == 2
        for call, event in zip(runtime.await_args_list, events, strict=True):
            assert call.args == ("conv-a",)
            assert call.kwargs["active_session_id"] == active.session_id
            item = call.kwargs["volatile_items"][0]
            assert item.content == event.data["message"]
            assert item.notice_id == event.data["notice_id"]
            assert item.notice_kind == "executor_recovery"
        assert dispatcher.cluster_signals.publish_chat_change.await_count == 2
        assert all(event.type == "lifecycle" for event in events)
        assert events_to_messages([{"type": event.type, "data": event.data} for event in events])
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recovery_lost_ack_reuses_identity_after_dispatcher_restart(tmp_path: Path) -> None:
    engine, store, _ = await _stores(tmp_path)
    factory = store._session_factory  # noqa: SLF001
    notice_id = "executor_recovery:conv-a:executor-a:2026-01-01T10:00:00+00:00:unavailable"
    async with factory() as session:
        session.add(
            ExecutorRecoveryNoticeRow(
                notice_id=notice_id,
                conversation_id="conv-a",
                session_id="sess-a",
                intaris_session_id="sess-a",
                user_email="user@example.com",
                agent_id="agent-1",
                executor_id="executor-a",
                unavailable_since=datetime(2026, 1, 1, tzinfo=UTC),
                recovered=False,
            )
        )
        await session.commit()
    attempts = []
    receipts = {}

    async def record_events(**kwargs):
        key = kwargs["idempotency_key"]
        payload = kwargs["events"][0].model_dump()
        attempts.append((key, payload))
        if key not in receipts:
            receipts[key] = payload
            raise TimeoutError("Acknowledgement lost after append")
        assert receipts[key] == payload
        return SimpleNamespace(ok=True, count=1, first_seq=1, last_seq=1)

    try:
        for expected in (0, 1):
            dispatcher = ExecutorPinNoticeDispatcher(
                session_factory=factory,
                guardrails=SimpleNamespace(record_events=record_events),
            )
            assert await dispatcher.dispatch_recovery_pending() == expected
        assert attempts[0] == attempts[1]
        assert len(receipts) == 1
        assert attempts[0][1]["data"]["notice_id"] == notice_id
        assert await dispatcher.dispatch_recovery_pending() == 0
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "notice_id",
    [
        "executor_recovery:conv-a:executor-a:2026-01-01T10:00:00+00:00:unavailable",
        "executor_recovery:conv-a:executor-a:2026-01-01T10:00:00+00:00:recovered",
        "executor_recovery:" + "a" * 300,
    ],
)
def test_recovery_append_identity_is_valid_stable_and_scoped(notice_id: str) -> None:
    key = recovery_notice_idempotency_key("sess-a", notice_id)
    assert re.fullmatch(r"[a-zA-Z0-9._:@-]{1,256}", key)
    assert key.startswith("sess-a:")
    assert key == recovery_notice_idempotency_key("sess-a", notice_id)
    assert key != recovery_notice_idempotency_key("sess-b", notice_id)
    assert key != recovery_notice_idempotency_key("sess-a", notice_id + ":next")


def test_recovery_append_identity_preserves_legacy_receipts() -> None:
    notice_id = "executor_recovery:conv-a:executor-a:2026-01-01T10:00:00Z:unavailable"
    assert recovery_notice_idempotency_key("sess-a", notice_id) == f"sess-a:{notice_id}"


@pytest.mark.asyncio
async def test_notice_io_does_not_extend_recovery_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, store, _ = await _stores(tmp_path)
    factory = store._session_factory  # noqa: SLF001
    clock = 100.0

    async def slow_flush():
        nonlocal clock
        clock += 20

    monkeypatch.setattr("cognis.core.executor_recovery.monotonic", lambda: clock)
    dispatcher = SimpleNamespace(
        queue_recovery_notice=AsyncMock(), flush_recovery_notices=slow_flush
    )
    try:
        window = await begin_executor_recovery(
            factory,
            conversation_id="conv-a",
            task_id=None,
            executor_id="maitrea_riker",
            notice_dispatcher=dispatcher,
        )
        assert window.remaining_seconds() == 880
    finally:
        await engine.dispose()
