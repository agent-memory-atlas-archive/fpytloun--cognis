"""Exact native-count parity and bounded reuse for growing context histories."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import litellm
import pytest

from cognis.providers.llm.litellm import (
    _COUNT_MEMO_MAX_ENTRIES,
    _COUNT_MESSAGE_BLOCK_SIZE,
    LiteLLMProvider,
)


def _messages(count: int = 70) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for index in range(count):
        text = f"Record {index}: " + "Preserve přesný Unicode text and tool output. " * 80
        messages.append({"role": "user", "content": text})
    messages[0] = {"role": "system", "content": "Keep the complete instructions."}
    messages[3] = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-count",
                "type": "function",
                "function": {"name": "read", "arguments": '{"path": "/project/source.py"}'},
            }
        ],
    }
    messages[4].update(role="tool", tool_call_id="call-count")
    messages[5].update(name="reviewer", content=[{"type": "text", "text": "Review text."}])
    return messages


@pytest.mark.parametrize("model", ["gpt-4o", "claude-sonnet-5", "gemini/gemini-2.5-pro"])
def test_block_counts_match_native_before_and_after_mutation(model: str) -> None:
    provider = LiteLLMProvider(object())  # type: ignore[arg-type]
    messages = _messages()
    original = copy.deepcopy(messages)
    assert provider.count_messages_tokens(messages, model) == litellm.token_counter(
        model=model, messages=messages
    )
    assert messages == original
    for edit in ("append", "content", "arguments", "name", "markers", "boundary", "remove"):
        if edit == "append":
            messages.append({"role": "assistant", "content": "Small tail."})
        elif edit == "content":
            messages[10]["content"] += " Changed prefix."
        elif edit == "arguments":
            messages[3]["tool_calls"][0]["function"]["arguments"] = '{"path": "/project/tests.py"}'
        elif edit == "name":
            messages[10]["name"] = "another reviewer"
        elif edit == "markers":
            for message in messages:
                message["_token_estimate"] = 100
                message["_audit"] = {"seq": 3}
            messages[10]["string_marker"] = "Native counting sees string-valued fields."
        elif edit == "boundary":
            messages.insert(_COUNT_MESSAGE_BLOCK_SIZE, {"role": "user", "content": "Insert."})
        else:
            del messages[:12]
        assert provider.count_messages_tokens(messages, model) == litellm.token_counter(
            model=model, messages=messages
        )


def test_growing_tail_reuses_exact_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    native = litellm.token_counter
    counted_sizes: list[int] = []

    def count(**kwargs: Any) -> int:
        counted_sizes.append(len(kwargs["messages"]))
        return native(**kwargs)

    monkeypatch.setattr(litellm, "token_counter", count)
    provider = LiteLLMProvider(object())  # type: ignore[arg-type]
    messages = _messages()
    assert provider.count_messages_tokens(messages, "gpt-4o") == native(
        model="gpt-4o", messages=messages
    )
    counted_sizes.clear()
    messages.append({"role": "assistant", "content": "One new message."})
    assert provider.count_messages_tokens(messages, "gpt-4o") == native(
        model="gpt-4o", messages=messages
    )
    assert counted_sizes == [0, 7], "Only priming and the changed tail need native counting"
    counted_sizes.clear()
    provider.count_messages_tokens(messages, "gpt-4o")
    assert counted_sizes == [], "The existing complete-transcript memo still applies"


@pytest.mark.parametrize("size", [0, 1, 31, 32, 33, 64, 65])
def test_block_boundaries_preserve_response_priming(size: int) -> None:
    messages = [{"role": "user", "content": "A short message."} for _ in range(size)]
    provider = LiteLLMProvider(object())  # type: ignore[arg-type]
    assert provider.count_messages_tokens(messages, "gpt-4o") == litellm.token_counter(
        model="gpt-4o", messages=messages
    )


def test_multimodal_block_count_matches_native_without_network() -> None:
    messages = _messages()
    messages[32]["content"] = [
        {"type": "text", "text": "Describe this low-detail image."},
        {
            "type": "image_url",
            # Low detail has a fixed native count; no remote image is fetched.
            "image_url": {"url": "data:image/png;base64,cG5n", "detail": "low"},
        },
    ]
    provider = LiteLLMProvider(object())  # type: ignore[arg-type]
    assert provider.count_messages_tokens(messages, "gpt-4o") == litellm.token_counter(
        model="gpt-4o", messages=messages
    )


def test_failed_block_count_does_not_publish_partial_memo(monkeypatch: pytest.MonkeyPatch) -> None:
    native = litellm.token_counter
    blocks = 0

    def fail_second_block(**kwargs: Any) -> int:
        nonlocal blocks
        if kwargs.get("count_response_tokens"):
            blocks += 1
            if blocks == 2:
                raise RuntimeError("Synthetic tokenizer failure")
        return native(**kwargs)

    monkeypatch.setattr(litellm, "token_counter", fail_second_block)
    provider = LiteLLMProvider(object())  # type: ignore[arg-type]
    # Isolate the existing fallback to test publication of the failed native path.
    monkeypatch.setattr(provider, "count_tokens", lambda *_: 20)
    assert provider.count_messages_tokens(_messages(), "gpt-4o") == 22
    assert provider._count_memo == {}


def test_block_memo_is_bounded_isolated_and_thread_safe() -> None:
    provider = LiteLLMProvider(object())  # type: ignore[arg-type]
    native = litellm.token_counter
    messages = _messages()
    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(
            pool.map(
                lambda model: provider.count_messages_tokens(messages, model),
                ["gpt-4o", "claude-sonnet-5"] * 4,
            )
        )
    assert counts == [
        native(model=model, messages=messages) for model in ["gpt-4o", "claude-sonnet-5"] * 4
    ]
    for index in range(_COUNT_MEMO_MAX_ENTRIES + 2):
        changed = [{**message, "name": f"revision-{index}"} for message in messages]
        provider.count_messages_tokens(changed, "gpt-4o")
    assert len(provider._count_memo) <= _COUNT_MEMO_MAX_ENTRIES
    provider.clear_count_memo()
    assert not provider._count_memo
