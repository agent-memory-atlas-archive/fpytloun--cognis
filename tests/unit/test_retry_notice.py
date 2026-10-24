from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from cognis.core.retry_notice import RetryNoticePersistenceError, record_retry_notice
from cognis.core.turn_scheduler import classify_turn_error
from cognis.models.session import EventAppendResult, EventReadResult, SessionEvent


def notice(attempt=2, reason="controller_restart"):
    return SessionEvent(
        type="system_message",
        data={
            "event": "system_notice",
            "notice_id": "retry:recovery-turn",
            "kind": "model_recovery",
            "scope": "turn",
            "turn_id": "recovery-turn",
            "retry_source_turn_id": "source-turn",
            "retry_reason": reason,
            "attempt": attempt,
            "content": "Recovery context",
        },
    )


async def persist(guardrails, event):
    return await record_retry_notice(
        guardrails,
        "session",
        event,
        idempotency_key="session:retry_turn:recovery-turn",
        source_turn_id="source-turn",
        user_email="alice@cognis.local",
        agent_id="agent",
        agent_owner_email="alice@cognis.local",
    )


@pytest.mark.asyncio
async def test_new_worker_reuses_original_payload_after_attempt_and_reason_change():
    canonical = notice()
    stored = {**canonical.model_dump(mode="json"), "seq": 5}
    guardrails = SimpleNamespace(
        read_events=AsyncMock(
            return_value=EventReadResult(events=[stored], last_seq=5, has_more=False)
        ),
        record_events=AsyncMock(),
    )
    receipt = await persist(guardrails, notice(3, "transient_runtime"))
    assert receipt.appended is None
    assert receipt.event.data == canonical.data
    guardrails.record_events.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_response", [False, True])
async def test_committed_race_or_lost_response_reconciles_from_durable_owner(lost_response):
    canonical = notice()
    stored = {**canonical.model_dump(mode="json"), "seq": 5}
    error = (
        httpx.ReadTimeout("response lost")
        if lost_response
        else httpx.HTTPStatusError(
            "conflict",
            request=httpx.Request("POST", "https://intaris.local/events"),
            response=httpx.Response(409),
        )
    )
    guardrails = SimpleNamespace(
        read_events=AsyncMock(
            side_effect=[
                EventReadResult(events=[], last_seq=0, has_more=False),
                EventReadResult(events=[stored], last_seq=5, has_more=False),
            ]
        ),
        record_events=AsyncMock(side_effect=error),
    )
    receipt = await persist(guardrails, notice(3))
    assert receipt.appended is None
    assert receipt.event.data["attempt"] == 2
    guardrails.record_events.assert_awaited_once()


@pytest.mark.asyncio
async def test_unverified_conflict_is_not_accepted_or_reported_as_llm_failure():
    wrong = notice().model_dump(mode="json")
    wrong["data"]["retry_source_turn_id"] = "different-source"
    guardrails = SimpleNamespace(
        read_events=AsyncMock(
            return_value=EventReadResult(events=[wrong], last_seq=1, has_more=False)
        ),
        record_events=AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "conflict",
                request=httpx.Request("POST", "https://intaris.local/events"),
                response=httpx.Response(409),
            )
        ),
    )
    with pytest.raises(RetryNoticePersistenceError) as failure:
        await persist(guardrails, notice(3))
    classified = await classify_turn_error(SimpleNamespace(), failure.value)
    assert classified.code == "event_persistence_error:intaris"
    assert not classified.recoverable


@pytest.mark.asyncio
async def test_new_notice_is_written_with_original_metadata_and_key():
    event = notice()
    before = deepcopy(event.data)
    guardrails = SimpleNamespace(
        read_events=AsyncMock(return_value=EventReadResult(events=[], last_seq=0, has_more=False)),
        record_events=AsyncMock(
            return_value=EventAppendResult(ok=True, count=1, first_seq=1, last_seq=1)
        ),
    )
    receipt = await persist(guardrails, event)
    assert receipt.appended.count == 1
    assert event.data == before
    assert (
        guardrails.record_events.call_args.kwargs["idempotency_key"]
        == "session:retry_turn:recovery-turn"
    )


@pytest.mark.asyncio
async def test_storage_outage_remains_retryable_not_a_model_error():
    guardrails = SimpleNamespace(
        read_events=AsyncMock(side_effect=httpx.ConnectTimeout("unavailable")),
        record_events=AsyncMock(),
    )
    with pytest.raises(RetryNoticePersistenceError) as failure:
        await persist(guardrails, notice())
    classified = await classify_turn_error(SimpleNamespace(), failure.value)
    assert classified.code == "event_persistence_error:intaris"
    assert classified.transient
    guardrails.record_events.assert_not_called()


@pytest.mark.asyncio
async def test_append_rejection_is_a_typed_retryable_storage_error():
    guardrails = SimpleNamespace(
        read_events=AsyncMock(return_value=EventReadResult(events=[], last_seq=0, has_more=False)),
        record_events=AsyncMock(
            return_value=EventAppendResult(ok=False, count=0, first_seq=0, last_seq=0)
        ),
    )
    with pytest.raises(RetryNoticePersistenceError) as failure:
        await persist(guardrails, notice())
    classified = await classify_turn_error(SimpleNamespace(), failure.value)
    assert classified.code == "event_persistence_error:intaris"
    assert classified.transient


@pytest.mark.asyncio
async def test_existing_notice_refresh_failure_is_not_a_model_error():
    from cognis.core.turn_scheduler import RetryReason, TurnScheduler

    stored = notice().model_dump(mode="json")
    guardrails = SimpleNamespace(
        read_events=AsyncMock(
            return_value=EventReadResult(events=[stored], last_seq=1, has_more=False)
        ),
        record_events=AsyncMock(),
    )
    scheduler = object.__new__(TurnScheduler)
    scheduler._providers = SimpleNamespace(guardrails=guardrails)
    scheduler._session_cache = SimpleNamespace(
        refresh=AsyncMock(side_effect=RuntimeError("cache unavailable"))
    )
    with pytest.raises(RetryNoticePersistenceError) as failure:
        await scheduler._persist_retry_turn_notice(
            conversation_id="conversation",
            session=SimpleNamespace(session_id="session", intaris_session_id="session"),
            agent=SimpleNamespace(agent_id="agent", owner_email="alice@cognis.local"),
            user_email="alice@cognis.local",
            turn_id="recovery-turn",
            retry_source_turn_id="source-turn",
            retry_reason=RetryReason.CONTROLLER_RESTART,
            retry_attempt=3,
            turn_observers=(),
        )
    assert (
        await classify_turn_error(SimpleNamespace(), failure.value)
    ).code == "event_persistence_error:intaris"
    guardrails.record_events.assert_not_called()
