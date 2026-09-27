"""Wire compatibility and snapshot isolation for low-allocation cache codecs."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock

import pytest

from cognis.core.redis_service import RedisService
from cognis.core.session_cache import (
    CachedEvent,
    CachedSessionState,
    SessionCache,
    _serialize_entry,
)


@pytest.mark.asyncio
async def test_checkpoint_wire_bytes_and_snapshot_are_preserved(monkeypatch: pytest.MonkeyPatch):
    service = RedisService("")
    entry = CachedSessionState(
        session_id="session-memory",
        intaris_session_id="session-memory",
        initialized=True,
        last_event_seq=1,
        events=[
            CachedEvent(
                seq=1,
                type="tool_result",
                data={"nested": [{"text": "Příliš 🐈 " * 1000}], "number": 1.25},
            )
        ],
    )
    expected = json.dumps(
        {
            "previous": "",
            "events": [
                {
                    "seq": 1,
                    "type": "tool_result",
                    "data": entry.events[0].data,
                    "source": None,
                    "ts": None,
                }
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    captured = {}

    async def store(key: str, payload: bytes, *, ttl_seconds: int) -> bool:
        entry.events[0].data["nested"][0]["text"] = "changed while Redis is awaited"
        captured["payload"] = payload
        assert key.endswith(hashlib.sha256(expected).hexdigest()[:24])
        return True

    monkeypatch.setattr(service, "set", store)
    monkeypatch.setattr(service, "eval", AsyncMock(return_value=1))
    cache = SessionCache(AsyncMock(), redis_service=service)
    await cache._redis_set(entry)  # noqa: SLF001
    assert captured["payload"] == expected


@pytest.mark.asyncio
async def test_legacy_snapshot_hydration(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = CachedSessionState(
        session_id="session-legacy-memory",
        intaris_session_id="session-legacy-memory",
        initialized=True,
        events=[CachedEvent(seq=7, type="tool_result", data={"content": "Příliš 🐈"})],
        last_event_seq=7,
    )
    raw = _serialize_entry(entry).encode()
    service = RedisService("")
    monkeypatch.setattr(service, "get", AsyncMock(side_effect=[None, raw]))
    restored = await SessionCache(AsyncMock(), redis_service=service)._redis_get(entry.session_id)
    assert restored is not None
    assert restored.events == entry.events
    assert restored.event_seqs == {7}


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk", [None, b"{}", b'{"events":[{"seq":"bad"}]}'])
async def test_unusable_chunk_is_a_cache_miss(
    monkeypatch: pytest.MonkeyPatch, chunk: bytes | None
) -> None:
    metadata = json.dumps(
        {
            "schema_version": 4,
            "session_id": "session-malformed-memory",
            "intaris_session_id": "session-malformed-memory",
            "event_head": "cognis:session-cache:v3:session-malformed-memory:chunk:broken",
        }
    ).encode()
    service = RedisService("")
    monkeypatch.setattr(service, "get", AsyncMock(side_effect=[metadata, chunk]))
    cache = SessionCache(AsyncMock(), redis_service=service)
    assert await cache._redis_get("session-malformed-memory") is None
