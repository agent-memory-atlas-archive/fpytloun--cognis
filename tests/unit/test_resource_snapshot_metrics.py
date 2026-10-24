"""Snapshot diagnostics must not weaken canonical isolation or fail the turn."""

from unittest.mock import Mock

from cognis.core import session_cache


def test_snapshot_instrumentation_preserves_nested_isolation(monkeypatch):
    duration, items = Mock(), Mock()
    monkeypatch.setattr(session_cache, "CONTEXT_SNAPSHOT_COPY_SECONDS", duration)
    monkeypatch.setattr(session_cache, "CONTEXT_SNAPSHOT_ITEMS", items)
    entry = session_cache.CachedSessionState(
        session_id="snapshot",
        intaris_session_id="snapshot-intaris",
        events=[
            session_cache.CachedEvent(seq=1, type="user_message", data={"nested": {"values": [1]}})
        ],
    )
    snapshot = session_cache.SessionCache._context_snapshot(entry)
    snapshot.events[0].data["nested"]["values"].append(2)
    assert entry.events[0].data["nested"]["values"] == [1]
    duration.observe.assert_called_once()
    items.observe.assert_called_once_with(1)
    duration.observe.side_effect = RuntimeError("metrics unavailable")
    assert session_cache.SessionCache._context_snapshot(entry).events == entry.events
