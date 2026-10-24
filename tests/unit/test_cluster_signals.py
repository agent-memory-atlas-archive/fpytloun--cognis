from __future__ import annotations

import asyncio
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call

import pytest

import cognis.core.cluster_signals as cluster_signals_module
from cognis.bootstrap import run_schema_bootstrap
from cognis.core.cluster_signals import (
    MAX_DEDUP_ENTRIES,
    MAX_RECONCILE_SCOPES,
    ClusterEventStoreId,
    ClusterSignal,
    ClusterSignalKind,
    ClusterSignalScope,
    ClusterSignalService,
)
from cognis.core.events import Event, EventBus, EventType
from cognis.core.queue_wakeup import publish_queue_wakeup
from cognis.runtime_context import current_agent_id, current_agent_owner_email, current_user_email
from cognis.store import queries
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import Agent, Conversation, Session
from cognis.store.work_live_invalidation import bump_live_work_revision


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed


class _FakeTransport:
    def __init__(self, callbacks: list[Any]) -> None:
        self.callbacks = callbacks
        self.connection = _FakeConnection()
        self.closed = False

    async def listen(self, _channel: str, callback: Any) -> _FakeConnection:
        self.callbacks.append(callback)
        self.connection = _FakeConnection()
        return self.connection

    async def publish(self, _channel: str, payload: str) -> None:
        for callback in list(self.callbacks):
            callback(payload)

    async def close(self) -> None:
        self.closed = True
        self.connection.closed = True


@pytest.mark.asyncio
async def test_queue_wakeup_crosses_real_signal_dispatch_boundary() -> None:
    callbacks: list[Any] = []
    buses = [EventBus(), EventBus()]
    signals = [
        ClusterSignalService(
            database_url="postgresql+asyncpg://localhost/cognis",
            controller_id=f"controller-{index}",
            session_factory=None,
            event_bus=bus,
            scope_provider=lambda: [],
            transport=_FakeTransport(callbacks),
        )
        for index, bus in enumerate(buses)
    ]
    wakes = [asyncio.Event(), asyncio.Event()]

    for bus, wake in zip(buses, wakes, strict=True):

        async def handler(event: Event, wake: asyncio.Event = wake) -> None:
            if event.data.get("kind") == ClusterSignalKind.TASK_QUEUE_CHANGED:
                wake.set()

        bus.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, handler)
    try:
        for service in signals:
            await service.start()
        async with asyncio.timeout(1):
            while len(callbacks) != 2:
                await asyncio.sleep(0.001)
        await publish_queue_wakeup(buses[0], signals[0])
        await asyncio.wait_for(asyncio.gather(*(wake.wait() for wake in wakes)), 1)
    finally:
        for service in signals:
            await service.stop()


class _SessionContext:
    async def __aenter__(self) -> _SessionContext:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, model: type[Any], key: str) -> Any:
        if model is Conversation and key == "conv-1":
            return type(
                "ConversationRow",
                (),
                {
                    "active_session_id": "session-1",
                    "updated_at": "2026-07-29T08:30:00+00:00",
                },
            )()
        if model is Session and key.startswith("session-"):
            agent_id = "system:explore" if key == "session-system" else "agent-1"
            return type(
                "SessionRow",
                (),
                {
                    "intaris_session_id": f"intaris-{key}",
                    "user_email": "session-user@example.com",
                    "agent_id": agent_id,
                },
            )()
        if model is Agent and key == "agent-1":
            return type("AgentRow", (), {"owner_email": "agent-owner@example.com"})()
        return None


async def _unused_session_factory() -> Any:
    raise AssertionError("database should not be queried")


def _record_events(target: list[Event]) -> Any:
    async def _record(event: Event) -> None:
        target.append(event)

    return _record


