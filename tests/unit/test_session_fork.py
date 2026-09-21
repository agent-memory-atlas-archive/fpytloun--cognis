from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from cognis.core.canonical_history import CanonicalHistoryUnavailable, read_complete_history
from cognis.core.immutable_prefix import ImmutablePrefixEntry
from cognis.core.session_cache import CachedEvent
from cognis.core.session_fork import fork_session_events
from cognis.models.session import EventReadResult, SessionEvent


class _SessionCache:
    def __init__(self) -> None:
        self.events: list[CachedEvent] = [
            CachedEvent(seq=1, type="system_message", data={"content": "old identity"}),
            CachedEvent(seq=2, type="user_message", data={"content": "source input"}),
        ]
        self.prefix_entries: list[ImmutablePrefixEntry] = [
            ImmutablePrefixEntry(role="system", source="identity", content="old identity", seq=1),
            ImmutablePrefixEntry(
                role="developer",
                source="core_memories",
                content="private owner memory",
                seq=2,
            ),
        ]
        self.seeded_events: list[CachedEvent] = []
        self.seed_last_seqs: list[int] = []
        self.stored_prefix: list[ImmutablePrefixEntry] = []

    def get_entry(self, session_id: str) -> object:
        del session_id
        return SimpleNamespace(initialized=True, canonical_stale=False, events=self.events)

    def get_prefix_entries(self, session_id: str) -> list[ImmutablePrefixEntry]:
        del session_id
        return list(self.prefix_entries)

    async def seed_events(self, session: object, events: list[CachedEvent], last_seq: int) -> None:
        del session
        self.seeded_events.extend(events)
        self.seed_last_seqs.append(last_seq)

    async def append_recorded_events(
        self, session: object, events: list[object], result: object
    ) -> None:
        del session, events, result

    async def store_prefix_snapshot(
        self,
        session_id: str,
        entries: list[ImmutablePrefixEntry],
        *,
        snapshot_seq: int,
        snapshot_source: str,
    ) -> None:
        del session_id, snapshot_seq, snapshot_source
        self.stored_prefix = list(entries)


class _Guardrails:
    def __init__(self, source: _SessionCache | None = None) -> None:
        self.source = source or _SessionCache()
        self.recorded_events: list[SessionEvent] = []
        self.recorded_batches: list[list[SessionEvent]] = []
        self.read_kwargs: list[dict[str, object]] = []

    async def read_events(self, **kwargs: object) -> object:
        self.read_kwargs.append(dict(kwargs))
        events = [
            {
                "type": f"{entry.role}_message",
                "data": {
                    "role": entry.role,
                    "source": entry.source,
                    "content": entry.content,
                },
            }
            for entry in self.source.prefix_entries
        ] + [
            {"type": event.type, "data": event.data}
            for event in self.source.events
            if event.type != "system_message"
        ]
        return EventReadResult(
            events=[{"seq": index, **event} for index, event in enumerate(events, 1)],
            last_seq=len(events),
            has_more=False,
        )

    async def record_events(self, **kwargs: object) -> object:
        events = cast(list[SessionEvent], kwargs.get("events", []))
        first_seq = len(self.recorded_events) + 1
        self.recorded_batches.append(events)
        self.recorded_events.extend(events)
        return SimpleNamespace(ok=True, first_seq=first_seq, last_seq=len(self.recorded_events))


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_reference", [False, True])
async def test_fork_inherits_only_complete_latest_prefix_snapshot(
    missing_reference: bool,
) -> None:
    class SnapshotSource(_Guardrails):
        async def read_events(self, **kwargs: object) -> EventReadResult:
            return EventReadResult(
                events=[
                    {
                        "seq": 1,
                        "type": "system_message",
                        "data": {
                            "role": "system",
                            "source": "identity",
                            "content": "old identity",
                        },
                    },
                    {
                        "seq": 2,
                        "type": "system_message",
                        "data": {
                            "role": "system",
                            "source": "identity",
                            "content": "current identity",
                        },
                    },
                    {
                        "seq": 3,
                        "type": "context_snapshot",
                        "data": {
                            "entries": [{"seq": 4 if missing_reference else 2}],
                        },
                    },
                ],
                last_seq=3,
                has_more=False,
            )

    cache, guardrails = _SessionCache(), SnapshotSource()

    async def copy() -> bool:
        return await fork_session_events(
            providers=SimpleNamespace(guardrails=guardrails),
            session_cache=cache,
            source_cognis_session_id="source-session",
            source_intaris_session_id="source-intaris",
            target_session=SimpleNamespace(session_id="target", intaris_session_id="target"),
            source_label="conversation_fork",
        )

    if missing_reference:
        with pytest.raises(CanonicalHistoryUnavailable):
            await copy()
        assert cache.seeded_events == []
    else:
        assert await copy()
        assert [entry.content for entry in cache.stored_prefix] == ["current identity"]


