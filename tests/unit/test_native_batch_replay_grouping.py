"""Cold replay must regroup one native provider response like the live tool loop."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from cognis.core.context import events_to_messages
from cognis.core.context_projection import projection_decisions_from_diff
from cognis.providers.llm.responses_bridge import messages_to_responses_input

CALLS = [
    ("call_search", "search_tools", {"query": "calendar"}),
    ("call_bash", "bash", {"command": "ls", "timeout": 5}),
    ("call_read", "read", {"file_path": "/x"}),
]
NATIVE_ITEMS = [
    {"type": "reasoning", "id": "rs_1", "encrypted_content": "signed", "summary": []},
    *(
        {
            "type": "function_call",
            "id": f"fc_{call_id}",
            "call_id": call_id,
            "name": name,
            "arguments": json.dumps(arguments, separators=(",", ":")),
        }
        for call_id, name, arguments in CALLS
    ),
]


def _recorded_events(*, with_content: bool, batch_replay: bool = True) -> list[dict]:
    """Events in sequential-execution order: each call is followed by its result."""

    events: list[dict] = [{"type": "user_message", "data": {"content": "go"}}]
    if with_content:
        events.append(
            {
                "type": "assistant_message",
                "data": {
                    "content": "Checking.",
                    "responses_output_items": NATIVE_ITEMS,
                    **({"native_batch_replay_version": 1} if batch_replay else {}),
                },
            }
        )
    for index, (call_id, name, arguments) in enumerate(CALLS):
        data = {"call_id": call_id, "name": name, "arguments": arguments, "turn_id": "turn_1"}
        if index == 0 and batch_replay and not with_content:
            data["native_batch_replay_version"] = 1
        if index == 0 and not with_content:
            data["responses_output_items"] = NATIVE_ITEMS
        elif index > 0:
            # A spaced chat-shaped copy must not replace native provider bytes.
            data["provider_arguments_json"] = json.dumps(arguments)
        events.append({"type": "tool_call", "data": data})
        events.append({"type": "evaluation", "data": {"call_id": "audit", "decision": "approve"}})
        events.append(
            {"type": "tool_result", "data": {"call_id": call_id, "name": name, "result": name}}
        )
    return [dict(event, seq=seq) for seq, event in enumerate(events, start=1)]


def _live_messages(*, with_content: bool) -> list[dict]:
    """The live loop's shape: one assistant message per response, then results."""

    return [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "Checking." if with_content else None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
                for call_id, name, arguments in CALLS
            ],
            "_responses_output_items": deepcopy(NATIVE_ITEMS),
        },
        *(
            {"role": "tool", "tool_call_id": call_id, "content": name}
            for call_id, name, _arguments in CALLS
        ),
    ]


@pytest.mark.parametrize("with_content", [False, True])
def test_interleaved_native_batch_replays_like_the_live_request(with_content: bool) -> None:
    events = _recorded_events(with_content=with_content)
    original = deepcopy(events)

    messages = events_to_messages(events)

    assistants = [message for message in messages if message.get("role") == "assistant"]
    assert len(assistants) == 1
    assert [call["id"] for call in assistants[0]["tool_calls"]] == [c[0] for c in CALLS]
    assert messages_to_responses_input(messages) == messages_to_responses_input(
        _live_messages(with_content=with_content)
    )
    assert events == original


def _split_replay() -> list[dict]:
    """The pre-regrouping replay shape: one assistant message per recorded call."""

    return [
        {"role": "user", "content": "go"},
        *(
            message
            for call_id, name, arguments in CALLS
            for message in (
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": call_id, "content": name},
            )
        ),
    ]


@pytest.mark.parametrize("omitted", ["call_search", "call_bash", "call_read"])
def test_existing_group_omission_keeps_its_original_replay_scope(omitted: str) -> None:
    split = _split_replay()
    projected = [
        message
        for message in split
        if message.get("tool_call_id") != omitted
        and omitted not in {call["id"] for call in message.get("tool_calls", [])}
    ]
    decisions = projection_decisions_from_diff(split, projected)
    assert [d["operation"] for d in decisions[omitted]] == ["omit_tool_group"]

    replayed = events_to_messages(
        _recorded_events(with_content=False, batch_replay=False), projection_decisions=decisions
    )

    retained = {call_id for call_id, _name, _arguments in CALLS} - {omitted}
    assert {
        call["id"] for message in replayed for call in message.get("tool_calls", [])
    } == retained
    assert {m["tool_call_id"] for m in replayed if m.get("role") == "tool"} == retained


