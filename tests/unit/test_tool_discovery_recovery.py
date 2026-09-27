"""Regression coverage for browser discovery and malformed call envelopes."""

from __future__ import annotations

import pytest

from cognis.core.agent_loop import AgentLoop, _resolve_call_tool_envelope
from cognis.models.tool import ToolCall, stable_tool_id, tool_input_schema
from cognis.tools.builtin.tool_search import CALL_TOOL_TOOL, SEARCH_TOOLS_TOOL, search_inventory
from cognis.tools.executor.browser.definitions import browser_tool_definitions
from cognis.tools.introspection import describe_available_tool


@pytest.mark.parametrize("operation", ["open", "navigate", "browser_open"])
def test_browser_description_recovers_single_operation(operation: str) -> None:
    tools = browser_tool_definitions()
    match = search_inventory(tools, "browser_open", limit=1)[0]
    described = describe_available_tool(tools, match["tool_id"], operation)
    assert described["valid"] is True
    assert described["descriptor"]["operation"]["operation"] == "browser_open"
    assert "url" in described["descriptor"]["operation"]["input_schema"]["properties"]
    if operation != "browser_open":
        assert described["requested_operation"] == operation
        assert described["resolved_operation"] == "browser_open"
    else:
        assert "resolved_operation" not in described


def test_single_operation_recovery_cannot_reveal_unavailable_tool() -> None:
    assert describe_available_tool([], "builtin:browser_open", "open")["error"] == (
        "tool_not_available"
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"headless": False, "profile_mode": "persistent_local"},
        {"tool": "builtin:browser_open"},
        {"tool": "builtin:browser_open", "arguments": "{}"},
        {"tool": "builtin:browser_open", "arguments": {}, "headless": False},
    ],
)
def test_malformed_envelope_is_rejected_before_resolution(arguments: dict) -> None:
    loop = object.__new__(AgentLoop)
    assert loop._get_controller_tool_parameters("call_tool") == tool_input_schema(CALL_TOOL_TOOL)
    call = ToolCall(call_id="call-envelope", name="call_tool", arguments=arguments)
    assert _resolve_call_tool_envelope(call, browser_tool_definitions()) is None
    error = loop._validate_controller_tool_arguments("call_tool", arguments)
    assert error is not None
    assert error.as_tool_result()["error"] == "invalid_tool_arguments"
    assert "envelope" in error.message
    assert "describe_tool" in error.message
    assert call.arguments == arguments


def test_corrected_envelope_resolves_without_changing_identity_or_arguments() -> None:
    tools = browser_tool_definitions()
    target = next(tool for tool in tools if tool.name == "browser_list_sessions")
    envelope = {"tool": stable_tool_id(target), "arguments": {}}
    call = ToolCall(call_id="call-corrected", name="call_tool", arguments=envelope)
    loop = object.__new__(AgentLoop)
    assert loop._validate_controller_tool_arguments("call_tool", envelope) is None
    assert _resolve_call_tool_envelope(call, tools) == (target, {})
    assert call.name == "call_tool"
    assert call.arguments == envelope
    assert _resolve_call_tool_envelope(call, []) is None


@pytest.mark.parametrize("target", [CALL_TOOL_TOOL, SEARCH_TOOLS_TOOL])
def test_envelope_cannot_recurse_into_discovery_protocol(target) -> None:
    call = ToolCall(
        call_id="call-recursion",
        name="call_tool",
        arguments={"tool": stable_tool_id(target), "arguments": {}},
    )
    assert _resolve_call_tool_envelope(call, [target]) is None
