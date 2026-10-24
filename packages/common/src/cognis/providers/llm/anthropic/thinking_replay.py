"""Local append-only proof for Sonnet 5.5 signed thinking.

The native transport seals the actual wire prefix, and checks it again before
I/O. Cache annotations are not conversation content. Everything else in the
system prompt, tool definitions, and preceding messages is covered. These
digests supplement, never replace, Anthropic's signature/account validation.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from cognis.providers.llm.anthropic.contracts import (
    AnthropicNativeEnvelope,
    ResolvedAnthropicRequestContext,
    sha256_fingerprint,
)
from cognis.providers.llm.anthropic.model_policy import anthropic_model_policy

REPLAY_FINGERPRINTS = "cognis_anthropic_thinking_prefix_fingerprints"
THINKING_TYPES = frozenset({"thinking", "redacted_thinking"})
logger = logging.getLogger(__name__)


def _without_cache(value: Mapping[str, Any]) -> dict[str, Any]:
    # Do not recursively erase keys: tool schemas and inputs may legitimately
    # contain a property named cache_control.
    return {key: item for key, item in value.items() if key != "cache_control"}


def thinking_prefix_fingerprints(
    context: ResolvedAnthropicRequestContext,
    payload: Mapping[str, Any],
    *,
    response_blocks: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, ...]:
    return _project_prefix(context, payload, response_blocks=response_blocks)[0]


def _project_prefix(
    context: ResolvedAnthropicRequestContext,
    payload: Mapping[str, Any],
    *,
    response_blocks: Sequence[Mapping[str, Any]] = (),
    expected: Sequence[str | None] | None = None,
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    system = payload.get("system", [])
    digest = sha256_fingerprint(
        {
            "version": 1,
            "provider": context.chain_id,
            "auth_policy": context.auth_policy.value,
            "system": [_without_cache(block) for block in system]
            if isinstance(system, list)
            else system,
            "tools": [_without_cache(tool) for tool in payload.get("tools", [])],
            # between_tools effort cannot change during a conversation.
            "between_tools_effort": (payload.get("output_config") or {}).get("effort", "high")
            if (payload.get("thinking") or {}).get("type") == "between_tools"
            else None,
        }
    )
    fingerprints: list[str] = []
    messages = list(payload.get("messages", []))
    if response_blocks:
        messages.append({"role": "assistant", "content": response_blocks})
    previous_role = None
    projected: list[dict[str, Any]] = []
    thinking_index = 0
    removed = 0
    for message in messages:
        role = message.get("role")
        # Anthropic merges adjacent equal-role messages. Hash the same logical
        # prefix for pause_turn continuations and after canonical conversion.
        retained: list[Any] = []
        content = message.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for block in content:
            candidate = digest
            if role != previous_role:
                candidate = sha256_fingerprint([candidate, {"role": role}])
            candidate = sha256_fingerprint([candidate, _without_cache(block)])
            if role == "assistant" and block.get("type") in THINKING_TYPES:
                proof = (
                    expected[thinking_index]
                    if expected is not None and thinking_index < len(expected)
                    else None
                )
                thinking_index += 1
                if expected is not None and proof != candidate:
                    removed += 1
                    continue
                fingerprints.append(candidate)
            digest = candidate
            previous_role = role
            retained.append(block)
        if retained:
            projected.append({**message, "content": retained})
    if removed:
        logger.info(
            "Reset incompatible thinking prefix: model=%s blocks=%d", context.model, removed
        )
    return tuple(fingerprints), projected


def prepare_thinking_replay(
    context: ResolvedAnthropicRequestContext,
    payload: dict[str, Any],
    expected: Any,
) -> None:
    if not anthropic_model_policy(context.model).binds_thinking_to_prefix:
        return
    _, projected = _project_prefix(
        context, payload, expected=expected if isinstance(expected, (list, tuple)) else ()
    )
    payload["messages"] = projected


def seal_thinking_replay(
    envelope: AnthropicNativeEnvelope,
    context: ResolvedAnthropicRequestContext,
    payload: Mapping[str, Any],
) -> AnthropicNativeEnvelope:
    if not anthropic_model_policy(context.model).binds_thinking_to_prefix:
        return envelope
    count = sum(block.get("type") in THINKING_TYPES for block in envelope.native_blocks)
    if not count:
        return envelope
    fingerprints = thinking_prefix_fingerprints(
        context, payload, response_blocks=envelope.native_blocks
    )
    return replace(envelope, thinking_prefix_fingerprints=fingerprints[-count:])
