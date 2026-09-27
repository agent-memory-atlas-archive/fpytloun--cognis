"""Escalation deadline precedence and validation through the owning boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from cognis.api.models import TaskCreateRequest, TaskUpdateRequest
from cognis.core.agent_loop import AgentLoop, ToolCall, ToolResult
from cognis.models.agent import AgentCapabilities
from cognis.tools.builtin.agent_management import MANAGE_AGENTS_TOOL
from cognis.tools.builtin.orchestration import CREATE_TASK_TOOL, UPDATE_TASK_TOOL


class _CapturedNotification(Exception):
    pass


def test_management_tools_expose_timeout_with_clearable_task_update() -> None:
    agent = next(
        operation
        for operation in MANAGE_AGENTS_TOOL.native_operations
        if operation.operation == "settings_update"
    ).input_schema["properties"]["settings"]["properties"]["escalation_timeout_seconds"]
    created = CREATE_TASK_TOOL.parameters["properties"]["escalation_timeout_seconds"]
    updated = UPDATE_TASK_TOOL.parameters["properties"]["escalation_timeout_seconds"]
    assert agent["maximum"] == created["maximum"] == updated["maximum"] == 86400
    assert agent["type"] == updated["type"] == ["integer", "null"]
    assert created["type"] == "integer"


@pytest.mark.parametrize("invalid", [0, -1, 86401, 1.5, "12", True])
def test_timeout_rejects_invalid_values(invalid: object) -> None:
    with pytest.raises(ValidationError):
        AgentCapabilities(escalation_timeout_seconds=invalid)
    with pytest.raises(ValidationError):
        TaskCreateRequest(agent_id="agent", title="Task", escalation_timeout_seconds=invalid)
    with pytest.raises(ValidationError):
        TaskUpdateRequest(escalation_timeout_seconds=invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task_timeout", "agent_timeout", "expected"),
    [
        (11, 22, 11),
        (None, 22, 22),
        (None, None, 300),
        (11, None, 11),
    ],
)
async def test_escalation_notification_captures_task_agent_global_precedence(
    monkeypatch: pytest.MonkeyPatch,
    task_timeout: int | None,
    agent_timeout: int | None,
    expected: int,
) -> None:
    get_task = AsyncMock(return_value=SimpleNamespace(escalation_timeout_seconds=task_timeout))
    get_global = AsyncMock(return_value=300)
    monkeypatch.setattr("cognis.store.queries.get_task", get_task)
    monkeypatch.setattr("cognis.core.agent_loop.get_setting_value", get_global)

    session = AsyncMock()
    create_notification = AsyncMock(side_effect=_CapturedNotification)
    loop = SimpleNamespace(
        session_manager=SimpleNamespace(session_factory=lambda: session),
        notification_service=SimpleNamespace(create=create_notification),
    )
    context = SimpleNamespace(
        interaction_mode="explicit_gates",
        task_id="task-1",
        agent=SimpleNamespace(
            capabilities=AgentCapabilities(escalation_timeout_seconds=agent_timeout)
        ),
        session=SimpleNamespace(session_id="session-1", user_email="owner@example.com"),
        conversation=SimpleNamespace(conversation_id="conversation-1"),
        step_run_id="step-1",
    )
    result = ToolResult(
        output="Approval required",
        is_error=True,
        metadata={"evaluation": {"decision": "escalate", "call_id": "evaluation-1"}},
    )
    with pytest.raises(_CapturedNotification):
        await AgentLoop._handle_escalation(
            loop,
            result,
            ToolCall(call_id="tool-1", name="read", arguments={}),
            context,
            [],
            None,
        )
    assert create_notification.await_args.kwargs["payload"]["timeout_seconds"] == expected
    assert get_global.await_count == int(task_timeout is None and agent_timeout is None)
    get_task.assert_awaited_once_with(session.__aenter__.return_value, "task-1")