@pytest.mark.asyncio
async def test_cancelled_fork_does_not_publish_or_complete_partial_history() -> None:
    import asyncio

    class CancelAppend(_Guardrails):
        async def record_events(self, **kwargs: object) -> object:
            if len(self.recorded_batches) == 1:
                raise asyncio.CancelledError
            return await super().record_events(**kwargs)

    cache, guardrails = _SessionCache(), CancelAppend()
    with pytest.raises(asyncio.CancelledError):
        await fork_session_events(
            providers=SimpleNamespace(guardrails=guardrails),
            session_cache=cache,
            source_cognis_session_id="source-session",
            source_intaris_session_id="source-intaris",
            target_session=SimpleNamespace(session_id="target", intaris_session_id="target"),
            source_label="conversation_fork",
        )
    assert cache.seeded_events == []
    assert [event.data.get("event") for event in guardrails.recorded_events] == [
        "history_copy_started",
    ]


@pytest.mark.asyncio
async def test_failed_source_read_leaves_durable_incomplete_fork_boundary() -> None:
    cache = _SessionCache()
    cache.events = []

    class MissingStream(_Guardrails):
        async def read_events(self, **kwargs: object) -> object:
            if kwargs["session_id"] == "source-intaris":
                return EventReadResult(
                    events=[],
                    last_seq=0,
                    has_more=False,
                    missing_stream_fallback_used=True,
                )
            return EventReadResult(
                events=[
                    {"seq": index, "type": event.type, "data": event.data}
                    for index, event in enumerate(self.recorded_events, 1)
                ],
                last_seq=len(self.recorded_events),
                has_more=False,
            )

    guardrails = MissingStream()
    with pytest.raises(CanonicalHistoryUnavailable, match="source history"):
        await fork_session_events(
            providers=SimpleNamespace(guardrails=guardrails),
            session_cache=cache,
            source_cognis_session_id="source-session",
            source_intaris_session_id="source-intaris",
            target_session=SimpleNamespace(session_id="target", intaris_session_id="target"),
            source_label="conversation_fork",
        )
    assert cache.seeded_events == []
    assert cache.stored_prefix == []
    # A different controller, without the local cache, also refuses this target.
    with pytest.raises(CanonicalHistoryUnavailable, match="incomplete"):
        await read_complete_history(guardrails, "target")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", [0, 1, 2, 3, 4])