@pytest.mark.asyncio
async def test_only_account_sidebar_reconciliation_is_marked_metadata_only() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, _record_events(received))
    service = ClusterSignalService(
        database_url="sqlite://",
        controller_id="controller-a",
        session_factory=_unused_session_factory,
        event_bus=bus,
        scope_provider=lambda: [],
        owner_token_secret="shared-secret",
    )
    service._scope_provider = lambda: [  # noqa: SLF001
        {
            "owner_token": service.owner_token("owner@example.com"),
            "user_email": "owner@example.com",
        },
        {"session_id": "session-1", "user_email": "owner@example.com"},
    ]
    service._scope_watermark = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
        side_effect=["initial", "initial", "changed", "changed"]
    )
    await service.reconcile_once()
    await service.reconcile_once()
    assert len(received) == 4  # Initial snapshots and their subsequent changes.
    account = [event for event in received if event.data["scope"].get("owner_token")]
    session = [event for event in received if event.data["scope"].get("session_id")]
    assert len(account) == len(session) == 2
    assert all(event.data["metadata_only"] is True for event in account)
    assert all("metadata_only" not in event.data for event in session)


@pytest.mark.asyncio
async def test_work_reconciliation_watermark_reads_durable_revision(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'work-revision.db'}")
    factory = create_session_factory(engine)
    await run_schema_bootstrap(engine)
    async with factory() as db:
        await queries.create_user(
            db,
            email="owner@example.com",
            name="Owner",
            password_hash="x",
            role="user",
        )
        await db.flush()
        assert await bump_live_work_revision(db, "owner@example.com") == 1
        assert await bump_live_work_revision(db, "owner@example.com") == 2
        await db.commit()

    service = ClusterSignalService(
        database_url="sqlite://",
        controller_id="controller",
        session_factory=factory,
        event_bus=EventBus(),
        scope_provider=lambda: [],
        transport=_FakeTransport([]),
        owner_token_secret="shared-secret",
    )
    watermark = await service._scope_watermark(  # noqa: SLF001
        ClusterSignalScope(work_scope_key="*"),
        "owner@example.com",
    )
    assert "work:2" in watermark
    await engine.dispose()


@pytest.mark.asyncio
async def test_signal_from_controller_a_invalidates_controller_b_and_stops_cleanly() -> None:
    callbacks: list[Any] = []
    bus_a = EventBus()
    bus_b = EventBus()
    received: list[Event] = []
    bus_b.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, _record_events(received))
    service_a = ClusterSignalService(
        database_url="postgresql+asyncpg://localhost/cognis",
        controller_id="controller-a",
        session_factory=_unused_session_factory,
        event_bus=bus_a,
        scope_provider=lambda: [],
        transport=_FakeTransport(callbacks),
        owner_token_secret="shared-secret",
    )
    transport_b = _FakeTransport(callbacks)
    service_b = ClusterSignalService(
        database_url="postgresql+asyncpg://localhost/cognis",
        controller_id="controller-b",
        session_factory=_unused_session_factory,
        event_bus=bus_b,
        scope_provider=lambda: [],
        transport=transport_b,
        owner_token_secret="shared-secret",
    )

    await service_b.start()
    await asyncio.sleep(0)
    await service_a.publish(
        ClusterSignalKind.CHAT_SCOPE_CHANGED,
        scope=ClusterSignalScope(conversation_id="conv-1", session_id="session-1"),
        revision=42,
    )
    await asyncio.wait_for(service_b._pending.join(), timeout=1)  # noqa: SLF001

    assert len(received) == 1
    assert received[0].data == {
        "kind": ClusterSignalKind.CHAT_SCOPE_CHANGED,
        "scope": {"conversation_id": "conv-1", "session_id": "session-1"},
        "revision": "42",
    }
    await service_b.stop()
    assert transport_b.closed
    assert service_b._listener_task is None  # noqa: SLF001
    assert service_b._dispatch_task is None  # noqa: SLF001
    assert service_b._reconcile_task is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_slow_scope_does_not_block_unrelated_cluster_signal() -> None:
    callbacks: list[Any] = []
    bus = EventBus()
    release_slow = asyncio.Event()
    fast_received = asyncio.Event()

    async def _handle(event: Event) -> None:
        conversation_id = event.data["scope"].get("conversation_id")
        if conversation_id == "conv-slow":
            await release_slow.wait()
        elif conversation_id == "conv-fast":
            fast_received.set()

    bus.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, _handle)
    service = ClusterSignalService(
        database_url="postgresql+asyncpg://localhost/cognis",
        controller_id="controller-b",
        session_factory=_unused_session_factory,
        event_bus=bus,
        scope_provider=lambda: [],
        transport=_FakeTransport(callbacks),
        owner_token_secret="shared-secret",
    )
    await service.start()
    await asyncio.sleep(0)
    for conversation_id in ("conv-slow", "conv-fast"):
        service.receive_payload(
            ClusterSignal(
                kind=ClusterSignalKind.CHAT_SCOPE_CHANGED,
                origin_controller_id="controller-a",
                scope=ClusterSignalScope(conversation_id=conversation_id),
                revision="1",
            ).encoded()
        )

    await asyncio.wait_for(fast_received.wait(), timeout=0.5)
    release_slow.set()
    await asyncio.wait_for(service._pending.join(), timeout=1)  # noqa: SLF001
    await service.stop()


