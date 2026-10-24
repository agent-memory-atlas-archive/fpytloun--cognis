"""Durable, first-writer-owned retry notices for recovered direct turns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from cognis.core.canonical_history import read_complete_history
from cognis.models.session import EventAppendResult, SessionEvent


class RetryNoticePersistenceError(RuntimeError):
    """The retry admission notice could not be durably recorded or reconciled."""

    def __init__(self, *, recoverable: bool) -> None:
        super().__init__("The recovery notice could not be persisted in the event store.")
        self.recoverable = recoverable


@dataclass(frozen=True)
class RetryNoticeReceipt:
    event: SessionEvent
    appended: EventAppendResult | None


async def record_retry_notice(
    guardrails: Any,
    session_id: str,
    event: SessionEvent,
    *,
    idempotency_key: str,
    source_turn_id: str,
    user_email: str,
    agent_id: str,
    agent_owner_email: str,
) -> RetryNoticeReceipt:
    """Reuse canonical notices, including ones written by older controllers.

    One notice belongs to a recovery turn, not a controller lease attempt.
    Attempt/reason fields are first-writer diagnostics, never mutable append
    arguments. Reads use Intaris, not a replica-local cache. The scheduler owns
    the turn lease and cancellation; no DB transaction spans these calls.
    """

    async def existing() -> SessionEvent | None:
        history = await read_complete_history(guardrails, session_id)
        for item in history.events:
            data = item.get("data")
            if not isinstance(data, dict):
                continue
            if (
                item.get("type") == "system_message"
                and data.get("notice_id") == event.data["notice_id"]
                and data.get("turn_id") == event.data["turn_id"]
                and data.get("kind") == "model_recovery"
                and data.get("retry_source_turn_id") == source_turn_id
                and data.get("event") == "system_notice"
                and data.get("scope") == "turn"
            ):
                return SessionEvent.model_validate(item)
        return None

    try:
        found = await existing()
        if found is not None:
            return RetryNoticeReceipt(found, None)
        try:
            appended = await guardrails.record_events(
                session_id=session_id,
                events=[event],
                source="cognis",
                idempotency_key=idempotency_key,
                user_email=user_email,
                agent_id=agent_id,
                agent_owner_email=agent_owner_email,
            )
        except (httpx.HTTPError, TimeoutError) as exc:
            # A conflict or lost response can follow a committed write. Accept
            # only a matching canonical notice, never a conflict alone.
            found = await existing()
            if found is None:
                raise exc
            return RetryNoticeReceipt(found, None)
        if not appended.ok:
            raise RetryNoticePersistenceError(recoverable=True)
        return RetryNoticeReceipt(event, appended)
    except RetryNoticePersistenceError:
        raise
    except Exception as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        recoverable = isinstance(exc, (httpx.TransportError, TimeoutError)) or (
            status is not None and (status == 429 or status >= 500)
        )
        raise RetryNoticePersistenceError(recoverable=recoverable) from exc
