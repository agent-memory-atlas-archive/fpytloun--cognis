"""Shared producer-status normalization for durable and live Chat v2 items."""

from __future__ import annotations

from typing import Any, cast

from cognis.api.chat_v2.schemas import TimelineItemStatus


def normalize_timeline_status(value: Any) -> TimelineItemStatus | None:
    """Translate producer lifecycle vocabulary into the Chat v2 contract."""
    if not isinstance(value, str):
        return None
    if value in {"pending", "running", "waiting", "complete", "failed", "cancelled", "denied"}:
        return cast(TimelineItemStatus, value)
    if value in {"started", "in_progress"}:
        return "running"
    if value in {"completed", "success", "succeeded"}:
        return "complete"
    if value == "error":
        return "failed"
    return None
