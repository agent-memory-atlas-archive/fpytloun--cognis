"""In-memory tool rendering stability; no persisted transcript snapshots."""

from __future__ import annotations

import copy
from typing import Any

PROVIDER_REPLAY_FIELDS = frozenset(
    {
        "_audit_source",
        "_audit_role",
        "_tool_is_error",
        "_responses_output_items",
        "_anthropic_native_envelope",
        "_anthropic_thinking_blocks",
    }
)


def _tool_identity(message: dict[str, Any]) -> tuple[str, ...]:
    if message.get("role") == "tool":
        return ("tool", str(message.get("tool_call_id")))
    return ("assistant", *(str(call["id"]) for call in message.get("tool_calls", [])))


def freeze_rendered_tools(messages: list[dict[str, Any]], rendered: list[dict[str, Any]]) -> None:
    """Preserve accepted tool bytes within the live turn without event writes."""
    by_identity = {
        _tool_identity(message): message
        for message in rendered
        if message.get("role") == "tool" or message.get("tool_calls")
    }
    for index, message in enumerate(messages):
        if message.get("role") != "tool" and not message.get("tool_calls"):
            continue
        replacement = by_identity.get(_tool_identity(message))
        if replacement is None:
            continue
        updated = {**message, **copy.deepcopy(replacement)}
        for key in (
            "_responses_output_items",
            "_anthropic_native_envelope",
            "_anthropic_thinking_blocks",
        ):
            if key not in replacement:
                updated.pop(key, None)
        if updated.get("content") != message.get("content"):
            updated.pop("_token_estimate", None)
        messages[index] = updated
