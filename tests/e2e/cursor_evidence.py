"""Test-only canonical cursor comparison; never a client authorization decoder."""

import base64
import json

from cognis.api.chat_v2.cursors import InternalChatCursorPayload


def cursor_position(token: str) -> dict:
    payload = token.split(".", 1)[0]
    fields = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    InternalChatCursorPayload.model_validate(fields)
    return {key: value for key, value in fields.items() if key not in ("issued_at", "expires_at")}
