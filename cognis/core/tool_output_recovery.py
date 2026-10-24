"""Shared rendering for validated tool-output recovery handles."""

from __future__ import annotations

from collections.abc import Sequence

COMPACT_RESULT_RENDERING_POLICY_VERSION = 2
_MAX_INLINE_ANCHORS = 5


def format_recovery_hint(
    call_id: str,
    *,
    anchor_names: Sequence[str] = (),
    anchors_available: bool = False,
    legacy: bool = False,
) -> str:
    """Render a saved handle with already normalized, controller-safe anchors."""

    quoted = repr(call_id)
    if legacy:
        # Persisted version-1 projection decisions must retain their exact bytes.
        calls = [
            f"read_tool_output(call_id={quoted})",
            f"search_tool_output(call_id={quoted}, pattern='error|timeout|keyword')",
        ]
        if anchor_names:
            calls.append(f"list_tool_output_anchors(call_id={quoted})")
            calls.append(f"read_tool_output_anchor(call_id={quoted}, anchor={anchor_names[0]!r})")
        elif anchors_available:
            calls.append(f"list_tool_output_anchors(call_id={quoted})")
        return f"Recover with call_id {quoted}: " + ", ".join(calls) + "."

    hint = f"Recover only if needed: read_tool_output(call_id={quoted})."
    if anchor_names:
        preview = ", ".join(anchor_names[:_MAX_INLINE_ANCHORS])
        remaining = len(anchor_names) - _MAX_INLINE_ANCHORS
        suffix = f", +{remaining} more" if remaining > 0 else ""
        hint += f" Anchors: {preview}{suffix}."
    elif anchors_available:
        hint += " Anchors available."
    return hint
