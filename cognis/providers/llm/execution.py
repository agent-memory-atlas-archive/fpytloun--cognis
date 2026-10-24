"""Request-scoped inference planning and candidate preparation contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from cognis.ownership import SYSTEM_USER_EMAIL
from cognis.providers.llm.recovery import InferenceCandidate, InferencePlan
from cognis.providers.llm.recovery_policy import RecoveryPolicy, RouteTarget
from cognis.providers.llm.route_store import InferenceRouteStore
from cognis.store.models import LLMProvider


@dataclass
class PreparedInference:
    """Request and decoder state belong to exactly one concrete candidate."""

    messages: list[dict[str, Any]]
    kwargs: dict[str, Any] = field(default_factory=dict)
    decoder: Any = None


@dataclass(frozen=True)
class PreparedCall:
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    decoder: Any = None


def validate_request_compatibility(
    messages: list[dict[str, Any]], kwargs: dict[str, Any], info: Any
) -> None:
    """Required features are never silently dropped to make a fallback fit."""
    from cognis.providers.llm.recovery import IncompatibleCandidate

    if kwargs.get("tools") and not info.supports_tools:
        raise IncompatibleCandidate("Candidate does not support required tools")
    response_format = kwargs.get("response_format")
    # JSON-object mode is not schema-constrained structured output. Adapters
    # already implement and validate that mode, including native Codex.
    if (
        isinstance(response_format, dict)
        and response_format.get("type") == "json_schema"
        and not info.supports_structured_output
    ):
        raise IncompatibleCandidate("Candidate does not support structured output")
    required = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            kind = value.get("type")
            if kind in {"image_url", "image", "input_image"}:
                required.add("vision")
            if kind in {"input_audio", "audio"}:
                required.add("audio_input")
            if kind in {"document", "input_file", "file"}:
                required.add("file_input")
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(messages)
    for feature in required:
        supported = getattr(info, f"supports_{feature}", False)
        if feature == "file_input":
            supported = supported or getattr(info, "supports_pdf_input", False)
        if not supported:
            raise IncompatibleCandidate(f"Candidate does not support required {feature}")


async def build_inference_plan(
    provider: Any,
    *,
    model: str | None,
    provider_id: str | None,
    task_type: str,
    owner: str | None,
    session_identity: str | None,
    retry_override: int | None = None,
) -> InferencePlan:
    """Resolve role indirection once, then authorize every concrete candidate."""
    from cognis.providers.llm.litellm import LiteLLMProvider

    owner = owner or SYSTEM_USER_EMAIL
    store = InferenceRouteStore(provider.session_factory)
    reference = model or f"routes/{task_type}"
    if model and model.startswith("routes/"):
        task_type, model, provider_id = model.removeprefix("routes/"), None, None
    if model is None and provider_id is None:
        role = await store.role(task_type, owner)
        if role is not None:
            model, provider_id, owner = role.model, role.provider_id, role.owner
    policy = RecoveryPolicy()
    scope = "direct"
    binding_reference = reference
    if model and model.startswith("cognis/"):
        if provider_id not in (None, "cognis"):
            raise ValueError("A named route cannot override a concrete provider")
        route = await store.get(model, owner)
        targets = route.config.targets
        policy = route.config.recovery
        scope = f"{route.route_id}:{route.revision}"
        binding_reference = route.route_id
    else:
        resolved, row = await LiteLLMProvider._resolve_model_target(
            provider,
            model,
            task_type=task_type,
            explicit_provider_id=provider_id,
            acting_user_email=owner,
        )
        if row is None:
            raise ValueError("No inference provider configured")
        targets = [RouteTarget(provider_id=row.provider_id, model=resolved)]
        binding_reference = f"{row.provider_id}/{resolved}"
    candidates = []
    for target in targets:
        if scope != "direct":
            async with provider.session_factory() as session:
                configured = await session.get(LLMProvider, target.provider_id)
                if configured is None or configured.status != "active":
                    continue
        resolved, row = await LiteLLMProvider._resolve_model_target(
            provider,
            target.model,
            task_type=task_type,
            explicit_provider_id=target.provider_id,
            acting_user_email=owner,
        )
        if row is None:
            raise ValueError("Inference target is unavailable")
        identity = {
            "id": row.provider_id,
            "owner": row.owner_email,
            "config": row.config,
            "location": row.location,
        }
        account_fingerprint = hashlib.sha256(
            json.dumps(identity, sort_keys=True, default=str).encode()
        ).hexdigest()
        fingerprint = hashlib.sha256(
            json.dumps({**identity, "model": resolved}, sort_keys=True, default=str).encode()
        ).hexdigest()
        candidates.append(
            InferenceCandidate(
                target.model_copy(update={"model": resolved}), fingerprint, account_fingerprint
            )
        )
    if retry_override is not None:
        policy = policy.model_copy(
            update={"max_retries_per_target": max(0, min(10, retry_override))}
        )
    if not candidates:
        raise ValueError("Inference route has no active targets")
    return InferencePlan(
        reference=reference,
        owner=owner,
        candidates=tuple(candidates),
        policy=policy,
        policy_scope=scope,
        session_identity=session_identity,
        binding_reference=binding_reference,
    )
