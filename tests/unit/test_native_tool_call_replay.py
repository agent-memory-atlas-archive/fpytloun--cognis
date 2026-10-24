"""Regular and controller calls must retain the same sanitized provider bytes."""

import json
from types import SimpleNamespace

import pytest

from cognis.core.agent_loop import (
    RESPONSES_OUTPUT_ITEMS_PERSIST_MAX_BYTES,
    _append_tool_call_event,
    _attach_responses_output_items,
    _attach_responses_output_items_to_first_tool_call,
    _PreparedRegularToolCall,
    _regular_tool_call_event_data,
    _responses_output_items_for_persistence,
)
from cognis.core.context import events_to_messages
from cognis.models.tool import ToolCall
from cognis.providers.llm.responses_bridge import messages_to_responses_input


@pytest.mark.parametrize("regular", [False, True])
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize(
    "arguments",
    [
        '{"path":"/home/alice/src/sample","ignore":[]}',
        '{ "path" : "/home/alice/Žluťoučký", "ignore" : [] }',
    ],
    ids=["compact", "unicode-spaces"],
)
def test_tool_call_recording_cold_wire_identity(regular, native, arguments):
    tc = ToolCall(
        call_id="call_replay",
        name="list_directory",
        arguments=json.loads(arguments),
        runtime_metadata={"provider_arguments_json": arguments},
    )
    if native:
        _attach_responses_output_items_to_first_tool_call(
            [tc],
            [
                {
                    "type": "function_call",
                    "call_id": tc.call_id,
                    "name": tc.name,
                    "arguments": arguments,
                }
            ],
        )
    if regular:
        data = _regular_tool_call_event_data(
            SimpleNamespace(tool_registry=None, current_turn_cycle_index=0),
            _PreparedRegularToolCall(tool_call=tc, tool_id="list_directory"),
        )
    else:
        events = []
        _append_tool_call_event(events, tc)
        data = events[0].data
    messages = events_to_messages([{"seq": 1, "type": "tool_call", "data": data}])
    wire = messages_to_responses_input(messages)
    call = next(item for item in wire if item.get("type") == "function_call")
    assert call["arguments"] == arguments
    assert call["name"] == tc.name


def test_regular_parallel_batch_retains_native_items_once():
    calls = [
        ToolCall(call_id=f"call_parallel_{i}", name="list_directory", arguments={"path": "/"})
        for i in range(2)
    ]
    items = [{"type": "reasoning", "id": "reasoning_parallel", "encrypted_content": "signed"}]
    items += [
        {
            "type": "function_call",
            "call_id": tc.call_id,
            "name": tc.name,
            "arguments": '{ "path" : "/" }',
        }
        for tc in calls
    ]
    _attach_responses_output_items_to_first_tool_call(calls, items)
    ctx = SimpleNamespace(tool_registry=None, current_turn_cycle_index=0)
    events = [
        {
            "seq": i + 1,
            "type": "tool_call",
            "data": _regular_tool_call_event_data(
                ctx, _PreparedRegularToolCall(tool_call=tc, tool_id=tc.name)
            ),
        }
        for i, tc in enumerate(calls)
    ]
    wire = messages_to_responses_input(events_to_messages(events))
    assert sum(item.get("type") == "reasoning" for item in wire) == 1
    assert [item["arguments"] for item in wire if item.get("type") == "function_call"] == [
        '{ "path" : "/" }',
        '{ "path" : "/" }',
    ]


def test_native_arguments_still_redact_protected_control_content():
    arguments = {"agent_id": "laforge", "initial_message": "x" * 10000 + "PRIVATE_TAIL"}
    items = _responses_output_items_for_persistence(
        [
            {
                "type": "function_call",
                "call_id": "call_agent_update",
                "name": "agent_conversation_create",
                "arguments": json.dumps(arguments),
            }
        ]
    )
    assert "PRIVATE_TAIL" not in json.dumps(items)


def test_regular_call_native_cap_keeps_safe_argument_fallback():
    arguments = '{ "path" : "/" }'
    tc = ToolCall(
        call_id="call_cap",
        name="list_directory",
        arguments={"path": "/"},
        runtime_metadata={"provider_arguments_json": arguments},
    )
    _attach_responses_output_items_to_first_tool_call(
        [tc],
        [
            {
                "type": "reasoning",
                "encrypted_content": "x" * (RESPONSES_OUTPUT_ITEMS_PERSIST_MAX_BYTES + 1),
            }
        ],
    )
    data = _regular_tool_call_event_data(
        SimpleNamespace(tool_registry=None, current_turn_cycle_index=0),
        _PreparedRegularToolCall(tool_call=tc, tool_id=tc.name),
    )
    assert data["provider_arguments_json"] == arguments
    assert "responses_output_items" not in data
    assert "native_batch_replay_version" not in data