@pytest.mark.asyncio
async def test_chat_change_also_invalidates_sidebar_projection() -> None:
    service = ClusterSignalService(
        database_url="postgresql+asyncpg://localhost/cognis",
        controller_id="controller-a",
        session_factory=_SessionContext,
        event_bus=EventBus(),
        scope_provider=lambda: [],
        owner_token_secret="shared-secret",
    )
    service.publish = AsyncMock()  # type: ignore[method-assign]

    await service.publish_chat_change("conv-1", revision=42)

    assert service.publish.await_args_list == [
        call(
            ClusterSignalKind.CHAT_SCOPE_CHANGED,
            scope=ClusterSignalScope(conversation_id="conv-1", session_id="session-1"),
            revision=42,
        ),
        call(
            ClusterSignalKind.SIDEBAR_CHANGED,
            scope=ClusterSignalScope(conversation_id="conv-1", session_id="session-1"),
            revision=42,
        ),
    ]


@pytest.mark.asyncio
async def test_event_store_invalidation_signal_is_identity_free() -> None:
    callbacks: list[Any] = []
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, _record_events(received))
    service = ClusterSignalService(
        database_url="postgresql+asyncpg://localhost/cognis",
        controller_id="controller-b",
        session_factory=_unused_session_factory,
        event_bus=bus,
        scope_provider=lambda: [],
        transport=_FakeTransport(callbacks),
        owner_token_secret="shared-secret",
    )
    remote = ClusterSignalService(
        database_url="postgresql+asyncpg://localhost/cognis",
        controller_id="controller-a",
        session_factory=_unused_session_factory,
        event_bus=EventBus(),
        scope_provider=lambda: [],
        transport=_FakeTransport(callbacks),
        owner_token_secret="shared-secret",
    )
    token = "a" * 64

    await service.start()
    await asyncio.sleep(0)
    await remote.publish_event_store_invalidation(
        store_id=ClusterEventStoreId.INTARIS,
        session_token=token,
        revision=7,
    )
    await asyncio.wait_for(service._pending.join(), timeout=1)  # noqa: SLF001

    assert received[0].data == {
        "kind": ClusterSignalKind.EVENT_STORE_SESSION_INVALIDATED,
        "scope": {
            "event_store_id": ClusterEventStoreId.INTARIS,
            "event_session_token": token,
        },
        "revision": "7",
    }
    assert "@" not in received[0].model_dump_json()
    await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite+aiosqlite:///:memory:",
        "postgresql+asyncpg://localhost/cognis",
    ],
)
async def test_canonical_append_wakes_origin_controller_without_remote_echo(
    database_url: str,
) -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, _record_events(received))
    service = ClusterSignalService(
        database_url=database_url,
        controller_id="controller-a",
        session_factory=_unused_session_factory,
        event_bus=bus,
        scope_provider=lambda: [],
        transport=_FakeTransport([]),
        owner_token_secret="shared-secret",
    )
    await service.publish_event_store_invalidation(
        store_id=ClusterEventStoreId.INTARIS,
        session_token="a" * 64,
        revision=7,
    )
    assert len(received) == 1
    assert received[0].data["kind"] == "event_store_session_invalidated"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_append_publication_keeps_local_delivery_when_remote_fails(failure: bool) -> None:
    local_bus = EventBus()
    remote_bus = EventBus()
    local_events: list[Event] = []
    remote_events: list[Event] = []
    local_bus.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, _record_events(local_events))
    remote_bus.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, _record_events(remote_events))
    callbacks: list[Any] = []

    class Transport(_FakeTransport):
        async def publish(self, channel: str, payload: str) -> None:
            assert len(local_events) == 1  # Local delivery precedes transport.
            if failure:
                raise RuntimeError("synthetic transport failure")
            await super().publish(channel, payload)

    local = ClusterSignalService(
        database_url="postgresql+asyncpg://localhost/cognis",
        controller_id="controller-local",
        session_factory=_unused_session_factory,
        event_bus=local_bus,
        scope_provider=lambda: [],
        transport=Transport(callbacks),
        owner_token_secret="shared-secret",
    )
    remote = ClusterSignalService(
        database_url="postgresql+asyncpg://localhost/cognis",
        controller_id="controller-remote",
        session_factory=_unused_session_factory,
        event_bus=remote_bus,
        scope_provider=lambda: [],
        transport=_FakeTransport(callbacks),
        owner_token_secret="shared-secret",
    )
    await local.start()
    await remote.start()
    await asyncio.sleep(0)
    try:
        result = await local.publish_event_store_invalidation(
            store_id=ClusterEventStoreId.INTARIS,
            session_token="b" * 64,
            revision=8,
        )
        await asyncio.wait_for(local._pending.join(), timeout=1)  # noqa: SLF001
        await asyncio.wait_for(remote._pending.join(), timeout=1)  # noqa: SLF001
        assert result is (not failure)
        assert len(local_events) == 1  # Own echo must not recurse or redeliver.
        assert len(remote_events) == (0 if failure else 1)
        if not failure:
            assert remote_events[0].data == local_events[0].data
    finally:
        await local.stop()
        await remote.stop()


