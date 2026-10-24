"""Bounded projections of controller-owned runtime evidence; no additional cache."""

from __future__ import annotations

import json
from typing import Any

from cognis.guardrails_redaction import redact_runtime_evidence
from cognis.models.tool import ToolDefinition, ToolResult
from cognis.tools.introspection import selected_native_operation


def operation_context(tool: ToolDefinition, arguments: dict[str, Any]) -> dict[str, Any]:
    """Project the selected descriptor without copying schemas into evaluations."""
    descriptor = tool.descriptor
    if descriptor is None:
        return {"annotations": tool.annotations} if tool.annotations is not None else {}
    selected = selected_native_operation(tool, arguments)
    selector: dict[str, Any] = {}
    if selected is not None:
        properties = selected.input_schema.get("properties", {})
        selector = {
            key: value["const"]
            for key, value in properties.items()
            if isinstance(value, dict) and "const" in value
        }
        if any(arguments.get(key) != value for key, value in selector.items()):
            selected = None
    return {
        "annotations": descriptor.annotations or tool.annotations,
        "descriptor": {
            "authority": descriptor.authority,
            "schema_version": descriptor.schema_version,
            "schema_hash": descriptor.schema_hash,
            "selection": "exact" if selected is not None else "unknown",
            "selector": selector,
            "operation": (
                {
                    "name": selected.operation,
                    "summary": selected.summary,
                    "mutation_kind": str(selected.mutation_kind),
                    "side_effects": selected.side_effects,
                }
                if selected is not None
                else None
            ),
        },
    }


def loaded_skills_context(snapshots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Read only loaded snapshots, preserving missing and omitted evidence explicitly."""
    rows: list[dict[str, Any]] = []
    omitted = 0
    for skill_id, snapshot in sorted(snapshots.items()):
        description = str(redact_runtime_evidence(snapshot.get("description") or ""))
        row = {
            "id": skill_id,
            "name": snapshot.get("name"),
            "version_id": snapshot.get("version_id"),
            "version_number": snapshot.get("version_number"),
            "content_hash": snapshot.get("content_hash"),
            "summary": description[:240],
            "summary_truncated": len(description) > 240,
            "summary_missing": not bool(description),
        }
        if len(json.dumps([*rows, row], ensure_ascii=False).encode()) > 1800:
            omitted += 1
        else:
            rows.append(row)
    return {"skills": rows, "omitted": omitted, "authority": "context_only"}


def execution_outcome(
    result: ToolResult, *, executor_id: str | None, native_shell: bool = False
) -> dict[str, Any]:
    """Record delivery/outcome fields, never parse output for execution identity."""
    metadata = redact_runtime_evidence(result.metadata or {})
    evaluation = metadata.get("evaluation") or {}
    status = "error" if result.is_error else "completed"
    if metadata.get("uncertain") or metadata.get("delivery_state") == "accepted_unknown":
        status = "unknown"
    elif (
        evaluation.get("decision") in {"deny", "escalate"}
        or metadata.get("delivery_state") == "not_sent"
    ):
        status = "not_executed"
    row: dict[str, Any] = {"status": status, "is_error": result.is_error}
    if executor_id:
        row["executor_id"] = executor_id
    for key in ("shell_id", "status", "exit_code", "code") if native_shell else ("code",):
        value = metadata.get(key)
        if isinstance(value, (str, int, bool)):
            row["execution_status" if key == "status" else key] = (
                value[:160] if isinstance(value, str) else value
            )
            if isinstance(value, str) and len(value) > 160:
                row[f"{key}_truncated"] = True
                if key == "shell_id":
                    row[key] = None  # An incomplete identity cannot witness ownership.
    return row


def recent_outcomes(events: list[Any], *, user_id: str, session_id: str) -> dict[str, Any]:
    """Join canonical calls/results in one session; pending events share this owner."""
    calls: dict[str, dict[str, Any]] = {}
    rows: dict[str, dict[str, Any]] = {}
    for event in events:
        data = event.data
        call_id = data.get("call_id")
        if not isinstance(call_id, str):
            continue
        if event.type == "tool_call":
            calls[call_id] = data
        elif event.type == "tool_result" and call_id in calls:
            call = calls[call_id]
            outcome = data.get("execution_outcome")
            arguments = redact_runtime_evidence(call.get("arguments", call.get("args", {})))
            target = (
                {
                    key: value[:220] if isinstance(value, str) else value
                    for key, value in arguments.items()
                    if key in {"command", "path", "file_path", "shell_id", "target_executor"}
                    and isinstance(value, (str, int, bool))
                }
                if isinstance(arguments, dict)
                else {}
            )
            rows[call_id] = {
                "call_id": call_id,
                "tool": call.get("name"),
                "target": target,
                "target_truncated": any(
                    isinstance(v, str) and len(v) > 220 for v in arguments.values()
                )
                if isinstance(arguments, dict)
                else True,
                "outcome": outcome if isinstance(outcome, dict) else {"status": "unknown"},
            }
    return {
        "user_id": user_id,
        "session_id": session_id,
        "actions": list(rows.values())[-12:],
        "omitted": max(0, len(rows) - 12),
        "source": "controller_events",
    }
