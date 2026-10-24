"""Transport-neutral authorization, resolution and observation for inference clients."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import Any

from prometheus_client import Counter, Histogram
from sqlalchemy import select, update

from cognis.logging import get_logger
from cognis.ownership import SYSTEM_USER_EMAIL
from cognis.providers.llm.hosted import is_chat_model, systemone_provider_preset
from cognis.providers.llm.inference_accounting import (
    InferenceAttribution,
    estimated_cost,
    pricing_snapshot,
    usage_log_fields,
)
from cognis.providers.llm.litellm import llm_token_values
from cognis.providers.llm.routing import (
    COMPANION_DEFAULTS,
    COMPANION_ROUTES,
    EMBEDDING_ROUTES,
    INHERIT_COMPANION_MODEL,
    ROUTING_TASK_TYPES,
    companion_routes,
    route_chain,
)
from cognis.store.models import InferenceCompanion, LLMProvider, ModelRouting

logger = get_logger(__name__)
LABELS = ("client_id", "auth_type", "provider_id", "model", "operation", "requested_route")
INFERENCE_REQUESTS = Counter(
    "cognis_inference_requests_total", "Inference API requests.", (*LABELS, "outcome")
)
INFERENCE_TOKENS = Counter(
    "cognis_inference_tokens_total", "Reported inference API tokens.", (*LABELS, "kind")
)
INFERENCE_DURATION = Histogram(
    "cognis_inference_duration_seconds",
    "Inference API duration.",
    LABELS,
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60, 120),
)


class InferenceError(ValueError):
    """A safe client-facing inference failure."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class InferencePrincipal:
    owner: str
    client_id: str
    auth_type: str
    service: str | None = None
    models: frozenset[str] | None = None
    operations: frozenset[str] | None = None
    token_id: str | None = None


@dataclass(frozen=True)
class InferenceTarget:
    requested: str
    model: str
    provider_id: str
    owner: str
    reasoning_effort: str | None = None
    route_reference: str | None = None
    pricing: dict[str, Any] | None = None
    pricing_target: tuple[str, str] | None = None


