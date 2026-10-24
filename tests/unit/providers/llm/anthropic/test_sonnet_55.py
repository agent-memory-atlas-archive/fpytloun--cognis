"""Sonnet 5.5 acceptance through the native request and persistence boundaries."""

import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from cognis.core.agent_loop import _anthropic_native_envelope_for_persistence
from cognis.executor.backends.anthropic import AnthropicMessagesExecutorBackend
from cognis.executor.inference_types import CognisInferenceRequest
from cognis.models.config import ModelInfo
from cognis.providers.llm.anthropic.contracts import AnthropicNativeEnvelope
from cognis.providers.llm.anthropic.integration import build_native_request
from cognis.providers.llm.anthropic.model_policy import prepare_model_history
from cognis.providers.llm.anthropic.thinking_replay import REPLAY_FINGERPRINTS, seal_thinking_replay
from cognis.providers.llm.anthropic.transport import (
    AnthropicMessagesClient,
    AnthropicStreamDecoder,
    AnthropicTransportError,
    _envelope_from_message,
    _payload,
    _request_headers,
)
from cognis.providers.llm.anthropic_subscription import bundled_anthropic_model_entries
from cognis.providers.llm.litellm import LiteLLMProvider
from cognis.providers.llm.reasoning import (
    apply_reasoning_config,
    auxiliary_reasoning_effort_for_model,
    enrich_model_entry,
)

MODEL = "claude-sonnet-5-5"
TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
}


def _provider(*, oauth: bool = False, protocol: str = "auto") -> Any:
    return SimpleNamespace(
        provider_id="anthropic",
        location="controller",
        config={
            "preset": "anthropic",
            "protocol": protocol,
            "auth_config": {"mode": "oauth" if oauth else "secret"},
        },
    )


def _build(
    messages: list[dict[str, Any]], *, model: str = MODEL, oauth: bool = False, **kwargs: Any
):
    return build_native_request(
        provider=_provider(oauth=oauth),
        model=model,
        model_info=ModelInfo(model_id=model),
        messages=messages,
        request_kwargs={"tools": [deepcopy(TOOL)], **kwargs},
        credential_ref="$credential:anthropic",
    )


def test_catalog_retains_sonnet_5_and_exposes_sonnet_55_efforts_and_prices() -> None:
    entries = {entry["model_id"]: entry for entry in bundled_anthropic_model_entries()}
    assert "claude-sonnet-5" in entries
    entry = enrich_model_entry(entries[MODEL], provider_preset="anthropic")
    assert entry["context_window"] == 1_000_000
    assert entry["max_output_tokens"] == 128_000
    assert entry["input_cost_per_mtok"] == 2
    assert entry["output_cost_per_mtok"] == 10
    assert entry["reasoning_efforts"] == ["default", "low", "medium", "high", "xhigh", "max"]
    assert auxiliary_reasoning_effort_for_model(MODEL, supports_reasoning=True) == "low"
    assert enrich_model_entry({**entry, "reasoning_efforts": ["none", "low"]})[
        "reasoning_efforts"
    ] == ["low"]
    assert enrich_model_entry({**entry, "reasoning_efforts": ["none"]})["reasoning_efforts"] == [
        "default",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]


def test_haiku_55_catalog_capabilities_and_native_payload() -> None:
    model = "claude-haiku-5-5"
    entries = {entry["model_id"]: entry for entry in bundled_anthropic_model_entries()}
    entry = enrich_model_entry(entries[model], provider_preset="anthropic")
    context, request, bundle = _build(
        [{"role": "user", "content": "hello"}],
        model=model,
        max_tokens=4096,
    )
    wire = _payload(context, request, bundle, stream=False)

    assert entry["context_window"] == 1_000_000
    assert entry["max_output_tokens"] == 128_000
    assert wire["model"] == model
    assert wire["max_tokens"] == 4096