@pytest.mark.asyncio
async def test_append_listener_dispatches_post_commit_read_after_early_hint() -> None:
    from cognis.api.chat_v2.append_listener import EventAppendListenerFastPath
    from cognis.api.chat_v2.cached_event_store import AppendInvalidation
    from cognis.core.event_append_invalidation import EventAppendInvalidationDispatcher
    from cognis.models.session import SessionEvent
    from cognis.providers.guardrails.events import EventAppendNotification, EventStoreAuthority

    committed: list[SessionEvent] = []
    reads: list[list[str]] = []
    observed = asyncio.Event()
    token = "c" * 64

    class Store:
        def invalidate_append_local(self, notification):
            assert committed == list(notification.events)
            return AppendInvalidation(token, "authority", 1, True, 1)

        async def process_append_invalidation(self, work):
            assert committed and work.last_seq == 1
            return True

    async def recipient_read(_event):
        reads.append([event.data["client_message_id"] for event in committed])
        observed.set()

    bus = EventBus()
    bus.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, recipient_read)
    service = ClusterSignalService(
        database_url="sqlite+aiosqlite:///:memory:",
        controller_id="controller-origin",
        session_factory=_unused_session_factory,
        event_bus=bus,
        scope_provider=lambda: [],
        owner_token_secret="shared-secret",
    )

    async def publish(session_token, revision):
        return await service.publish_event_store_invalidation(
            store_id=ClusterEventStoreId.INTARIS,
            session_token=session_token,
            revision=revision,
        )

    dispatcher = EventAppendInvalidationDispatcher(
        event_store=Store(), publish_invalidation=publish
    )
    listener = EventAppendListenerFastPath(
        event_store=Store(),
        invalidation_dispatcher=dispatcher,
        work_materializer=SimpleNamespace(enqueue_append=lambda _: True),
    )
    await dispatcher.start()
    try:
        # Early admission returns an unchanged canonical read. Sender HTTP ACK
        # is irrelevant: only the real post-append listener can wake this reader.
        await recipient_read(None)
        assert reads == [[]]
        observed.clear()
        committed.append(
            SessionEvent(
                type="user_message",
                data={
                    "client_message_id": "absorbed-admission",
                    "content": "Synthetic absorbed input",
                },
            )
        )
        await listener(
            EventAppendNotification(
                authority=EventStoreAuthority(
                    user_email="recipient@example.com",
                    agent_id="agent-1",
                    agent_owner_email="recipient@example.com",
                ),
                session_id="session-1",
                first_seq=1,
                last_seq=1,
                event_count=1,
                events=tuple(committed),
            )
        )
        await asyncio.wait_for(observed.wait(), timeout=1)
        assert reads == [[], ["absorbed-admission"]]
    finally:
        await dispatcher.stop()


