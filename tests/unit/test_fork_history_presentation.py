from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from cognis.api.chat_v2.event_store import IntarisSessionEventStore
from cognis.api.chat_v2.normalizer import normalize_session_events
from cognis.api.chat_v2.projector import project_timeline
from cognis.api.chat_v2.schemas import MessageTimelineItem
from cognis.api.serializers import event_to_response
from cognis.core.event_timestamps import HISTORY_SOURCE_TIMESTAMP
from cognis.core.session_cache import CachedEvent
from cognis.core.session_fork import fork_session_events
from cognis.models.session import EventReadResult
from tests.unit.test_session_fork import _Guardrails, _SessionCache


class _DurableReader:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw

    async def read_events(self, **kwargs: object) -> EventReadResult:
        return EventReadResult(events=[self.raw], last_seq=int(self.raw["seq"]), has_more=False)


@pytest.mark.asyncio
async def test_fork_times_survive_durable_reload_and_refork() -> None:
    original = "2026-10-21T05:47:00+00:00"
    copied_at = "2026-10-21T06:15:54+00:00"
    cache = _SessionCache()
    cache.events = [
        CachedEvent(seq=1, type="assistant_message", data={"content": "Reviewed"}, ts=original)
    ]
    guardrails = _Guardrails(cache)
    for iteration in range(2):
        await fork_session_events(
            providers=SimpleNamespace(guardrails=guardrails),
            session_cache=cache,
            source_cognis_session_id=f"source-{iteration}",
            source_intaris_session_id=f"source-intaris-{iteration}",
            target_session=SimpleNamespace(
                session_id=f"target-{iteration}", intaris_session_id=f"target-intaris-{iteration}"
            ),
            source_label="conversation_fork",
            copy_prefix=False,
        )
        copied = next(
            event for event in guardrails.recorded_events if event.type == "assistant_message"
        )
        assert copied.data[HISTORY_SOURCE_TIMESTAMP] == original
        seeded = next(event for event in cache.seeded_events if event.type == "assistant_message")
        assert seeded.ts == original
        raw = {"seq": 2, "type": copied.type, "data": copied.data, "ts": copied_at}

        page = await IntarisSessionEventStore(_DurableReader(raw)).read_session_events(
            session_id=f"target-intaris-{iteration}"
        )
        projected = project_timeline(normalize_session_events(page.events).events)
        message = projected.timeline.items[0]
        assert isinstance(message, MessageTimelineItem)
        assert datetime.fromisoformat(message.created_at.replace("Z", "+00:00")) == (
            datetime.fromisoformat(original)
        )
        assert event_to_response(raw).timestamp == original
        assert raw["ts"] == copied_at  # The durable audit time remains untouched.

        cache = _SessionCache()
        cache.events = [CachedEvent(seq=2, type=copied.type, data=copied.data, ts=copied_at)]
        guardrails = _Guardrails(cache)


@pytest.mark.parametrize("original", [None, "", "not-a-date", "2026-10-21T05:47:00", {}])
@pytest.mark.asyncio
async def test_invalid_history_timestamp_falls_back_to_audit_time(original: object) -> None:
    copied_at = "2026-10-21T06:15:54+00:00"
    raw = {
        "seq": 1,
        "type": "assistant_message",
        "ts": copied_at,
        "data": {"content": "Reviewed", HISTORY_SOURCE_TIMESTAMP: original},
    }

    class Reader:
        async def read_events(self, **kwargs: object) -> EventReadResult:
            return EventReadResult(events=[raw], last_seq=1, has_more=False)

    page = await IntarisSessionEventStore(Reader()).read_session_events(session_id="target")
    assert page.events[0].timestamp == datetime(2026, 10, 21, 6, 15, 54, tzinfo=UTC)
    assert event_to_response(raw).timestamp == copied_at
