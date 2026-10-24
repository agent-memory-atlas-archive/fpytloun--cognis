"""Scoped keyset cursors for readable project activity."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from cognis.api.common import api_exception


def encode_project_cursor(scope: list[str | None], at: datetime, item_id: str) -> str:
    """Encode an ordering boundary, not an access grant."""
    return base64.urlsafe_b64encode(json.dumps([scope, at.isoformat(), item_id]).encode()).decode()


def decode_project_cursor(
    token: str | None, scope: list[str | None]
) -> tuple[datetime, str] | None:
    """Reject malformed or differently scoped cursors before querying."""
    if token is None:
        return None
    try:
        saved_scope, timestamp, item_id = json.loads(base64.urlsafe_b64decode(token))
        if saved_scope != scope or not isinstance(item_id, str) or not item_id:
            raise ValueError("Invalid scope or key")
        return datetime.fromisoformat(timestamp), item_id
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise api_exception(400, "invalid_cursor", "Invalid project cursor") from exc