@pytest.mark.asyncio
async def test_work_revision_invalidates_local_and_remote_controllers() -> None:
    callbacks: list[Any] = []
    local_bus = EventBus()
    remote_bus = EventBus()
    local_events: list[Event] = []
    remote_events: list[Event] = []
    local_bus.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, _record_events(local_events))
    remote_bus.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, _record_events(remote_events))
    local = ClusterSignalService(
        database_url="postgresql+asyncpg://localhost/cognis",
        controller_id="controller-a",
        session_factory=_unused_session_factory,
        event_bus=local_bus,
        scope_provider=lambda: [],
        transport=_FakeTransport(callbacks),
        owner_token_secret="shared-secret",
    )
    remote = ClusterSignalService(
        database_url="postgresql+asyncpg://localhost/cognis",
        controller_id="controller-b",
        session_factory=_unused_session_factory,
        event_bus=remote_bus,
        scope_provider=lambda: [],
        transport=_FakeTransport(callbacks),
        owner_token_secret="shared-secret",
    )

    await remote.start()
    await asyncio.sleep(0)
    assert (
        await local.publish_work_invalidation(
            scope_key="conversation:conv-1",
            user_email="owner@example.com",
            revision=9,
        )
        is True
    )
    await asyncio.wait_for(remote._pending.join(), timeout=1)  # noqa: SLF001

    assert local_events[0].data["kind"] == ClusterSignalKind.WORK_INVALIDATED
    assert remote_events[0].data == local_events[0].data
    assert remote_events[0].data["revision"] == "9"
    assert remote_events[0].data["scope"]["work_scope_key"] == "conversation:conv-1"
    assert "owner@example.com" not in remote_events[0].model_dump_json()
    assert (
        await local.publish_work_invalidation(
            scope_key="conversation:conv-1",
            user_email="owner@example.com",
            revision=10,
        )
        is True
    )
    await asyncio.wait_for(remote._pending.join(), timeout=1)  # noqa: SLF001
    assert [event.data["revision"] for event in remote_events] == ["9", "10"]
    await remote.stop()


@pytest.mark.asyncio
async def test_work_publication_reports_transient_transport_failure() -> None:
    class _FailingTransport(_FakeTransport):
        async def publish(self, _channel: str, payload: str) -> None:
            del payload
            raise RuntimeError("transient")

    service = ClusterSignalService(
        database_url="postgresql+asyncpg://localhost/cognis",
        controller_id="controller-a",
        session_factory=_unused_session_factory,
        event_bus=EventBus(),
        scope_provider=lambda: [],
        transport=_FailingTransport([]),
        owner_token_secret="shared-secret",
    )

    assert (
        await service.publish_work_invalidation(
            scope_key="conversation:conv-1",
            user_email="owner@example.com",
            revision=9,
        )
        is False
    )


