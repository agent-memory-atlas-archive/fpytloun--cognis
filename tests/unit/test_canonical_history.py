from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cognis.core.canonical_history import CanonicalHistoryUnavailable, read_complete_history
from cognis.core.immutable_prefix import ImmutablePrefixEntry
from cognis.core.session_cache import CachedEvent, CachedSessionState, SessionCache
from cognis.models.session import EventHistoryGap, EventReadResult


@pytest.mark.asyncio
async def test_complete_history_reads_all_pages_and_uses_event_cursor() -> None:
    from types import SimpleNamespace

    read = AsyncMock(
        side_effect=[
            EventReadResult(events=[{"seq": 1}], last_seq=99, has_more=True),
            EventReadResult(events=[{"seq": 2}], last_seq=99, has_more=False),
        ]
    )
    result = await read_complete_history(SimpleNamespace(read_events=read), "source")
    assert [event["seq"] for event in result.events] == [1, 2]
    assert [call.kwargs["after_seq"] for call in read.await_args_list] == [0, 1]
    assert all(call.kwargs["allow_missing_stream"] is False for call in read.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "gap", "page_error", "copy"])
async def test_complete_history_rejects_incomplete_results(failure: str) -> None:
    from types import SimpleNamespace

    page = EventReadResult(events=[], last_seq=0, has_more=False)
    if failure == "missing":
        page.missing_stream_fallback_used = True
    elif failure == "gap":
        page.history_gap = EventHistoryGap(from_seq=1, to_seq=3, reason="internal_gap")
    elif failure == "copy":
        page.events = [
            {
                "seq": 1,
                "type": "lifecycle",
                "data": {"event": "history_copy_started", "history_copy_id": "target"},
            }
        ]
    read = AsyncMock(return_value=page)
    if failure == "page_error":
        read.side_effect = [
            EventReadResult(events=[{"seq": 1}], last_seq=2, has_more=True),
            RuntimeError("read failed"),
        ]
    with pytest.raises((CanonicalHistoryUnavailable, RuntimeError)):
        await read_complete_history(SimpleNamespace(read_events=read), "source")


@pytest.mark.asyncio
async def test_snapshot_survives_invalidation_and_nested_mutation() -> None:
    cache = SessionCache(None)
    entry = CachedSessionState(
        session_id="source",
        intaris_session_id="source",
        initialized=True,
        events=[
            CachedEvent(seq=1, type="user_message", data={"content": "implement", "nested": [1]})
        ],
        prefix_entries=[ImmutablePrefixEntry(role="system", source="identity", content="identity")],
        last_compaction_summary="previous summary",
    )
    cache._entries["source"] = entry
    snapshot = cache.get_context_snapshot("source")
    entry.events[0].data["nested"].append(2)
    await cache.invalidate_canonical("source")
    assert snapshot.events[0].data == {"content": "implement", "nested": [1]}
    assert snapshot.prefix_entries[0].content == "identity"
    assert snapshot.last_compaction_summary == "previous summary"
    with pytest.raises(CanonicalHistoryUnavailable):
        cache.get_context_snapshot("source")


@pytest.mark.parametrize("missing", ["user_message", "tool_call", "tool_result", "lifecycle", None])
def test_profile_continuation_requires_entire_turn_boundary(missing: str | None) -> None:
    cache = SessionCache(None)
    events = [
        CachedEvent(
            seq=index,
            type=kind,
            data={
                "turn_id": "turn",
                "call_id": "switch-call",
                "kind": "agent_profile_changed",
                "content": "implement",
            },
        )
        for index, kind in enumerate(("user_message", "tool_call", "tool_result", "lifecycle"), 1)
        if kind != missing
    ]
    cache._entries["source"] = CachedSessionState(
        session_id="source", intaris_session_id="source", initialized=True, events=events
    )
    snapshot = cache.get_context_snapshot("source")
    if missing is None:
        snapshot.require_turn("turn", user_event=True, profile_switch=True)
    else:
        with pytest.raises(CanonicalHistoryUnavailable):
            snapshot.require_turn("turn", user_event=True, profile_switch=True)
