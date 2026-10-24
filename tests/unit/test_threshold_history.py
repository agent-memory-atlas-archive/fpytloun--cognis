"""Threshold projection stays enabled without transcript snapshot storage."""

from __future__ import annotations

import copy

from cognis.core.context import ContextAssembler, events_to_messages
from cognis.core.injection_replay import freeze_rendered_tools
from tests.unit.test_context_assembler import (
    _LLM,
    _Guardrails,
    _Memory,
    _SessionCache,
    _SessionManager,
)


class ExactCounter(_LLM):
    def count_tokens(self, text: str, model: str) -> int:
        return len(text)

    def count_messages_tokens(self, messages: list[dict], model: str) -> int:
        return sum(len(str(message.get("content") or "")) for message in messages)


def test_threshold_policy_survives_snapshot_removal() -> None:
    assembler = ContextAssembler(
        memory=_Memory(),
        guardrails=_Guardrails(),
        llm=ExactCounter(),
        session_cache=_SessionCache(),
        session_manager=_SessionManager(),
        compaction_threshold=0.85,
    )
    messages: list[dict] = [{"role": "user", "content": "Inspect"}]
    for index in range(4):
        messages.extend(
            [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": f"read-{index}",
                            "type": "function",
                            "function": {"name": "read", "arguments": "{}"},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": f"read-{index}",
                    "_tool_name": "read",
                    "_has_full_output": True,
                    "_recovery_call_id": f"read-{index}",
                    "content": "evidence " * 240,
                },
            ]
        )

    def project(items: list[dict]) -> list[dict]:
        result, *_ = assembler._finalize_assembled_messages(
            messages=copy.deepcopy(items),
            resolved_model="test-model",
            max_context_tokens=10_000,
            available_prompt_tokens=10_000,
            effective_input_tokens=10_000,
            max_prompt_tokens=9_800,
            tool_schema_tokens=0,
        )
        return result

    below = messages[:5]
    result = project(below)
    assert [m.get("content") for m in result] == [m.get("content") for m in below]
    assert project(messages) != messages
    assert ExactCounter().count_messages_tokens(project(messages), "test-model") <= 3_500


def test_retired_snapshots_cannot_override_canonical_events() -> None:
    events = [
        {"seq": 1, "type": "user_message", "data": {"content": "Canonical question"}},
        {
            "seq": 2,
            "type": "lifecycle",
            "data": {
                "event": "prompt_injections",
                "version": 1,
                "messages": [{"message": {"role": "system", "content": "Retired notice"}}],
            },
        },
        {
            "seq": 3,
            "type": "lifecycle",
            "data": {"event": "prompt_injections_chunk", "content": "not valid JSON"},
        },
        {"seq": 4, "type": "assistant_message", "data": {"content": "Canonical answer"}},
    ]
    assert events_to_messages(events) == events_to_messages([events[0], events[-1]])


def test_in_turn_tool_rendering_stays_frozen_without_snapshot() -> None:
    original = {
        "role": "tool",
        "tool_call_id": "read-evidence",
        "content": "Full output",
        "_token_estimate": 100,
    }
    messages = [copy.deepcopy(original)]
    freeze_rendered_tools(
        messages, [{**original, "content": "Projected output", "_tool_is_error": True}]
    )
    assert messages[0]["content"] == "Projected output"
    assert messages[0]["_tool_is_error"] is True
    assert "_token_estimate" not in messages[0]
