"""Typed agent request/decoder handoff at the inference attempt boundary."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from cognis.providers.llm.anthropic.contracts import (
    AnthropicNativeEnvelope,
    AnthropicProtocol,
    CompiledAnthropicToolBundle,
    ResolvedAnthropicRequestContext,
)
from cognis.providers.llm.anthropic.integration import (
    NATIVE_REQUEST_CONTEXT_KWARG,
    NATIVE_TOOL_BUNDLE_KWARG,
    OFFICIAL_MESSAGES_ENDPOINT,
)
from cognis.providers.llm.cache_policy import apply_cache_ttl
from cognis.providers.llm.recovery import IncompatibleCandidate


def _cache_neutral_bundle(bundle: CompiledAnthropicToolBundle) -> dict[str, Any]:
    value = bundle.to_dict()
    value.pop("fingerprint", None)
    apply_cache_ttl(value, "5m")
    return value


def prepare_native_account_replay(
    messages: list[dict[str, Any]],
    source_chain: dict[str, Any] | None,
    target_chain: dict[str, Any] | None,
    *,
    continuation_required: bool,
) -> list[dict[str, Any]]:
    """Copy native history for a compatible account switch before any output.

    Only Cognis's account-bound envelope fingerprint is rebound. Signed native
    blocks, tool IDs, bundle identity and canonical history remain untouched.
    Transport validation still checks the target identity and active tool group.
    """
    if source_chain is None or target_chain is None:
        raise IncompatibleCandidate("Native history requires a compatible Anthropic account")
    try:
        source = ResolvedAnthropicRequestContext.from_dict(
            source_chain[NATIVE_REQUEST_CONTEXT_KWARG]
        )
        target = ResolvedAnthropicRequestContext.from_dict(
            target_chain[NATIVE_REQUEST_CONTEXT_KWARG]
        )
        source_bundle = CompiledAnthropicToolBundle.from_dict(
            source_chain[NATIVE_TOOL_BUNDLE_KWARG]
        )
        target_bundle = CompiledAnthropicToolBundle.from_dict(
            target_chain[NATIVE_TOOL_BUNDLE_KWARG]
        )
        # Restrict portability to the official service and the identical wire
        # contract. Third-party endpoints and other native protocols fail closed.
        if (
            source.endpoint != OFFICIAL_MESSAGES_ENDPOINT
            or target.endpoint != source.endpoint
            or source.protocol != AnthropicProtocol.ANTHROPIC_MESSAGES
            or target.protocol != source.protocol
            or target.model != source.model
            or target.auth_policy != source.auth_policy
            or target.location != source.location
            or target.model_info != source.model_info
            or target.thinking_fingerprint != source.thinking_fingerprint
            or _cache_neutral_bundle(target_bundle) != _cache_neutral_bundle(source_bundle)
        ):
            raise IncompatibleCandidate("Native fallback account has an incompatible wire contract")
        result = deepcopy(messages)
        last_assistant = max(
            (i for i, message in enumerate(result) if message.get("role") == "assistant"),
            default=-1,
        )
        for index, message in enumerate(result):
            for key in ("responses_output_items", "_responses_output_items"):
                # Earlier completed tool groups can belong to a different
                # provider. Only the current assistant group can constrain
                # continuation; trailing tool metadata remains fail-closed.
                if message.get(key) and index >= last_assistant:
                    raise IncompatibleCandidate("Responses history requires its native provider")
            for key in ("anthropic_native_envelope", "_anthropic_native_envelope"):
                raw = message.get(key)
                if raw is None:
                    continue
                envelope = AnthropicNativeEnvelope.from_dict(raw)
                if continuation_required and index == last_assistant:
                    # Check the original identity before changing account metadata.
                    envelope.assert_matches(
                        bundle_fingerprint=source_bundle.fingerprint,
                        provider_fingerprint=source.chain_id,
                        model_fingerprint=source.model,
                        thinking_fingerprint=source.thinking_fingerprint,
                    )
                    raw["provider_fingerprint"] = target.chain_id
                    raw["bundle_fingerprint"] = target_bundle.fingerprint
        return result
    except IncompatibleCandidate:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise IncompatibleCandidate("Native fallback history failed integrity validation") from exc


@dataclass(frozen=True)
class AgentInferenceDecoder:
    model: str
    provider_id: str | None
    model_info: Any
    exposure: Any
    exposure_contract: Any
    discovery_mode: Any
    projected: Any
    native_chain: Any
    native_fingerprint: str | None
    reasoning_mode: Any
    projection_state: Any = None


@dataclass(frozen=True)
class AuxiliaryInference:
    """Detached request for one text-only operation, never an executable agent turn."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    model: str
    provider_id: str | None
    request_kwargs: dict[str, Any]
