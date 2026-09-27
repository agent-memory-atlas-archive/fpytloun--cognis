"""An unattended step cannot wait for an Intaris escalation."""

from types import SimpleNamespace

import pytest

from cognis.core.agent_loop import AgentLoop, ToolCall, ToolResult


@pytest.mark.asyncio
async def test_unattended_escalation_fails_closed_before_notification() -> None:
    result = ToolResult(
        output="Approval required",
        is_error=True,
        metadata={"evaluation": {"decision": "escalate", "call_id": "call-123"}},
    )
    blocked = await AgentLoop._handle_escalation(
        SimpleNamespace(),
        result,
        ToolCall(call_id="tool-123", name="bash", arguments={}),
        SimpleNamespace(interaction_mode="none"),
        [],
        None,
    )
    assert blocked.is_error
    assert blocked.metadata["evaluation"]["decision"] == "deny"
    assert blocked.metadata["evaluation"]["escalation_suppressed"] is True
    assert "disabled" in blocked.output