def test_signal_payload_is_strict_bounded_and_contains_no_content_fields() -> None:
    signal = ClusterSignal(
        kind=ClusterSignalKind.NOTIFICATION_STATE_CHANGED,
        origin_controller_id="controller-a",
        scope=ClusterSignalScope(
            conversation_id="conv-1",
            task_id="task-1",
        ),
        revision="2026-07-26T12:00:00Z",
    )

    encoded = signal.encoded()
    assert len(encoded.encode()) <= 2048
    assert "content" not in encoded
    assert "payload" not in encoded
    assert "owner@example.com" not in encoded
    assert "user_email" not in encoded
    with pytest.raises(ValueError):
        ClusterSignal.model_validate(
            {
                **signal.model_dump(),
                "prompt": "secret",
            }
        )
    with pytest.raises(ValueError):
        ClusterSignalScope(conversation_id="x" * 161)
    with pytest.raises(ValueError):
        ClusterSignal(
            kind=ClusterSignalKind.EVENT_STORE_SESSION_INVALIDATED,
            origin_controller_id="controller-a",
            scope=ClusterSignalScope(
                event_store_id=ClusterEventStoreId.INTARIS,
                event_session_token="a" * 64,
                conversation_id="must-not-be-present",
            ),
            revision="1",
        )
    with pytest.raises(ValueError):
        ClusterSignal(
            kind=ClusterSignalKind.CHAT_SCOPE_CHANGED,
            origin_controller_id="controller-a",
            scope=ClusterSignalScope(
                event_store_id=ClusterEventStoreId.INTARIS,
                event_session_token="a" * 64,
            ),
            revision="1",
        )


def test_long_reconciliation_revision_is_replaced_with_stable_digest() -> None:
    source = "watermark:" + ("x" * 500)

    revision = cluster_signals_module._bounded_revision(source)

    assert revision.startswith("sha256:")
    assert len(revision) == 71
    assert revision == cluster_signals_module._bounded_revision(source)


def test_same_origin_duplicates_and_dedup_storage_are_bounded() -> None:
    service = ClusterSignalService(
        database_url="postgresql://localhost/cognis",
        controller_id="controller-b",
        session_factory=_unused_session_factory,
        event_bus=EventBus(),
        scope_provider=lambda: [],
        transport=_FakeTransport([]),
        owner_token_secret="shared-secret",
    )
    same_origin = ClusterSignal(
        kind=ClusterSignalKind.CHAT_SCOPE_CHANGED,
        origin_controller_id="controller-b",
        scope=ClusterSignalScope(conversation_id="conv-1"),
        revision="1",
    )
    service.receive_payload(same_origin.encoded())
    assert service._pending.empty()  # noqa: SLF001

    remote = same_origin.model_copy(update={"origin_controller_id": "controller-a"})
    service.receive_payload(remote.encoded())
    service.receive_payload(remote.encoded())
    assert service._pending.qsize() == 1  # noqa: SLF001
    for revision in range(MAX_DEDUP_ENTRIES + 20):
        service.receive_payload(remote.model_copy(update={"revision": str(revision)}).encoded())
    assert len(service._dedup) == MAX_DEDUP_ENTRIES  # noqa: SLF001


@pytest.mark.asyncio
async def test_missed_signal_is_healed_by_subscribed_scope_reconciliation() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, _record_events(received))
    service = ClusterSignalService(
        database_url="postgresql://localhost/cognis",
        controller_id="controller-b",
        session_factory=_unused_session_factory,
        event_bus=bus,
        scope_provider=lambda: [
            {
                "conversation_id": "conv-1",
                "session_id": "session-1",
                "user_email": "owner@example.com",
                "owner_token": "a" * 64,
            }
        ],
        transport=_FakeTransport([]),
        owner_token_secret="shared-secret",
    )
    watermark = "1"

    async def _watermark(_scope: ClusterSignalScope, _owner_email: str | None = None) -> str:
        return watermark

    service._scope_watermark = _watermark  # type: ignore[method-assign]  # noqa: SLF001
    await service.reconcile_once()
    assert len(received) == 1
    received.clear()
    watermark = "2"
    await service.reconcile_once()
    assert len(received) == 1
    assert received[0].data["revision"] == "2"


