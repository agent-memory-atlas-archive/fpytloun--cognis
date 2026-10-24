"""Portable request restrictions for model-specific Messages API contracts."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AnthropicModelPolicy:
    supports_disabled_thinking: bool = True
    supports_forced_tools: bool = True
    binds_thinking_to_prefix: bool = False


_DEFAULT = AnthropicModelPolicy()
_SONNET_55 = AnthropicModelPolicy(False, False, True)
_THINKING_TYPES = {"thinking", "redacted_thinking"}
logger = logging.getLogger(__name__)


def matches_anthropic_model_key(candidate: str, key: str) -> bool:
    """Match the same documented ID/alias forms for reasoning and wire policy."""
    normalized = re.sub(r"[\s._/]+", "-", candidate.strip().lower())
    for prefix in (f"claude-{key}", key):
        start = 0
        while True:
            index = normalized.find(prefix, start)
            if index < 0:
                break
            before = normalized[index - 1] if index > 0 else ""
            if before and before.isalnum():
                start = index + 1
                continue
            suffix = normalized[index + len(prefix) :]
            if (
                not suffix
                or suffix == "-alias"
                or re.fullmatch(r"-\d{8}(?:-[a-z0-9:-]+)?", suffix)
                or re.fullmatch(r"-v\d+(?::\d+)?", suffix)
            ):
                return True
            start = index + 1
    return False


def anthropic_model_policy(model: str) -> AnthropicModelPolicy:
    if matches_anthropic_model_key(model, "sonnet-5-5"):
        return _SONNET_55
    return _DEFAULT


def validate_model_request(model: str, request: Mapping[str, Any]) -> None:
    """Reject unsupported semantics, never replace them with weaker settings."""
    policy = anthropic_model_policy(model)
    if not policy.binds_thinking_to_prefix:
        return
    if str(request.get("reasoning_effort") or "").strip().lower() == "none":
        raise ValueError(f"Reasoning effort 'none' is not supported by {model}")
    thinking = request.get("thinking")
    if thinking is not None:
        if not isinstance(thinking, Mapping) or thinking.get("type") not in {
            "adaptive",
            "between_tools",
        }:
            raise ValueError(
                f"{model} supports only adaptive or explicit between_tools thinking; "
                "disabled thinking and manual budgets are unsupported"
            )
        if "budget_tokens" in thinking:
            raise ValueError(f"{model} does not support manual thinking budgets")
        if thinking.get("type") == "between_tools":
            output = request.get("output_config") or {}
            if set(thinking) != {"type"} or output.get("effort", "high") not in {
                "low",
                "medium",
                "high",
            }:
                raise ValueError(
                    f"{model} between_tools requires low, medium, or high effort "
                    "and accepts no additional thinking fields"
                )
    choice = request.get("tool_choice")
    choice_type = choice.get("type") if isinstance(choice, Mapping) else choice
    if not policy.supports_forced_tools and (
        choice_type in {"required", "any", "tool", "function"}
        or (isinstance(choice, Mapping) and choice.get("mode") == "required")
        or (isinstance(choice, Mapping) and ("name" in choice or "function" in choice))
    ):
        raise ValueError(
            f"{model} does not support forced tool choice; use a compatible model "
            "when a tool call is required"
        )


def prepare_model_history(model: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project a switch without changing durable messages or tool history.

    Older reasoning must not reappear when switching A -> B -> A. The last
    foreign-model assistant envelope is a stable reset boundary on every replay.
    """
    envelopes = [
        (index, message["_anthropic_native_envelope"])
        for index, message in enumerate(messages)
        if isinstance(message.get("_anthropic_native_envelope"), Mapping)
    ]
    if not (
        anthropic_model_policy(model).binds_thinking_to_prefix
        or any(
            anthropic_model_policy(
                str(envelope.get("model_fingerprint") or "")
            ).binds_thinking_to_prefix
            for _, envelope in envelopes
        )
    ):
        return messages
    boundary = max(
        (index for index, envelope in envelopes if envelope.get("model_fingerprint") != model),
        default=-1,
    )
    projected = deepcopy(messages)
    removed = 0
    for index, message in enumerate(projected):
        envelope = message.get("_anthropic_native_envelope")
        if isinstance(envelope, dict) and index <= boundary:
            blocks = envelope.get("native_blocks")
            if isinstance(blocks, list):
                retained = [block for block in blocks if block.get("type") not in _THINKING_TYPES]
                removed += len(blocks) - len(retained)
                envelope["native_blocks"] = retained
                envelope.pop("thinking_prefix_fingerprints", None)
        # Unproven legacy thinking cannot be attributed to a model or prefix.
        if index <= boundary or not isinstance(envelope, Mapping):
            for field in ("content", "_anthropic_thinking_blocks", "_anthropic_native_blocks"):
                blocks = message.get(field)
                if isinstance(blocks, list):
                    retained = [
                        block
                        for block in blocks
                        if not isinstance(block, Mapping)
                        or block.get("type") not in _THINKING_TYPES
                    ]
                    removed += len(blocks) - len(retained)
                    message[field] = retained
    if removed:
        logger.info(
            "Reset signed thinking for model transition: model=%s blocks=%d", model, removed
        )
    return projected