@pytest.mark.parametrize("regular", [False, True])
@pytest.mark.parametrize("with_content", [False, True])
def test_recorded_native_response_opts_into_interleaved_batch_replay(regular, with_content):
    calls = [
        ToolCall(
            call_id=call_id,
            name="list_directory",
            arguments=json.loads(raw),
            runtime_metadata={"provider_arguments_json": raw},
        )
        for call_id, raw in [
            ("call_first", '{ "path": "/" }'),
            ("call_second", '{"path":"/tmp"}'),
        ]
    ]
    items = [
        {
            "type": "function_call",
            "id": f"fc_{tc.call_id}",
            "call_id": tc.call_id,
            "name": tc.name,
            "arguments": tc.runtime_metadata["provider_arguments_json"],
        }
        for tc in calls
    ]
    events = []
    if with_content:
        data = {"content": "Checking both directories."}
        _attach_responses_output_items(data, items, durable=True)
        events.append({"type": "assistant_message", "data": data})
    else:
        _attach_responses_output_items_to_first_tool_call(calls, items)
    for tc in calls:
        if regular:
            data = _regular_tool_call_event_data(
                SimpleNamespace(tool_registry=None, current_turn_cycle_index=0),
                _PreparedRegularToolCall(tool_call=tc, tool_id=tc.name),
            )
        else:
            recorded = []
            _append_tool_call_event(recorded, tc)
            data = recorded[0].data
        events.extend(
            [
                {"type": "tool_call", "data": data},
                {"type": "tool_result", "data": {"call_id": tc.call_id, "result": "done"}},
            ]
        )
    assert events[0]["data"]["native_batch_replay_version"] == 1
    assert "native_batch_replay_version" not in events[-2]["data"]
    messages = events_to_messages(events)
    assert len([m for m in messages if m.get("tool_calls")]) == 1
    assert [
        item
        for item in messages_to_responses_input(messages)
        if item.get("type") == "function_call"
    ] == items


@pytest.mark.parametrize("regular", [False, True])
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("padding", [" " * 300_000, "\n" * 150_000])
def test_raw_argument_fallback_is_bounded_by_encoded_json_bytes(regular, native, padding):
    arguments = padding + "{}"
    tc = ToolCall(
        call_id="call_padded",
        name="list_directory",
        arguments={},
        runtime_metadata={"provider_arguments_json": arguments},
    )
    if native:
        _attach_responses_output_items_to_first_tool_call(
            [tc],
            [
                {
                    "type": "function_call",
                    "call_id": tc.call_id,
                    "name": tc.name,
                    "arguments": arguments,
                }
            ],
        )
    if regular:
        data = _regular_tool_call_event_data(
            SimpleNamespace(tool_registry=None, current_turn_cycle_index=0),
            _PreparedRegularToolCall(tool_call=tc, tool_id=tc.name),
        )
    else:
        events = []
        _append_tool_call_event(events, tc)
        data = events[0].data
    assert "provider_arguments_json" not in data
    assert len(json.dumps(data).encode()) < RESPONSES_OUTPUT_ITEMS_PERSIST_MAX_BYTES


@pytest.mark.parametrize("case", ["signed", "oversized", "malformed", "non_continuable"])
@pytest.mark.parametrize("parallel", [False, True])
def test_regular_call_signed_anthropic_envelope_is_exact_or_non_continuable(case, parallel):
    from cognis.providers.llm.anthropic.contracts import AnthropicNativeEnvelope

    original = AnthropicNativeEnvelope(
        native_blocks=(
            {"type": "thinking", "thinking": "reasoning", "signature": "signed-prefix"},
            {
                "type": "tool_use",
                "id": "call_anthropic",
                "name": "list_directory",
                "input": {"path": "/"},
            },
        ),
        stop_reason="tool_use",
        stop_details={},
        usage={},
        pending_client_message_id=None,
        pending_server_message_id=None,
        bundle_fingerprint="bundle",
        provider_fingerprint="provider",
        model_fingerprint="model",
        thinking_fingerprint="thinking",
    ).to_dict()
    if parallel:
        original["native_blocks"].append(
            {
                "type": "tool_use",
                "id": "call_anthropic_second",
                "name": "list_directory",
                "input": {"path": "/"},
            }
        )
    if case == "oversized":
        original["native_blocks"][0]["thinking"] = "x" * 300_000
    elif case == "malformed":
        original["native_blocks"][0]["unsupported_field"] = True
    elif case == "non_continuable":
        original = {"contract_version": 1, "continuation_status": "non_continuable"}
    tc = ToolCall(
        call_id="call_anthropic",
        name="list_directory",
        arguments={"path": "/"},
        runtime_metadata={"anthropic_native_envelope": original},
    )
    data = _regular_tool_call_event_data(
        SimpleNamespace(tool_registry=None, current_turn_cycle_index=0),
        _PreparedRegularToolCall(tool_call=tc, tool_id=tc.name),
    )
    durable = data["anthropic_native_envelope"]
    if case == "signed":
        assert durable == original
        events = [{"seq": 1, "type": "tool_call", "data": data}]
        ids = [tc.call_id]
        if parallel:
            second = tc.model_copy(
                update={"call_id": "call_anthropic_second", "runtime_metadata": {}}
            )
            second_data = _regular_tool_call_event_data(
                SimpleNamespace(tool_registry=None, current_turn_cycle_index=0),
                _PreparedRegularToolCall(tool_call=second, tool_id=second.name),
            )
            assert "anthropic_native_envelope" not in second_data
            events.append({"seq": 2, "type": "tool_call", "data": second_data})
            ids.append(second.call_id)
        for cid in ids:
            events.append(
                {
                    "seq": len(events) + 1,
                    "type": "tool_result",
                    "data": {
                        "call_id": cid,
                        "name": tc.name,
                        "result": "completed",
                    },
                }
            )
        messages = events_to_messages(events)
        assert sum("_anthropic_native_envelope" in m for m in messages) == 1
        assert (
            next(
                m["_anthropic_native_envelope"]
                for m in messages
                if "_anthropic_native_envelope" in m
            )
            == original
        )
    else:
        assert durable == {"contract_version": 1, "continuation_status": "non_continuable"}
