"""Complete, fail-closed reads of the durable session history."""

from __future__ import annotations

from typing import Any

from cognis.models.session import EventReadResult, next_event_page_after_seq


class CanonicalHistoryUnavailable(RuntimeError):
    """Required session history is unavailable; inference must not proceed."""


def require_completed_history_copy(event_data: list[dict[str, Any]]) -> None:
    """Reject a fork whose durable history copy was interrupted."""
    pending: set[str] = set()
    for data in event_data:
        copy_id = data.get("history_copy_id")
        if not isinstance(copy_id, str):
            continue
        if data.get("event") == "history_copy_started":
            pending.add(copy_id)
        elif data.get("event") == "history_copy_completed":
            pending.discard(copy_id)
    if pending:
        raise CanonicalHistoryUnavailable("Session history copy is incomplete; recreate the fork")


async def read_complete_history(
    guardrails: Any, session_id: str, *, after_seq: int = 0, max_pages: int = 50
) -> EventReadResult:
    """Read every page or fail without publishing partial results.

    This operation owns no cache state or database transaction. Cancellation
    propagates to its caller; retry always starts at the caller's watermark.
    """
    events: list[dict[str, Any]] = []
    cursor = after_seq
    for _ in range(max_pages):
        page = await guardrails.read_events(
            session_id=session_id, after_seq=cursor, allow_missing_stream=False
        )
        if getattr(page, "missing_stream_fallback_used", False):
            raise CanonicalHistoryUnavailable("Canonical event stream is unavailable")
        gap = getattr(page, "history_gap", None)
        if gap is not None and gap.to_seq > cursor:
            raise CanonicalHistoryUnavailable("Canonical event stream contains a history gap")
        events.extend(page.events)
        next_cursor = next_event_page_after_seq(page, cursor)
        if next_cursor is None:
            if after_seq == 0:
                require_completed_history_copy(
                    [event.get("data", {}) for event in events if event.get("type") == "lifecycle"]
                )
            return EventReadResult(events=events, last_seq=page.last_seq, has_more=False)
        cursor = next_cursor
    raise CanonicalHistoryUnavailable("Canonical event pagination exceeded its safety limit")