async def test_fork_never_publishes_partial_copy(failure_stage: int) -> None:
    cache = _SessionCache()

    class RejectAppend(_Guardrails):
        async def record_events(self, **kwargs: object) -> object:
            if len(self.recorded_batches) == failure_stage:
                return SimpleNamespace(ok=False, first_seq=0, last_seq=0)
            return await super().record_events(**kwargs)

    guardrails = RejectAppend()
    with pytest.raises(CanonicalHistoryUnavailable):
        await fork_session_events(
            providers=SimpleNamespace(guardrails=guardrails),
            session_cache=cache,
            source_cognis_session_id="source-session",
            source_intaris_session_id="source-intaris",
            target_session=SimpleNamespace(session_id="target", intaris_session_id="target"),
            source_label="conversation_fork",
        )
    assert cache.seeded_events == []
    assert cache.stored_prefix == []
    assert not any(
        event.data.get("event") == "history_copy_completed" for event in guardrails.recorded_events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("canonical_stale", [False, True])
async def test_fork_verifies_durable_history_even_with_nonempty_cache(
    canonical_stale: bool,
) -> None:
    class StaleCache(_SessionCache):
        def get_entry(self, session_id: str) -> object:
            return SimpleNamespace(
                initialized=True, canonical_stale=canonical_stale, events=self.events
            )

    class PagedGuardrails(_Guardrails):
        async def read_events(self, **kwargs: object) -> object:
            self.read_kwargs.append(dict(kwargs))
            seq = 1 if kwargs["after_seq"] == 0 else 2
            return EventReadResult(
                events=[{"seq": seq, "type": "user_message", "data": {"content": f"page {seq}"}}],
                last_seq=2,
                has_more=seq == 1,
            )

    cache, guardrails = StaleCache(), PagedGuardrails()
    assert await fork_session_events(
        providers=SimpleNamespace(guardrails=guardrails),
        session_cache=cache,
        source_cognis_session_id="source-session",
        source_intaris_session_id="source-intaris",
        target_session=SimpleNamespace(session_id="target", intaris_session_id="target"),
        source_label="conversation_fork",
    )
    assert [call["after_seq"] for call in guardrails.read_kwargs] == [0, 1]
    assert [
        event.data["content"] for event in cache.seeded_events if event.type == "user_message"
    ] == [
        "page 1",
        "page 2",
    ]
    assert cache.stored_prefix == []  # stale cached prefix must not leak into the durable copy


@pytest.mark.asyncio
async def test_fork_session_events_can_skip_source_prefix() -> None:
    cache = _SessionCache()
    guardrails = _Guardrails(cache)

    copied = await fork_session_events(
        providers=SimpleNamespace(guardrails=guardrails),
        session_cache=cache,
        source_cognis_session_id="source-session",
        source_intaris_session_id="source-intaris",
        target_session=SimpleNamespace(
            session_id="target-session", intaris_session_id="target-intaris"
        ),
        source_label="plan",
        copy_prefix=False,
    )

    assert copied is True
    assert [event.type for event in cache.seeded_events] == ["lifecycle", "user_message"]
    assert cache.stored_prefix == []
    assert [event.type for event in guardrails.recorded_events] == [
        "lifecycle",
        "user_message",
        "lifecycle",
    ]


@pytest.mark.asyncio
async def test_fork_session_events_preserves_copied_event_payloads() -> None:
    cache = _SessionCache()
    cache.events = [
        CachedEvent(seq=1, type="user_message", data={"content": "without turn"}),
        CachedEvent(
            seq=2,
            type="assistant_message",
            data={"content": "with turn", "turn_id": "turn-1"},
        ),
    ]
    guardrails = _Guardrails(cache)

    copied = await fork_session_events(
        providers=SimpleNamespace(guardrails=guardrails),
        session_cache=cache,
        source_cognis_session_id="source-session",
        source_intaris_session_id="source-intaris",
        target_session=SimpleNamespace(
            session_id="target-session", intaris_session_id="target-intaris"
        ),
        source_label="undo",
        copy_prefix=False,
    )

    assert copied is True
    assert [event.data for event in guardrails.recorded_events[1:-1]] == [
        {"content": "without turn"},
        {"content": "with turn", "turn_id": "turn-1"},
    ]
    assert "turn_id" not in guardrails.recorded_events[1].model_dump()["data"]


@pytest.mark.asyncio
async def test_fork_session_events_can_require_durable_source_history() -> None:
    cache = _SessionCache()
    cache.events = [CachedEvent(seq=1, type="user_message", data={"content": "stale"})]

    class _DurableGuardrails(_Guardrails):
        async def read_events(self, **kwargs: object) -> object:
            self.read_kwargs.append(dict(kwargs))
            return EventReadResult(
                last_seq=2,
                has_more=False,
                events=[
                    {"seq": 1, "type": "user_message", "data": {"content": "one"}},
                    {"seq": 2, "type": "assistant_message", "data": {"content": "two"}},
                ],
            )

    guardrails = _DurableGuardrails()

    copied = await fork_session_events(
        providers=SimpleNamespace(guardrails=guardrails),
        session_cache=cache,
        source_cognis_session_id="source-session",
        source_intaris_session_id="source-intaris",
        target_session=SimpleNamespace(
            session_id="target-session", intaris_session_id="target-intaris"
        ),
        source_label="reuse_recovery",
        copy_prefix=False,
    )

    assert copied is True
    assert guardrails.read_kwargs == [
        {
            "session_id": "source-intaris",
            "after_seq": 0,
            "allow_missing_stream": False,
        }
    ]
    assert [event.data["content"] for event in guardrails.recorded_events[1:-1]] == ["one", "two"]


@pytest.mark.asyncio
async def test_fork_session_events_copies_source_events_in_intaris_sized_batches() -> None:
    cache = _SessionCache()
    cache.events = [
        CachedEvent(seq=index, type="user_message", data={"content": f"message {index}"})
        for index in range(1, 1003)
    ]
    guardrails = _Guardrails(cache)

    copied = await fork_session_events(
        providers=SimpleNamespace(guardrails=guardrails),
        session_cache=cache,
        source_cognis_session_id="source-session",
        source_intaris_session_id="source-intaris",
        target_session=SimpleNamespace(
            session_id="target-session", intaris_session_id="target-intaris"
        ),
        source_label="conversation_fork",
        copy_prefix=False,
    )

    assert copied is True
    assert [len(batch) for batch in guardrails.recorded_batches] == [1, 1000, 2, 1]
    assert len(cache.seeded_events) == 1003
    assert [event.seq for event in cache.seeded_events] == list(range(1, 1004))
    assert cache.seed_last_seqs == [1, 1001, 1003]
    assert guardrails.recorded_events[1].data == {"content": "message 1"}
    assert guardrails.recorded_events[-2].data == {"content": "message 1002"}


@pytest.mark.asyncio
async def test_fork_session_events_skips_non_appendable_source_events() -> None:
    cache = _SessionCache()
    cache.events = [
        CachedEvent(seq=1, type="user_message", data={"content": "copy me"}),
        CachedEvent(seq=2, type="tool_result_chunk", data={"content": "live only"}),
        CachedEvent(seq=3, type="assistant_message", data={"content": "copy me too"}),
    ]
    guardrails = _Guardrails(cache)

    copied = await fork_session_events(
        providers=SimpleNamespace(guardrails=guardrails),
        session_cache=cache,
        source_cognis_session_id="source-session",
        source_intaris_session_id="source-intaris",
        target_session=SimpleNamespace(
            session_id="target-session", intaris_session_id="target-intaris"
        ),
        source_label="task_chat",
        copy_prefix=False,
    )

    assert copied is True
    assert [event.type for event in guardrails.recorded_events] == [
        "lifecycle",
        "user_message",
        "assistant_message",
        "lifecycle",
    ]
    assert [event.type for event in cache.seeded_events] == [
        "lifecycle",
        "user_message",
        "assistant_message",
    ]


@pytest.mark.asyncio
async def test_fork_session_events_preserves_prefix_by_default() -> None:
    cache = _SessionCache()
    guardrails = _Guardrails(cache)

    copied = await fork_session_events(
        providers=SimpleNamespace(guardrails=guardrails),
        session_cache=cache,
        source_cognis_session_id="source-session",
        source_intaris_session_id="source-intaris",
        target_session=SimpleNamespace(
            session_id="target-session", intaris_session_id="target-intaris"
        ),
        source_label="conversation_fork",
    )

    assert copied is True
    assert [entry.source for entry in cache.stored_prefix] == ["identity", "core_memories"]
    assert [event.type for event in guardrails.recorded_events] == [
        "lifecycle",
        "user_message",
        "system_message",
        "developer_message",
        "context_snapshot",
        "lifecycle",
    ]
    assert all(
        "turn_id" not in event.model_dump()["data"] for event in guardrails.recorded_events[1:]
    )


@pytest.mark.asyncio
async def test_fork_session_events_allows_confirmed_empty_source_stream() -> None:
    cache = _SessionCache()
    cache.events = []
    cache.prefix_entries = []
    guardrails = _Guardrails(cache)

    copied = await fork_session_events(
        providers=SimpleNamespace(guardrails=guardrails),
        session_cache=cache,
        source_cognis_session_id="source-session",
        source_intaris_session_id="source-intaris",
        target_session=SimpleNamespace(
            session_id="target-session", intaris_session_id="target-intaris"
        ),
        source_label="conversation_fork",
    )

    assert copied is False
    assert guardrails.read_kwargs == [
        {
            "session_id": "source-intaris",
            "after_seq": 0,
            "allow_missing_stream": False,
        }
    ]
    assert [event.data["event"] for event in guardrails.recorded_events] == [
        "history_copy_started",
        "history_copy_completed",
    ]