class InferenceAPIService:
    """Share the LLM service without invoking agents, memory or guardrails."""

    def __init__(self, llm: Any, session_factory: Any) -> None:
        self.llm = llm
        self.session_factory = session_factory
        self._active: dict[str, int] = {}
        self._total = 0
        self._discovery_key = secrets.token_bytes(32)

    async def resolve(
        self,
        principal: InferencePrincipal,
        reference: str,
        operation: str,
    ) -> InferenceTarget:
        if principal.operations is not None and operation not in principal.operations:
            raise InferenceError(403, "permission_denied", "Operation not allowed by API key")
        if principal.models is not None and reference not in principal.models:
            raise InferenceError(403, "permission_denied", "Model not allowed by API key")
        role = reference.removeprefix("routes/") if reference.startswith("routes/") else None
        if principal.service and role not in companion_routes(principal.service):
            raise InferenceError(403, "permission_denied", "Companion may only use its own routes")
        reasoning = None
        global_only = role in {*COMPANION_ROUTES, *COMPANION_DEFAULTS}
        owner = SYSTEM_USER_EMAIL if global_only else principal.owner
        if role is not None:
            if role not in ROUTING_TASK_TYPES or role in {
                "speech_to_text",
                "text_to_speech",
                "image_generation",
            }:
                raise InferenceError(400, "invalid_model", "Unsupported inference routing alias")
            if (operation == "embeddings") != (role in EMBEDDING_ROUTES):
                raise InferenceError(400, "invalid_model", "Route does not support this operation")
            async with self.session_factory() as session:
                owners = (
                    [SYSTEM_USER_EMAIL]
                    if global_only
                    else list(dict.fromkeys([owner, SYSTEM_USER_EMAIL]))
                )
                route = None
                model_route = None
                for candidate in route_chain(role):
                    for route_owner in owners:
                        route = (
                            await session.execute(
                                select(ModelRouting).where(
                                    ModelRouting.owner_email == route_owner,
                                    ModelRouting.task_type == candidate,
                                )
                            )
                        ).scalar_one_or_none()
                        if route:
                            break
                    if route:
                        if reasoning is None:
                            reasoning = (route.config or {}).get("reasoning_effort")
                        if model_route is None and route.model != INHERIT_COMPANION_MODEL:
                            model_route = route
                route = model_route
                if route is None and global_only:
                    raise InferenceError(
                        503,
                        "model_unavailable",
                        "Configure global companion models in Settings → Routing",
                    )
                if route:
                    model = str(route.model)
                    provider_id = route.provider_id
                else:
                    model, provider_id = await self.llm.resolve_model_target(
                        task_type=role,
                        acting_user_email=owner,
                    )
            if not provider_id:
                model, provider_id = await self.llm.resolve_model_reference(
                    model,
                    acting_user_email=owner,
                )
        else:
            concrete = reference.removeprefix("providers/")
            model, provider_id = await self.llm.resolve_model_reference(
                concrete,
                acting_user_email=owner,
            )
        named_reference = model if model.startswith("cognis/") else None
        if named_reference is not None:
            plan = await self.llm.inference_plan(model=named_reference, acting_user_email=owner)
            if operation == "embeddings" and len(plan.candidates) != 1:
                raise InferenceError(
                    400, "invalid_model", "Multi-target embedding routes are not supported"
                )
            for candidate in plan.candidates:
                candidate_info = await self.llm.get_model_info(
                    candidate.target.model,
                    provider_id=candidate.target.provider_id,
                    acting_user_email=owner,
                )
                if bool(candidate_info.supports_embedding) != (operation == "embeddings"):
                    raise InferenceError(
                        400, "invalid_model", "Route mixes incompatible operations"
                    )
                if (candidate_info.model_mode == "systemone") != (operation == "systemone"):
                    raise InferenceError(
                        400, "invalid_model", "Route mixes incompatible operations"
                    )
            first = min(plan.candidates, key=lambda candidate: candidate.target.priority).target
            model, provider_id = first.model, first.provider_id
        async with self.session_factory() as session:
            provider = await session.get(LLMProvider, provider_id)
        if (
            provider is None
            or provider.status != "active"
            or provider.owner_email not in {owner, SYSTEM_USER_EMAIL}
            or (global_only and provider.owner_email != SYSTEM_USER_EMAIL)
        ):
            raise InferenceError(503, "model_unavailable", "Inference provider unavailable")
        # Recheck configuration at admission, including explicit route references.
        model, checked_id = await self.llm.resolve_model_reference(
            f"{provider.provider_id}/{model}",
            acting_user_email=owner,
        )
        if checked_id != provider.provider_id:
            raise InferenceError(503, "model_unavailable", "Inference provider unavailable")
        info = await self.llm.get_model_info(
            model,
            provider_id=provider.provider_id,
            acting_user_email=owner,
        )
        embedding = bool(getattr(info, "supports_embedding", False))
        if embedding != (operation == "embeddings"):
            raise InferenceError(400, "invalid_model", "Model does not support this operation")
        decision = getattr(info, "model_mode", None) == "systemone"
        if decision != (operation == "systemone"):
            raise InferenceError(400, "invalid_model", "Model does not support this operation")
        if operation == "chat" and not is_chat_model(
            {
                "model_mode": getattr(info, "model_mode", None),
                "supports_embedding": embedding,
            }
        ):
            raise InferenceError(400, "invalid_model", "Model does not support this operation")
        if operation == "systemone":
            if role is not None and role != "intaris_evaluation":
                raise InferenceError(400, "invalid_model", "Route does not support System One")
            if (
                systemone_provider_preset(
                    str(provider.config.get("preset", "")),
                    str(provider.config.get("api_base") or provider.config.get("base_url") or ""),
                )
                is None
            ):
                raise InferenceError(400, "invalid_model", "Provider does not support System One")
            reasoning = None
        if principal.service and operation == "embeddings":
            async with self.session_factory() as session:
                binding = await session.get(InferenceCompanion, principal.service)
            if binding and binding.embedding_reference not in {
                None,
                f"{provider.provider_id}/{model}",
            }:
                raise InferenceError(
                    503,
                    "embedding_reindex_required",
                    "Companion embedding model changed; prepare a reindex migration and reset its binding",
                )
        return InferenceTarget(
            reference,
            model,
            provider.provider_id,
            owner,
            reasoning,
            named_reference,
            pricing_snapshot(info),
            (provider.provider_id, model),
        )

    async def bind_embedding(
        self,
        principal: InferencePrincipal,
        target: InferenceTarget,
        dimensions: int,
    ) -> None:
        """Pin vector space at its first successful call, including concurrent starts."""
        if not principal.service:
            return
        reference = f"{target.provider_id}/{target.model}"
        async with self.session_factory() as session:
            await session.execute(
                update(InferenceCompanion)
                .where(
                    InferenceCompanion.service == principal.service,
                    InferenceCompanion.embedding_reference.is_(None),
                )
                .values(embedding_reference=reference, embedding_dimensions=dimensions)
            )
            row = await session.get(InferenceCompanion, principal.service)
            if (
                row is None
                or row.embedding_reference != reference
                or row.embedding_dimensions != dimensions
            ):
                raise InferenceError(
                    503,
                    "embedding_reindex_required",
                    "Companion embedding vector space changed; a reindex migration is required",
                )
            await session.commit()

    async def _operations(
        self,
        principal: InferencePrincipal,
        model_id: str,
        candidates: tuple[str, ...],
    ) -> list[str]:
        """Return the operations that resolve for this caller, using inference admission rules."""
        operations: list[str] = []
        for operation in candidates:
            try:
                await self.resolve(principal, model_id, operation)
            except (InferenceError, ValueError):
                continue
            operations.append(operation)
        return operations

    async def models(self, principal: InferencePrincipal) -> list[dict[str, Any]]:
        """List usable models with the operations each one resolves for the caller."""
        entries: list[dict[str, Any]] = []
        if not principal.service:
            refs = await self.llm.list_model_references(acting_user_email=principal.owner)
            for ref in refs:
                model_id = f"providers/{ref['value']}"
                if principal.models is None or model_id in principal.models:
                    operations = await self._operations(
                        principal, model_id, ("chat", "embeddings", "systemone")
                    )
                    if not operations:
                        continue
                    entries.append(
                        {
                            "id": model_id,
                            "object": "model",
                            "created": 0,
                            "owned_by": ref["provider_id"],
                            "cognis": {"operations": operations},
                        }
                    )
        roles = companion_routes(principal.service) if principal.service else ROUTING_TASK_TYPES
        for role in roles:
            model_id = f"routes/{role}"
            candidates = (
                ("embeddings",)
                if role in EMBEDDING_ROUTES
                else ("chat", "systemone")
                if role == "intaris_evaluation"
                else ("chat",)
            )
            operations = await self._operations(principal, model_id, candidates)
            if not operations:
                continue
            entries.append(
                {
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "cognis",
                    "cognis": {"operations": operations},
                }
            )
        for entry in entries:
            entry.update(
                await self._limits(principal, entry["id"], entry["cognis"]["operations"][0])
            )
        return entries

    async def model(
        self, principal: InferencePrincipal, model_id: str, operation: str | None = None
    ) -> dict[str, Any]:
        """Retrieve one authorized model, including slash-containing route/provider IDs."""
        operations = await self._operations(
            principal, model_id, ("chat", "embeddings", "systemone")
        )
        if not operations or operation is not None and operation not in operations:
            raise InferenceError(404, "model_not_found", "Model unavailable for this caller")
        selected = operation or operations[0]
        target = await self.resolve(principal, model_id, selected)
        return {
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "cognis" if model_id.startswith("routes/") else target.provider_id,
            "cognis": {"operations": operations},
            **await self._limits(principal, model_id, selected),
        }

    async def _limits(
        self, principal: InferencePrincipal, model_id: str, operation: str
    ) -> dict[str, Any]:
        target = await self.resolve(principal, model_id, operation)
        limits: dict[str, Any] = dict.fromkeys(
            ("context_window", "max_input_tokens", "max_output_tokens")
        )
        try:
            info = await self.llm.get_model_info(
                target.model, provider_id=target.provider_id, acting_user_email=target.owner
            )
            sources = info.provider_metadata.get("field_sources", {})
            for name in limits:
                value = getattr(info, name, None)
                if name in sources and type(value) is int and value > 0:
                    limits[name] = value
        except Exception:
            # Discovery failures never invent capacity or break standard model listing.
            pass
        material = json.dumps(
            [target.provider_id, target.model, operation, limits], sort_keys=True
        ).encode()
        limits["resolution_fingerprint"] = hmac.new(
            self._discovery_key, material, hashlib.sha256
        ).hexdigest()
        return limits

    @asynccontextmanager
    async def admission(self, principal: InferencePrincipal) -> AsyncIterator[None]:
        """Bound concurrent calls, retaining a slot through stream completion."""
        key = f"{principal.auth_type}:{principal.client_id}:{principal.owner}"
        self.check_admission(principal)
        self._active[key] = self._active.get(key, 0) + 1
        self._total += 1
        try:
            yield
        finally:
            self._total -= 1
            remaining = self._active[key] - 1
            if remaining:
                self._active[key] = remaining
            else:
                del self._active[key]

    def check_admission(self, principal: InferencePrincipal) -> None:
        key = f"{principal.auth_type}:{principal.client_id}:{principal.owner}"
        limit = 16 if principal.service else 4
        if self._total >= 64 or self._active.get(key, 0) >= limit:
            raise InferenceError(429, "rate_limit_exceeded", "Inference concurrency limit exceeded")

    def observe(
        self,
        principal: InferencePrincipal,
        target: InferenceTarget,
        operation: str,
        request_id: str,
        started: float,
        outcome: str,
        usage: dict[str, Any],
        attribution: InferenceAttribution | None = None,
    ) -> None:
        role = target.requested.removeprefix("routes/")
        requested_route = (
            role
            if target.requested.startswith("routes/") and role in ROUTING_TASK_TYPES
            else "named"
            if target.requested.startswith("cognis/")
            else "direct"
        )
        labels = (
            principal.client_id,
            principal.auth_type,
            target.provider_id,
            target.model,
            operation,
            requested_route,
        )
        tokens = llm_token_values(usage)
        for kind, value in tokens.items():
            if value > 0:
                INFERENCE_TOKENS.labels(*labels, kind).inc(value)
        INFERENCE_REQUESTS.labels(*labels, outcome).inc()
        INFERENCE_DURATION.labels(*labels).observe(monotonic() - started)
        usage_fields = usage_log_fields(usage, tokens, outcome)
        pricing = (
            target.pricing if target.pricing_target == (target.provider_id, target.model) else None
        )
        logger.info(
            "inference_request",
            extra={
                "extra_data": {
                    "request_id": request_id,
                    "client_id": principal.client_id,
                    "auth_type": principal.auth_type,
                    "token_id": principal.token_id,
                    "owner": principal.owner,
                    "requested_model": target.requested,
                    "provider_id": target.provider_id,
                    "model": target.model,
                    "operation": operation,
                    "outcome": outcome,
                    "duration_ms": int((monotonic() - started) * 1000),
                    "requested_route": requested_route,
                    "accounting_scope": "request",
                    "attempt_accounting": "incomplete",
                    "llm_request_id": request_id,
                    **(attribution.log_fields() if attribution else {}),
                    **usage_fields,
                    **estimated_cost(usage, usage_fields, pricing),
                }
            },
        )
