"""Controller-only process bindings, not agent-supplied evaluation context."""

from dataclasses import dataclass
from typing import Any

from cognis.core.workflow_step_scope import canonical_digest


@dataclass(frozen=True)
class ProcessEvaluationBinding:
    user_email: str
    agent_id: str
    declaration: dict[str, Any]

    @property
    def digest(self) -> str:
        return canonical_digest(self.declaration)


def build_binding(
    *,
    user_email: str,
    agent_id: str,
    session_id: str,
    conversation_id: str,
    execution_scope: str,
    logical_call_id: str,
    executor_id: str,
    tool: str,
    arguments: dict[str, Any],
    target: dict[str, Any] | None,
) -> ProcessEvaluationBinding | None:
    if not all(
        (
            user_email,
            agent_id,
            session_id,
            conversation_id,
            execution_scope,
            logical_call_id,
            executor_id,
        )
    ):
        return None
    body: dict[str, Any] = {
        "version": 1,
        "operation": "spawn",
        "session_id": session_id,
        "conversation_id": conversation_id,
        "execution_scope": execution_scope,
        "logical_call_id": logical_call_id,
        "executor_id": executor_id,
        "tool": tool,
        "evaluated_args_digest": canonical_digest(arguments),
        "spawn_call_id": None,
        "spawn_session_id": None,
        "spawn_logical_call_id": None,
        "shell_id": None,
        "incarnation": None,
    }
    if tool == "bash" and arguments.get("run_in_background") is True:
        return ProcessEvaluationBinding(user_email, agent_id, body)
    if tool != "bash_kill" or not isinstance(target, dict):
        return None
    resource = target.get("target")
    if not isinstance(resource, dict):
        return None
    if (
        target.get("source") != "executor_shell_registry"
        or target.get("coverage") != "complete"
        or target.get("user_id") != user_email
        or target.get("conversation_id") != conversation_id
        or resource.get("execution_scope") != execution_scope
        or target.get("executor_id") != executor_id
        or resource.get("agent_id") != agent_id
        or target.get("shell_id") != arguments.get("shell_id")
    ):
        return None
    fields = {
        "spawn_call_id": "admission_call_id",
        "spawn_session_id": "admission_session_id",
        "spawn_logical_call_id": "call_id",
        "incarnation": "incarnation",
    }
    for key, source in fields.items():
        value = resource.get(source)
        if not isinstance(value, str) or not value:
            return None
        body[key] = value
    body["operation"] = "terminate"
    body["shell_id"] = target["shell_id"]
    return ProcessEvaluationBinding(user_email, agent_id, body)
