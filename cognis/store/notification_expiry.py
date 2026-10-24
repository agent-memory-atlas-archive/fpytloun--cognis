"""Deadline policy shared by notification lifecycle and metadata projections."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from cognis.store.models import NotificationRow


def notification_payload_expiry(
    notification_type: str, payload: dict[str, Any], *, created_at: datetime
) -> datetime | None:
    """Resolve durable payload deadlines, including bounded legacy auth waits."""
    raw = payload.get("expires_at")
    metadata = payload.get("metadata")
    if raw is None and isinstance(metadata, dict):
        raw = metadata.get("expires_at")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    if notification_type not in {"escalation", "auth_challenge"}:
        return None
    default = 180.0 if notification_type == "auth_challenge" else 300.0
    try:
        timeout = float(payload.get("timeout_seconds", default))
    except (ValueError, TypeError):
        timeout = default
    if not math.isfinite(timeout):
        timeout = default
    timeout = max(0.0, timeout)
    if notification_type == "auth_challenge":
        timeout = max(1.0, min(timeout, 600.0))
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at + timedelta(seconds=timeout)


def notification_expiry(row: NotificationRow) -> datetime | None:
    """Read explicit expiry or derive deadlines for legacy persisted rows."""
    expiry = row.expires_at
    if expiry is not None:
        return expiry if expiry.tzinfo is not None else expiry.replace(tzinfo=UTC)
    if row.notification_type not in {"escalation", "auth_challenge"}:
        return None
    created_at = row.created_at
    if created_at is None:
        return None
    return notification_payload_expiry(
        row.notification_type,
        row.payload if isinstance(row.payload, dict) else {},
        created_at=created_at,
    )


def notification_is_expired(row: NotificationRow, *, now: datetime) -> bool:
    """Apply one expiry boundary to lifecycle, sidebar and navigation reads."""
    expiry = notification_expiry(row)
    return row.status in {"pending", "resolving"} and expiry is not None and now >= expiry
