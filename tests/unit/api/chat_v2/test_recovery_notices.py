"""Runtime notices retain metadata and operation-scoped retirement."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cognis.api.websocket import WebSocketConnectionManager, _event_to_payload
from cognis.core.events import Event, EventType


@pytest.mark.asyncio
async def test_system_notice_runtime_adapter_preserves_recovery_metadata() -> None:
    manager = WebSocketConnectionManager(SimpleNamespace(state=SimpleNamespace()))
    manager.send_chat_v2_runtime_to_conversation = AsyncMock()
    data = {
        "conversation_id": "conv-recovery",
        "session_id": "session-recovery",
        "turn_id": "turn-recovery",
        "notice_id": "retry-operation",
        "message": "Retrying",
        "kind": "model_recovery",
        "scope": "retry",
        "provider_id": "codex",
        "model": "gpt-6-sol",
        "retry_at": "2026-09-26T11:30:00Z",
        "retry_after_seconds": 1.1,
        "provider_retry_after_seconds": 1.1,
        "attempt": 1,
        "max_attempts": 3,
        "reason_class": "transport",
        "recoverable": True,
    }
    await manager._handle_event(Event(type=EventType.SYSTEM_NOTICE, data=data))
    item = manager.send_chat_v2_runtime_to_conversation.await_args.kwargs["volatile_items"][0]
    for field in (
        "provider_id",
        "model",
        "retry_at",
        "retry_after_seconds",
        "provider_retry_after_seconds",
        "attempt",
        "max_attempts",
        "reason_class",
        "recoverable",
    ):
        assert getattr(item, field) == data[field]
    assert item.notice_resolved is False
    await manager._handle_event(
        Event(type=EventType.SYSTEM_NOTICE, data={**data, "notice_resolved": True})
    )
    resolved = manager.send_chat_v2_runtime_to_conversation.await_args.kwargs["volatile_items"][0]
    assert resolved.id == item.id
    assert resolved.notice_resolved is True
    assert (
        _event_to_payload(Event(type=EventType.SYSTEM_NOTICE, data=data), "conv-recovery")
        is not None
    )
    assert (
        _event_to_payload(
            Event(type=EventType.SYSTEM_NOTICE, data={**data, "notice_resolved": True}),
            "conv-recovery",
        )
        is None
    )
