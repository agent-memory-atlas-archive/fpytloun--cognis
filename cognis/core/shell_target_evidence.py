"""Read-only, per-dispatch shell provenance; never an authorization decision."""

from __future__ import annotations

import asyncio
from typing import Any

from cognis.guardrails_redaction import redact_runtime_evidence


async def shell_target_evidence(
    executor: Any,
    *,
    shell_id: Any,
    user_id: str,
    session_id: str,
    conversation_id: str | None,
) -> dict[str, Any]:
    """Resolve a caller-owned target on the selected executor, without caching.

    Cancellation belongs to the caller. Missing registry state remains unknown,
    never permission. No execution retries, locks, persistent writes or outputs.
    """
    executor_id = getattr(executor, "executor_id", None)
    evidence: dict[str, Any] = {
        "coverage": "unknown",
        "source": "executor_shell_registry",
        "authority": "context_only",
        "user_id": user_id,
        "session_id": session_id,
        "conversation_id": conversation_id,
        "executor_id": executor_id if isinstance(executor_id, str) else None,
    }
    if not isinstance(shell_id, str) or not shell_id or len(shell_id) > 160:
        return {**evidence, "reason": "invalid_target"}
    evidence["shell_id"] = shell_id
    lookup = getattr(executor, "background_shell_status", None)
    if not user_id or not conversation_id or not isinstance(executor_id, str) or not executor_id:
        return {**evidence, "reason": "identity_unavailable"}
    if not callable(lookup):
        return {**evidence, "reason": "lookup_unavailable"}
    try:
        snapshot = await asyncio.wait_for(lookup(include_completed=True), timeout=2.0)
    except Exception:
        # Optional evidence failure cannot invent a target or grant permission.
        return {**evidence, "reason": "lookup_unavailable"}
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("shells"), list):
        return {**evidence, "reason": "invalid_snapshot"}
    matches = [
        row
        for row in snapshot["shells"]
        if isinstance(row, dict) and row.get("shell_id") == shell_id
    ]
    if len(matches) != 1:
        return {**evidence, "reason": "not_found_or_not_owned"}
    row = matches[0]
    if (
        row.get("user_email") != user_id
        or row.get("conversation_id") != conversation_id
        or row.get("executor_id") != executor_id
    ):
        return {**evidence, "reason": "not_found_or_not_owned"}
    # Session rotation within this conversation is valid. Never send output tails.
    target = {
        key: row.get(key)
        for key in (
            "command",
            "description",
            "cwd",
            "status",
            "session_id",
            "call_id",
            "agent_id",
            "admission_call_id",
            "admission_session_id",
            "execution_scope",
            "incarnation",
            "created_at",
            "done",
            "exit_code",
            "completion_reason",
        )
        if isinstance(row.get(key), (str, bool, int, float))
    }
    target = redact_runtime_evidence(target)
    missing = [key for key in ("command", "status", "session_id", "call_id") if not target.get(key)]
    truncated = []
    for key, value in target.items():
        if isinstance(value, str) and len(value) > 1200:
            target[key] = value[:1200] + "[TRUNCATED]"
            truncated.append(key)
    return {
        **evidence,
        "coverage": "partial" if truncated or missing else "complete",
        "missing_fields": missing,
        "truncated_fields": truncated,
        "target": target,
    }
