from copy import deepcopy
from types import SimpleNamespace

import pytest

from cognis.core.inference_preparation import prepare_native_account_replay
from cognis.models.config import ModelInfo
from cognis.providers.llm.anthropic.contracts import AnthropicNativeEnvelope
from cognis.providers.llm.anthropic.integration import (
    NATIVE_CONTINUATION_REQUIRED_KWARG,
    NATIVE_REQUEST_CONTEXT_KWARG,
    NATIVE_TOOL_BUNDLE_KWARG,
    build_native_chain,
    build_native_request,
)
from cognis.providers.llm.recovery import IncompatibleCandidate


def provider(name):
    return SimpleNamespace(
        provider_id=name,
        location="controller",
        config={"preset": "anthropic", "auth_config": {"mode": "oauth"}},
    )


def chain(name, *, model="claude-opus-4-6", thinking=None, ttl="5m"):
    info = ModelInfo(model_id=model, supports_tools=True, supports_extended_thinking=True)
    context, bundle = build_native_chain(
        provider=provider(name),
        model=model,
        model_info=info,
        exposed_tools=[
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "Read",
                    "parameters": {"type": "object", "properties": {}},
                    "cache_control": {"type": "ephemeral", "ttl": ttl},
                },
            }
        ],
        alias_map={"read": "read"},
        stable_id_map={"read": "builtin:read"},
        argument_alias_map={},
        thinking=thinking,
        credential_ref="$credential:anthropic-oauth",
    )
    return {
        NATIVE_REQUEST_CONTEXT_KWARG: context.to_dict(),
        NATIVE_TOOL_BUNDLE_KWARG: bundle.to_dict(),
    }, info


def test_destination_ttl_change_preserves_signed_active_history():
    source, _ = chain("primary", ttl="1h")
    target, info = chain("backup", ttl="5m")
    messages = history(source)
    original = deepcopy(messages)
    replay = prepare_native_account_replay(messages, source, target, continuation_required=True)
    assert messages == original
    envelope = replay[1]["_anthropic_native_envelope"]
    assert envelope["native_blocks"] == original[1]["_anthropic_native_envelope"]["native_blocks"]
    assert envelope["bundle_fingerprint"] == target[NATIVE_TOOL_BUNDLE_KWARG]["fingerprint"]
    _, _, compiled = build_native_request(
        provider=provider("backup"),
        model=info.model_id,
        model_info=info,
        messages=replay,
        request_kwargs={
            **target,
            NATIVE_CONTINUATION_REQUIRED_KWARG: True,
            "tools": [{"type": "function", "function": {"name": "read"}}],
        },
        credential_ref="$credential:anthropic-oauth",
    )
    assert compiled.wire_tools[0]["cache_control"]["ttl"] == "5m"


def history(source):
    context = source[NATIVE_REQUEST_CONTEXT_KWARG]
    envelope = AnthropicNativeEnvelope(
        native_blocks=(
            {
                "type": "thinking",
                "thinking": "Preserve signed content",
                "signature": "signed-content",
            },
            {"type": "tool_use", "id": "tool-read", "name": "read", "input": {}},
        ),
        stop_reason="tool_use",
        stop_details={},
        usage={},
        pending_client_message_id="message-read",
        pending_server_message_id=None,
        bundle_fingerprint=source[NATIVE_TOOL_BUNDLE_KWARG]["fingerprint"],
        provider_fingerprint=context["chain_id"],
        model_fingerprint=context["model"],
        thinking_fingerprint=context["thinking_fingerprint"],
    ).to_dict()
    return [
        {"role": "user", "content": "Read the file"},
        {"role": "assistant", "content": "", "_anthropic_native_envelope": envelope},
        {"role": "tool", "tool_call_id": "tool-read", "content": "file contents"},
    ]