def test_new_whole_batch_omission_replays_without_resurrecting_siblings() -> None:
    live = _live_messages(with_content=False)
    decisions = projection_decisions_from_diff(live, live[:1])
    replayed = events_to_messages(
        _recorded_events(with_content=False), projection_decisions=decisions
    )
    assert messages_to_responses_input(replayed) == messages_to_responses_input(live[:1])


def test_unmarked_native_history_keeps_its_original_split_shape() -> None:
    messages = events_to_messages(_recorded_events(with_content=False, batch_replay=False))
    assert len([m for m in messages if m.get("tool_calls")]) == 3


@pytest.mark.parametrize(
    "separator",
    [
        {"type": "user_message", "data": {"content": "interjection"}},
        {"type": "assistant_message", "data": {"content": "separate response"}},
    ],
)
def test_unrelated_history_between_calls_keeps_separate_messages(separator: dict) -> None:
    events = _recorded_events(with_content=False)
    second_call = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "tool_call" and event["data"]["call_id"] == "call_bash"
    )
    events.insert(second_call, dict(separator, seq=999))

    messages = events_to_messages(events)

    owners = [
        [call["id"] for call in message["tool_calls"]]
        for message in messages
        if message.get("role") == "assistant" and message.get("tool_calls")
    ]
    assert owners[0] == ["call_search"]
    assert ["call_bash", "call_read"] in owners or ["call_bash"] in owners


def test_calls_outside_the_native_response_are_not_regrouped() -> None:
    events = _recorded_events(with_content=False)
    events.append(
        {
            "seq": 100,
            "type": "tool_call",
            "data": {"call_id": "call_next", "name": "bash", "arguments": {"command": "pwd"}},
        }
    )
    events.append(
        {"seq": 101, "type": "tool_result", "data": {"call_id": "call_next", "result": "/"}}
    )

    messages = events_to_messages(events)

    assistants = [message for message in messages if message.get("role") == "assistant"]
    assert [[call["id"] for call in message["tool_calls"]] for message in assistants] == [
        [c[0] for c in CALLS],
        ["call_next"],
    ]


def test_interleaved_anthropic_native_batch_keeps_one_assistant_turn() -> None:
    from cognis.providers.llm.anthropic.integration import _convert_messages

    envelope = {
        "contract_version": 1,
        "native_blocks": [
            {"type": "thinking", "thinking": "reason", "signature": "signed"},
            {"type": "tool_use", "id": "tool_1", "name": "read", "input": {"path": "x"}},
            {"type": "tool_use", "id": "tool_2", "name": "glob", "input": {"pattern": "*"}},
        ],
        "stop_reason": "tool_use",
        "stop_details": {"stop_sequence": None},
        "usage": {"input_tokens": 1, "output_tokens": 2},
        "pending_client_message_id": None,
        "pending_server_message_id": "msg_1",
        "bundle_fingerprint": "bundle",
        "provider_fingerprint": "provider",
        "model_fingerprint": "model",
        "thinking_fingerprint": "thinking",
        "continuation_status": "continuable",
    }
    events = [
        {"type": "user_message", "data": {"content": "go"}},
        {
            "type": "tool_call",
            "data": {
                "call_id": "tool_1",
                "name": "read",
                "arguments": {"path": "x"},
                "anthropic_native_envelope": envelope,
                "native_batch_replay_version": 1,
            },
        },
        {"type": "tool_result", "data": {"call_id": "tool_1", "result": "one"}},
        {"type": "tool_call", "data": {"call_id": "tool_2", "name": "glob", "arguments": {}}},
        {"type": "tool_result", "data": {"call_id": "tool_2", "result": "two"}},
    ]

    consecutive = [events[0], events[1], events[3], events[2], events[4]]

    messages = events_to_messages(events)

    assert [message["role"] for message in messages] == ["user", "assistant", "tool", "tool"]
    assert messages[1]["_anthropic_native_envelope"] == envelope
    assert messages == events_to_messages(consecutive)
    assert _convert_messages(messages) == _convert_messages(events_to_messages(consecutive))