@pytest.mark.asyncio
async def test_reconciliation_rotates_through_more_than_one_bounded_batch() -> None:
    scopes = [{"conversation_id": f"conv-{index}"} for index in range(300)]
    service = ClusterSignalService(
        database_url="postgresql://localhost/cognis",
        controller_id="controller-b",
        session_factory=_unused_session_factory,
        event_bus=EventBus(),
        scope_provider=lambda: scopes,
        transport=_FakeTransport([]),
        owner_token_secret="shared-secret",
    )

    async def _watermark(scope: ClusterSignalScope, _owner_email: str | None = None) -> str:
        return str(scope.conversation_id)

    service._scope_watermark = _watermark  # type: ignore[method-assign]  # noqa: SLF001
    await service.reconcile_once()
    assert len(service._watermarks) == 256  # noqa: SLF001
    await service.reconcile_once()
    assert len(service._watermarks) == 300  # noqa: SLF001


@pytest.mark.asyncio
async def test_reconciliation_watermark_includes_canonical_event_store_sequence() -> None:
    observed_context: list[tuple[str | None, str | None, str | None]] = []

    async def _read_watermark(**_: object) -> object:
        observed_context.append(
            (current_user_email.get(), current_agent_id.get(), current_agent_owner_email.get())
        )
        return type("Watermark", (), {"last_seq": 73})()

    event_store = type(
        "EventStore",
        (),
        {"read_authoritative_session_high_watermark": AsyncMock(side_effect=_read_watermark)},
    )()
    service = ClusterSignalService(
        database_url="postgresql://localhost/cognis",
        controller_id="controller-b",
        session_factory=_SessionContext,
        event_bus=EventBus(),
        scope_provider=lambda: [],
        transport=_FakeTransport([]),
        event_store=event_store,
        owner_token_secret="shared-secret",
    )

    watermark = await service._scope_watermark(  # noqa: SLF001
        ClusterSignalScope(session_id="session-1")
    )

    assert "event_store:73" in watermark
    event_store.read_authoritative_session_high_watermark.assert_awaited_once_with(
        session_id="intaris-session-1"
    )
    assert observed_context == [("session-user@example.com", "agent-1", "agent-owner@example.com")]


@pytest.mark.asyncio
async def test_reconciliation_invalidates_cache_after_authoritative_sequence_change() -> None:
    sequence = 7

    async def read_authoritative(**_kwargs: object) -> object:
        return SimpleNamespace(last_seq=sequence)

    event_store = SimpleNamespace(
        bind=lambda _authority: event_store,
        read_authoritative_session_high_watermark=AsyncMock(side_effect=read_authoritative),
        invalidate_session=AsyncMock(return_value=True),
    )
    service = ClusterSignalService(
        database_url="postgresql://localhost/cognis",
        controller_id="controller-b",
        session_factory=_SessionContext,
        event_bus=EventBus(),
        scope_provider=lambda: [{"session_id": "session-1"}],
        transport=_FakeTransport([]),
        event_store=event_store,
        owner_token_secret="shared-secret",
    )

    await service.reconcile_once()
    event_store.invalidate_session.assert_awaited_once_with(
        ClusterEventStoreId.INTARIS,
        "intaris-session-1",
        source="cluster_signal",
    )

    sequence = 8
    await service.reconcile_once()

    assert event_store.invalidate_session.await_count == 2


@pytest.mark.asyncio
async def test_reconciliation_watermark_uses_system_agent_owner() -> None:
    observed_context: list[tuple[str | None, str | None, str | None]] = []

    async def _read_watermark(**_: object) -> object:
        observed_context.append(
            (current_user_email.get(), current_agent_id.get(), current_agent_owner_email.get())
        )
        return type("Watermark", (), {"last_seq": 0})()

    event_store = type(
        "EventStore",
        (),
        {"read_authoritative_session_high_watermark": AsyncMock(side_effect=_read_watermark)},
    )()
    service = ClusterSignalService(
        database_url="postgresql://localhost/cognis",
        controller_id="controller-b",
        session_factory=_SessionContext,
        event_bus=EventBus(),
        scope_provider=lambda: [],
        transport=_FakeTransport([]),
        event_store=event_store,
        owner_token_secret="shared-secret",
    )

    await service._scope_watermark(ClusterSignalScope(session_id="session-system"))  # noqa: SLF001

    assert observed_context == [
        ("session-user@example.com", "system:explore", "system@cognis.local")
    ]