def test_active_signed_tool_group_replays_on_compatible_account():
    source, _ = chain("primary")
    target, info = chain("backup")
    original = history(source)
    saved = deepcopy(original)
    replay = prepare_native_account_replay(original, source, target, continuation_required=True)
    assert original == saved
    assert (
        replay[1]["_anthropic_native_envelope"]["native_blocks"]
        == saved[1]["_anthropic_native_envelope"]["native_blocks"]
    )
    assert replay[2] == saved[2]
    assert (
        replay[1]["_anthropic_native_envelope"]["provider_fingerprint"]
        == target[NATIVE_REQUEST_CONTEXT_KWARG]["chain_id"]
    )
    _, wire, _ = build_native_request(
        provider=provider("backup"),
        model=info.model_id,
        model_info=info,
        messages=replay,
        request_kwargs={**target, NATIVE_CONTINUATION_REQUIRED_KWARG: True},
        credential_ref="$credential:anthropic-oauth",
    )
    assert any(
        block.get("signature") == "signed-content"
        for message in wire["messages"]
        for block in message["content"]
    )
    assert any(
        block.get("tool_use_id") == "tool-read"
        for message in wire["messages"]
        for block in message["content"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "claude-sonnet-4-6"),
        ("endpoint", "https://proxy.test/v1/messages"),
        ("auth_policy", "api_key"),
        ("location", "executor"),
        ("thinking_fingerprint", "changed"),
    ],
)
def test_incompatible_target_contract_is_rejected(field, value):
    source, _ = chain("primary")
    target, _ = chain("backup")
    target[NATIVE_REQUEST_CONTEXT_KWARG][field] = value
    expected = "integrity validation" if field == "location" else "incompatible wire contract"
    with pytest.raises(IncompatibleCandidate, match=expected):
        prepare_native_account_replay(history(source), source, target, continuation_required=True)


@pytest.mark.parametrize(
    "field",
    ["provider_fingerprint", "model_fingerprint", "bundle_fingerprint", "thinking_fingerprint"],
)
def test_active_envelope_identity_is_checked_before_rebinding(field):
    source, _ = chain("primary")
    target, _ = chain("backup")
    messages = history(source)
    messages[1]["_anthropic_native_envelope"][field] = "tampered"
    with pytest.raises(IncompatibleCandidate, match="integrity"):
        prepare_native_account_replay(messages, source, target, continuation_required=True)


def test_responses_history_and_missing_native_contract_remain_pinned():
    source, _ = chain("primary")
    target, _ = chain("backup")
    with pytest.raises(IncompatibleCandidate):
        prepare_native_account_replay(history(source), source, None, continuation_required=True)
    messages = history(source)
    messages[1]["responses_output_items"] = [{"type": "reasoning", "encrypted_content": "opaque"}]
    with pytest.raises(
        IncompatibleCandidate, match="Responses history requires its native provider"
    ):
        prepare_native_account_replay(messages, source, target, continuation_required=True)


@pytest.mark.parametrize("key", ["responses_output_items", "_responses_output_items"])
@pytest.mark.parametrize("continuation_required", [False, True])
def test_completed_responses_tool_history_does_not_block_anthropic_fallback(
    key, continuation_required
):
    source, _ = chain("primary")
    target, info = chain("backup")
    old = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "old-call",
                    "type": "function",
                    "function": {"name": "read", "arguments": "{}"},
                }
            ],
            key: [
                {"type": "function_call", "call_id": "old-call", "name": "read", "arguments": "{}"}
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "old-call",
            "content": "old result",
            key: [{"type": "function_call_output", "call_id": "old-call", "output": "old result"}],
        },
    ]
    messages = old + history(source)
    saved = deepcopy(messages)
    replay = prepare_native_account_replay(
        messages, source, target, continuation_required=continuation_required
    )
    assert messages == saved
    assert replay[:2] == old
    _, wire, _ = build_native_request(
        provider=provider("backup"),
        model=info.model_id,
        model_info=info,
        messages=replay,
        request_kwargs={**target, NATIVE_CONTINUATION_REQUIRED_KWARG: continuation_required},
        credential_ref="$credential:anthropic-oauth",
    )
    assert any(
        block.get("tool_use_id") == "old-call"
        for message in wire["messages"]
        for block in message["content"]
    )


def test_trailing_responses_tool_metadata_remains_blocked():
    source, _ = chain("primary")
    target, _ = chain("backup")
    messages = history(source)
    messages[-1]["_responses_output_items"] = [{"type": "function_call_output"}]
    with pytest.raises(
        IncompatibleCandidate, match="Responses history requires its native provider"
    ):
        prepare_native_account_replay(messages, source, target, continuation_required=True)


def test_refrozen_tool_exposure_keeps_previous_tool_group_historical():
    source, _ = chain("primary")
    target, info = chain("backup")
    messages = history(source)
    messages[1]["_anthropic_native_envelope"]["bundle_fingerprint"] = "previous-tool-exposure"
    replay = prepare_native_account_replay(messages, source, target, continuation_required=False)
    assert replay == messages
    build_native_request(
        provider=provider("backup"),
        model=info.model_id,
        model_info=info,
        messages=replay,
        request_kwargs={**target, NATIVE_CONTINUATION_REQUIRED_KWARG: False},
        credential_ref="$credential:anthropic-oauth",
    )
