"""Presentation timestamps for events copied into a new durable stream."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

HISTORY_SOURCE_TIMESTAMP = "history_source_timestamp"


def history_event_timestamp(
    data: Mapping[str, Any], recorded_at: str | datetime | None
) -> str | None:
    """Keep copied history's original time without altering the audit envelope."""
    original = data.get(HISTORY_SOURCE_TIMESTAMP)
    if isinstance(original, str):
        try:
            parsed = datetime.fromisoformat(original.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            if parsed.tzinfo is not None:
                return original
    return recorded_at.isoformat() if isinstance(recorded_at, datetime) else recorded_at