@pytest.mark.asyncio
async def test_reconciliation_watermarks_are_concurrent_and_bounded() -> None:
    scopes = [{"conversation_id": f"conv-{index}"} for index in range(24)]
    service = ClusterSignalService(
        database_url="postgresql://localhost/cognis",
        controller_id="controller-b",
        session_factory=_unused_session_factory,
        event_bus=EventBus(),
        scope_provider=lambda: scopes,
        transport=_FakeTransport([]),
        owner_token_secret="shared-secret",
    )
    active = 0
    maximum_active = 0

    async def _slow_watermark(scope: ClusterSignalScope, _owner_email: str | None = None) -> str:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            await asyncio.sleep(0.03)
            return str(scope.conversation_id)
        finally:
            active -= 1

    service._scope_watermark = _slow_watermark  # type: ignore[method-assign]  # noqa: SLF001
    started = monotonic()
    await service.reconcile_once()

    assert maximum_active == 8
    assert monotonic() - started < 0.3


@pytest.mark.asyncio
async def test_reconciliation_times_out_slow_event_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _slow_high_watermark(**_kwargs: object) -> object:
        await asyncio.sleep(1)
        return SimpleNamespace(last_seq=1)

    event_store = SimpleNamespace(
        read_authoritative_session_high_watermark=AsyncMock(side_effect=_slow_high_watermark)
    )
    service = ClusterSignalService(
        database_url="postgresql://localhost/cognis",
        controller_id="controller-b",
        session_factory=_SessionContext,
        event_bus=EventBus(),
        scope_provider=lambda: [{"session_id": f"session-{index}"} for index in range(256)],
        transport=_FakeTransport([]),
        event_store=event_store,
        owner_token_secret="shared-secret",
    )
    monkeypatch.setattr(cluster_signals_module, "RECONCILE_SCOPE_TIMEOUT_SECONDS", 0.05)

    started = monotonic()
    await service.reconcile_once()

    assert monotonic() - started < 2
    assert service._watermarks == {}  # noqa: SLF001
    assert event_store.read_authoritative_session_high_watermark.await_count == MAX_RECONCILE_SCOPES


@pytest.mark.asyncio
async def test_session_watermark_closes_database_session_before_event_store_read() -> None:
    state = SimpleNamespace(closed=False)

    class SessionContext(_SessionContext):
        async def __aenter__(self) -> SessionContext:
            state.closed = False
            return self

        async def __aexit__(self, *_args: object) -> None:
            state.closed = True

    async def read_high_watermark(**_kwargs: object) -> object:
        assert state.closed is True
        return SimpleNamespace(last_seq=7)

    service = ClusterSignalService(
        database_url="postgresql://localhost/cognis",
        controller_id="controller-b",
        session_factory=SessionContext,
        event_bus=EventBus(),
        scope_provider=lambda: [],
        transport=_FakeTransport([]),
        event_store=SimpleNamespace(read_authoritative_session_high_watermark=read_high_watermark),
        owner_token_secret="shared-secret",
    )

    watermark = await service._scope_watermark(  # noqa: SLF001
        ClusterSignalScope(session_id="session-1")
    )

    assert watermark == '["event_store:7"]'


@pytest.mark.asyncio
async def test_sqlite_mode_creates_no_background_tasks_or_publishes() -> None:
    transport = _FakeTransport([])
    service = ClusterSignalService(
        database_url="sqlite+aiosqlite:///cognis.db",
        controller_id="controller-local",
        session_factory=_unused_session_factory,
        event_bus=EventBus(),
        scope_provider=lambda: [],
        transport=transport,
        owner_token_secret="shared-secret",
    )
    await service.start()
    await service.publish(
        ClusterSignalKind.CHAT_SCOPE_CHANGED,
        scope=ClusterSignalScope(conversation_id="conv-1"),
        revision=1,
    )
    assert service._listener_task is None  # noqa: SLF001
    assert service._dispatch_task is None  # noqa: SLF001
    assert service._reconcile_task is None  # noqa: SLF001
