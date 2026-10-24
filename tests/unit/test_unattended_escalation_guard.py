"""An unattended step or agent cannot wait for an Intaris escalation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cognis.core.agent_loop import AgentLoop, ToolCall, ToolResult
from cognis.models.agent import AgentCapabilities


class _CapturedNotification(Exception):
    pass


def _escalation() -> ToolResult:
    return ToolResult(
        output="Approval required",
        is_error=True,
        metadata={"evaluation": {"decision": "escalate", "call_id": "call-123"}},
    )


def _context(
    *, interaction_mode: str, approval_mode: str = "ask", task_id: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        interaction_mode=interaction_mode,
        task_id=task_id,
        agent=SimpleNamespace(capabilities=AgentCapabilities(approval_mode=approval_mode)),
        session=SimpleNamespace(session_id="session-1", user_email="owner@example.com"),
        conversation=SimpleNamespace(conversation_id="conversation-1"),
        step_run_id=None,
    )


def _loop(monkeypatch: pytest.MonkeyPatch, *, task_override: str | None = None) -> SimpleNamespace:
    monkeypatch.setattr(
        "cognis.store.queries.get_task",
        AsyncMock(
            return_value=SimpleNamespace(
                interaction_mode_override=task_override, escalation_timeout_seconds=None
            )
        ),
    )
    monkeypatch.setattr("cognis.core.agent_loop.get_setting_value", AsyncMock(return_value=300))
    return SimpleNamespace(
        session_manager=SimpleNamespace(session_factory=lambda: AsyncMock()),
        notification_service=SimpleNamespace(create=AsyncMock(side_effect=_CapturedNotification)),
    )


def _assert_denied(blocked: ToolResult) -> None:
    assert blocked.is_error
    assert blocked.metadata["evaluation"]["decision"] == "deny"
    assert blocked.metadata["evaluation"]["escalation_suppressed"] is True
    assert "can't ask for approval" in blocked.output


@pytest.mark.asyncio
async def test_unattended_escalation_fails_closed_before_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _loop(monkeypatch)
    blocked = await AgentLoop._handle_escalation(
        loop,
        _escalation(),
        ToolCall(call_id="tool-123", name="bash", arguments={}),
        _context(interaction_mode="none"),
        [],
        None,
    )
    _assert_denied(blocked)
    loop.notification_service.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_unattended_denial_preserves_intaris_reason_without_internal_labels(monkeypatch):
    loop = _loop(monkeypatch)
    result = _escalation()
    reason = "This command targets a recipient outside the current task."
    result.metadata["evaluation"].update(
        reasoning=reason,
        source="hybrid_v1",
        path="judge.confirmation",
    )
    blocked = await AgentLoop._handle_escalation(
        loop,
        result,
        ToolCall(call_id="tool-123", name="bash", arguments={}),
        _context(interaction_mode="none"),
        [],
        None,
    )
    assert blocked.output == (
        "Tool denied: this unattended session can't ask for approval, "
        f"and Intaris flagged it: {reason}"
    )
    assert "hybrid_v1" not in blocked.output
    assert "judge.confirmation" not in blocked.output
    loop.notification_service.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("task_id", [None, "task-1"])
async def test_unattended_agent_escalation_is_denied_without_approval_card(
    monkeypatch: pytest.MonkeyPatch, task_id: str | None
) -> None:
    loop = _loop(monkeypatch, task_override=None)
    blocked = await AgentLoop._handle_escalation(
        loop,
        _escalation(),
        ToolCall(call_id="tool-123", name="bash", arguments={}),
        _context(interaction_mode="explicit_gates", approval_mode="unattended", task_id=task_id),
        [],
        None,
    )
    _assert_denied(blocked)
    loop.notification_service.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_ask_agent_still_creates_approval_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _loop(monkeypatch)
    with pytest.raises(_CapturedNotification):
        await AgentLoop._handle_escalation(
            loop,
            _escalation(),
            ToolCall(call_id="tool-123", name="bash", arguments={}),
            _context(interaction_mode="explicit_gates"),
            [],
            None,
        )
    loop.notification_service.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_task_interaction_mode_overrides_unattended_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _loop(monkeypatch, task_override="explicit_gates")
    with pytest.raises(_CapturedNotification):
        await AgentLoop._handle_escalation(
            loop,
            _escalation(),
            ToolCall(call_id="tool-123", name="bash", arguments={}),
            _context(
                interaction_mode="explicit_gates", approval_mode="unattended", task_id="task-1"
            ),
            [],
            None,
        )
    loop.notification_service.create.assert_awaited_once()
