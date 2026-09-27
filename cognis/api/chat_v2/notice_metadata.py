"""Shared metadata projection for durable and runtime system notices."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any


def notice_metadata(data: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve typed notice details without admitting arbitrary event fields."""
    result: dict[str, Any] = {}
    for field in (
        "reason_class",
        "provider_id",
        "model",
        "retry_at",
        "follow_up_conversation_id",
        "follow_up_session_id",
    ):
        value = data.get(field)
        if isinstance(value, str) and value:
            result[field] = value
    for field in ("retry_after_seconds", "provider_retry_after_seconds"):
        value = data.get(field)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isfinite(value)
            and value >= 0
        ):
            result[field] = value
    for field in ("max_attempts", "attempts", "attempts_per_cycle", "continuation_attempts"):
        value = data.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[field] = value
    for field in ("recoverable", "notice_resolved"):
        value = data.get(field)
        if isinstance(value, bool):
            result[field] = value
    return result