@pytest.mark.parametrize(
    "model",
    [
        MODEL,
        f"anthropic/{MODEL}",
        "Claude Sonnet 5.5",
        f"{MODEL}-20260928-preview",
        f"anthropic.{MODEL}-v1:0",
        "sonnet-5-5",
    ],
)
def test_adaptive_default_and_explicit_none_rejection(model: str) -> None:
    assert apply_reasoning_config({}, model_id=model, provider_preset="anthropic").request_kwargs[
        "thinking"
    ] == {"type": "adaptive"}
    with pytest.raises(ValueError, match="not supported"):
        apply_reasoning_config(
            {"reasoning_effort": "none"}, model_id=model, provider_preset="anthropic"
        )
    assert apply_reasoning_config(
        {"reasoning_effort": "xhigh"}, model_id=model, provider_preset="anthropic"
    ).request_kwargs["output_config"] == {"effort": "xhigh"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reasoning_effort": "none"},
        {"thinking": {"type": "disabled"}},
        {"thinking": {"type": "enabled", "budget_tokens": 4096}},
        {"thinking": {"type": "adaptive", "budget_tokens": 4096}},
        {"thinking": {"type": "between_tools", "display": "summarized"}},
        {"thinking": {"type": "between_tools"}, "output_config": {"effort": "xhigh"}},
        {"thinking": {"type": "between_tools"}, "output_config": {"effort": "max"}},
        {"tool_choice": "required"},
        {"tool_choice": "any"},
        {"tool_choice": {"type": "any"}},
        {"tool_choice": {"type": "tool", "name": "read_file"}},
        {"tool_choice": {"name": "read_file"}},
        {"tool_choice": {"type": "function", "function": {"name": "read_file"}}},
    ],
)
def test_unsupported_semantics_fail_in_reasoning_and_at_wire_boundary(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        apply_reasoning_config(kwargs, model_id=MODEL)
    context, payload, bundle = _build([{"role": "user", "content": "hello"}])
    with pytest.raises(AnthropicTransportError):
        _payload(context, {**payload, **kwargs}, bundle, stream=False)


def test_between_tools_is_explicit_and_none_keeps_tools_in_signed_prefix() -> None:
    kwargs = {"thinking": {"type": "between_tools"}, "output_config": {"effort": "high"}}
    assert apply_reasoning_config(kwargs, model_id=MODEL).request_kwargs == kwargs
    context, payload, bundle = _build([{"role": "user", "content": "hello"}], **kwargs)
    wire = _payload(context, {**payload, "tool_choice": "none"}, bundle, stream=False)
    assert wire["tool_choice"] == {"type": "none"}
    assert wire["tools"]


def test_litellm_transport_is_explicitly_unsupported() -> None:
    provider = LiteLLMProvider.__new__(LiteLLMProvider)
    with pytest.raises(ValueError, match="native anthropic_messages"):
        provider._prepare_generation_request_kwargs(
            {},
            model_id=MODEL,
            provider=_provider(protocol="litellm"),
            model_info=ModelInfo(model_id=MODEL),
        )


async def _credential(_ref: str) -> str:
    return "test-key"


async def _first_response(
    *, streaming: bool = False, oauth: bool = False, thinking_type: str = "adaptive"
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    history = [
        {"role": "system", "content": "Stable instructions"},
        {"role": "user", "content": "Read the file"},
    ]
    context, request, bundle = _build(history, oauth=oauth, thinking={"type": thinking_type})
    blocks = [
        {"type": "thinking", "thinking": "", "signature": "signed-empty-thinking"},
        {"type": "redacted_thinking", "data": "encrypted-thinking"},
        {
            "type": "tool_use",
            "id": "toolu_read",
            "name": bundle.bindings[0].wire_name,
            "input": {"path": "README.md"},
        },
    ]
    response = {
        "id": "msg_sonnet55",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": blocks,
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }

    def handler(http_request: httpx.Request) -> httpx.Response:
        wire = json.loads(http_request.content)
        assert not any(key.startswith("cognis_") for key in wire)
        if not streaming:
            return httpx.Response(200, json=response)
        events = [
            {"type": "message_start", "message": {**response, "content": [], "stop_reason": None}}
        ]
        for index, block in enumerate(blocks):
            start = dict(block)
            if block["type"] == "thinking":
                start.pop("signature")
            if block["type"] == "tool_use":
                start["input"] = {}
            events.append({"type": "content_block_start", "index": index, "content_block": start})
            if block["type"] == "thinking":
                events.append(
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "signature_delta", "signature": block["signature"]},
                    }
                )
            if block["type"] == "tool_use":
                events.append(
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": json.dumps(block["input"]),
                        },
                    }
                )
            events.append({"type": "content_block_stop", "index": index})
        events.extend(
            [
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 20},
                },
                {"type": "message_stop"},
            ]
        )
        return httpx.Response(
            200,
            text="".join(
                f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AnthropicMessagesClient(_credential, http_client=http)
        call = dict(provider_fingerprint=context.chain_id, model_fingerprint=MODEL)
        if streaming:
            chunks = [chunk async for chunk in client.stream(context, request, bundle, **call)]
            raw_envelope = chunks[-1]["anthropic_native_envelope"]
        else:
            result = await client.complete(context, request, bundle, **call)
            raw_envelope = result["anthropic_native_envelope"]
    persisted = _anthropic_native_envelope_for_persistence(raw_envelope)
    assert persisted is not None
    envelope = AnthropicNativeEnvelope.from_dict(json.loads(json.dumps(persisted)))
    assert len(envelope.thinking_prefix_fingerprints) == 2
    history += [
        {"role": "assistant", "content": None, "_anthropic_native_envelope": envelope.to_dict()},
        {"role": "tool", "tool_call_id": "toolu_read", "content": "File contents"},
    ]
    return history, {"thinking": {"type": thinking_type}}


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("oauth", [False, True])
async def test_exact_signed_tool_continuation_survives_persistence(
    streaming: bool, oauth: bool
) -> None:
    history, kwargs = await _first_response(streaming=streaming, oauth=oauth)
    context, request, bundle = _build(history, oauth=oauth, **kwargs)
    wire = _payload(context, request, bundle, stream=streaming)
    blocks = wire["messages"][1]["content"]
    assert blocks[0] == {"type": "thinking", "thinking": "", "signature": "signed-empty-thinking"}
    assert blocks[1] == {"type": "redacted_thinking", "data": "encrypted-thinking"}
    assert wire["messages"][2]["content"][0]["tool_use_id"] == "toolu_read"
    if oauth:
        assert (
            "interleaved-thinking"
            not in _request_headers(context, "test-token", request)["anthropic-beta"]
        )


@pytest.mark.parametrize(
    "change", ["system", "user", "tools", "provider", "unknown", "block", "reorder"]
)
async def test_changed_or_unproven_prefix_resets_only_thinking(change: str) -> None:
    history, kwargs = await _first_response()
    if change == "system":
        history[0]["content"] = "Changed instructions"
    elif change == "user":
        history[1]["content"] = "Changed earlier request"
    elif change == "unknown":
        history[2]["_anthropic_native_envelope"].pop("thinking_prefix_fingerprints")
    elif change == "block":
        history[2]["_anthropic_native_envelope"]["native_blocks"][0]["signature"] = "changed"
    elif change == "reorder":
        history[2]["_anthropic_native_envelope"]["native_blocks"].reverse()
    context, request, bundle = _build(history, **kwargs)
    if change == "tools":
        from dataclasses import replace

        bundle = replace(
            bundle,
            wire_tools=tuple({**tool, "description": "Changed"} for tool in bundle.wire_tools),
        )
    elif change == "provider":
        from dataclasses import replace

        context = replace(context, chain_id="another-provider-chain")
    original = deepcopy(history)
    wire = _payload(context, request, bundle, stream=False)
    assert history == original
    blocks = [block for message in wire["messages"] for block in message["content"]]
    assert not any(block["type"] in {"thinking", "redacted_thinking"} for block in blocks)
    assert any(block["type"] == "tool_use" and block["id"] == "toolu_read" for block in blocks)
    assert any(
        block["type"] == "tool_result" and block["content"] == "File contents" for block in blocks
    )


async def test_cache_annotations_and_appended_messages_are_not_prefix_edits() -> None:
    history, kwargs = await _first_response()
    history[0]["_cache_control"] = {"type": "ephemeral"}
    history[1]["_cache_control"] = {"type": "ephemeral"}
    history.append({"role": "user", "content": "Continue"})
    context, request, bundle = _build(history, **kwargs)
    _payload(context, request, bundle, stream=False)


@pytest.mark.parametrize(
    "source,target",
    [
        ("claude-opus-5", MODEL),
        ("claude-opus-5-5", MODEL),
        ("claude-sonnet-5", MODEL),
        (MODEL, "claude-opus-5"),
        (MODEL, "claude-opus-5-5"),
        (MODEL, "claude-sonnet-5"),
    ],
)
async def test_cross_model_replay_preserves_tool_history_in_both_directions(
    source: str, target: str
) -> None:
    history, kwargs = await _first_response()
    history[2]["_anthropic_native_envelope"]["model_fingerprint"] = source
    original = deepcopy(history)
    projected = prepare_model_history(target, history)
    context, request, bundle = _build(projected, model=target, **kwargs)
    wire = _payload(context, request, bundle, stream=False)
    assert history == original
    assert [block["type"] for block in wire["messages"][1]["content"]] == ["tool_use"]
    assert wire["messages"][2]["content"][0]["tool_use_id"] == "toolu_read"


async def test_between_tools_effort_change_resets_thinking() -> None:
    history, kwargs = await _first_response(thinking_type="between_tools")
    context, request, bundle = _build(history, **kwargs, output_config={"effort": "low"})
    wire = _payload(context, request, bundle, stream=False)
    assert [block["type"] for block in wire["messages"][1]["content"]] == ["tool_use"]


@pytest.mark.parametrize("model", [MODEL, f"{MODEL}-20260928-preview", "sonnet-5-5"])
def test_legacy_unproven_thinking_resets_without_losing_visible_history(model: str) -> None:
    messages = [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "answer",
            "_anthropic_thinking_blocks": [
                {"type": "thinking", "thinking": "", "signature": "old-signature"},
            ],
        },
        {"role": "user", "content": "continue"},
    ]
    context, request, bundle = _build(messages, model=model)
    assert request[REPLAY_FINGERPRINTS] == []
    wire = _payload(context, request, bundle, stream=False)
    assert wire["messages"][1]["content"] == [{"type": "text", "text": "answer"}]
    assert messages[1]["_anthropic_thinking_blocks"][0]["signature"] == "old-signature"


async def test_executor_preparation_checks_the_same_persisted_prefix() -> None:
    history, kwargs = await _first_response()
    backend = AnthropicMessagesExecutorBackend()
    request = CognisInferenceRequest(
        model=MODEL,
        messages=history,
        request_kwargs={**kwargs, "tools": [TOOL], "api_key": "test-key"},
        provider_id="anthropic",
        backend_metadata={"anthropic_native": {"config": _provider().config}},
    )
    try:
        _, context, payload, bundle = backend._prepared(request)
        _payload(context, payload, bundle, stream=False)
        request.messages[0]["content"] = "Changed system"
        _, context, payload, bundle = backend._prepared(request)
        wire = _payload(context, payload, bundle, stream=False)
        assert [block["type"] for block in wire["messages"][1]["content"]] == ["tool_use"]
    finally:
        await backend.close()


@pytest.mark.parametrize("streaming", [False, True])
def test_fallback_response_cannot_be_mislabeled_as_sonnet_55(streaming: bool) -> None:
    context, _, bundle = _build([{"role": "user", "content": "hello"}])
    message = {
        "model": "claude-sonnet-5",
        "content": [{"type": "thinking", "thinking": "", "signature": "fallback-signature"}],
        "stop_reason": "end_turn",
    }
    options = dict(
        bundle=bundle,
        provider_fingerprint=context.chain_id,
        model_fingerprint=MODEL,
        thinking_fingerprint=context.thinking_fingerprint,
    )
    with pytest.raises(AnthropicTransportError, match="response model differs"):
        if streaming:
            AnthropicStreamDecoder(**options).feed({"type": "message_start", "message": message})
        else:
            _envelope_from_message(message, **options)


def _answer_envelope(context, wire, bundle, signature: str) -> dict[str, Any]:
    envelope = _envelope_from_message(
        {
            "model": context.model,
            "content": [
                {"type": "thinking", "thinking": "", "signature": signature},
                {"type": "text", "text": "Completed"},
            ],
            "stop_reason": "end_turn",
        },
        bundle=bundle,
        provider_fingerprint=context.chain_id,
        model_fingerprint=context.model,
        thinking_fingerprint=context.thinking_fingerprint,
    )
    return seal_thinking_replay(envelope, context, wire).to_dict()


async def test_prefix_reset_preserves_fresh_reasoning_on_subsequent_turns() -> None:
    history, kwargs = await _first_response()
    history[0]["content"] = "Updated instructions"
    context, request, bundle = _build(history, **kwargs)
    wire = _payload(context, request, bundle, stream=False)
    envelope = _answer_envelope(context, wire, bundle, "fresh-signature")
    history.extend(
        [
            {"role": "assistant", "content": "Completed", "_anthropic_native_envelope": envelope},
            {"role": "user", "content": "Next step"},
        ]
    )
    context, request, bundle = _build(history, **kwargs)
    wire = _payload(context, request, bundle, stream=False)
    thinking = [
        block
        for message in wire["messages"]
        for block in message["content"]
        if block["type"] in {"thinking", "redacted_thinking"}
    ]
    assert thinking == [{"type": "thinking", "thinking": "", "signature": "fresh-signature"}]
    assert len(history[2]["_anthropic_native_envelope"]["native_blocks"]) == 3


async def test_switch_back_does_not_resurrect_old_reasoning_and_keeps_new_reasoning() -> None:
    history, kwargs = await _first_response()
    context, request, bundle = _build(history, model="claude-opus-5-5", **kwargs)
    wire = _payload(context, request, bundle, stream=False)
    history.extend(
        [
            {
                "role": "assistant",
                "content": "Completed",
                "_anthropic_native_envelope": _answer_envelope(
                    context, wire, bundle, "opus-signature"
                ),
            },
            {"role": "user", "content": "Back to Sonnet"},
        ]
    )
    context, request, bundle = _build(history, **kwargs)
    wire = _payload(context, request, bundle, stream=False)
    assert not any(
        block["type"] in {"thinking", "redacted_thinking"}
        for message in wire["messages"]
        for block in message["content"]
    )
    history.extend(
        [
            {
                "role": "assistant",
                "content": "Completed",
                "_anthropic_native_envelope": _answer_envelope(
                    context, wire, bundle, "returned-signature"
                ),
            },
            {"role": "user", "content": "Continue Sonnet"},
        ]
    )
    context, request, bundle = _build(history, **kwargs)
    wire = _payload(context, request, bundle, stream=False)
    assert [
        block.get("signature")
        for message in wire["messages"]
        for block in message["content"]
        if block["type"] == "thinking"
    ] == ["returned-signature"]
