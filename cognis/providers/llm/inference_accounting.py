"""Bounded, content-free metadata for inference request observations."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

OPERATIONS = frozenset(
    {
        "summary_window",
        "compaction",
        "l3",
        "intention",
        "source_context",
        "policy_compile",
        "policy_assess",
        "alignment",
        "evaluation",
        "judge",
    }
)
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_RATES = (
    "input_cost_per_mtok",
    "output_cost_per_mtok",
    "cache_read_cost_per_mtok",
    "cache_write_cost_per_mtok",
)
_SOURCES = frozenset({"provider", "configured"})


@dataclass(frozen=True)
class InferenceAttribution:
    """Client-supplied observations, never authority or routing inputs."""

    client_operation: str | None = None
    operation_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    client_request_id: str | None = None

    def log_fields(self) -> dict[str, str]:
        """Return only accepted, nonempty fields."""
        return {key: value for key, value in vars(self).items() if value is not None}


def attribution_from_headers(headers: Mapping[str, str]) -> InferenceAttribution:
    """Ignore invalid optional metadata without changing inference behavior."""

    def identifier(suffix: str) -> str | None:
        value = headers.get(f"x-cognis-inference-{suffix}")
        return value if value and _ID.fullmatch(value) else None

    operation = headers.get("x-cognis-inference-operation")
    return InferenceAttribution(
        client_operation=operation if operation in OPERATIONS else None,
        operation_id=identifier("operation-id"),
        session_id=identifier("session-id"),
        task_id=identifier("task-id"),
        client_request_id=identifier("client-request-id"),
    )


def pricing_snapshot(info: Any) -> dict[str, Any] | None:
    """Capture existing resolved prices only; never invent missing prices."""
    metadata = getattr(info, "provider_metadata", None)
    sources = metadata.get("field_sources", {}) if isinstance(metadata, dict) else {}
    if not isinstance(sources, dict):
        sources = {}
    rates = {}
    provenance = {}
    for field in _RATES:
        value = getattr(info, field, None)
        source = sources.get(field)
        if (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
            and isinstance(source, str)
            and (source in _SOURCES or source.startswith("catalog:"))
        ):
            rates[field] = value
            provenance[field] = source
    return {"rates": rates, "sources": provenance} if rates else None


def usage_log_fields(usage: dict[str, Any], tokens: dict[str, int], outcome: str) -> dict[str, Any]:
    """Separate absent provider usage from reported zero and partial usage."""
    fields: dict[str, Any] = {
        "usage_reported": bool(usage),
        "usage_status": ("reported" if outcome == "success" else "partial") if usage else "unknown",
    }
    names = {
        "input": "input_tokens",
        "output": "output_tokens",
        "total": "total_tokens",
        "cached": "cached_input_tokens",
        "cache_write": "cache_write_tokens",
        "cache_creation": "cache_creation_input_tokens",
        "reasoning": "reasoning_tokens",
    }
    for kind, name in names.items():
        fields[name] = tokens[kind] if usage else None
    # Missing primary counts are unknown, even if other usage details were returned.
    for name, aliases in (
        ("input_tokens", ("input_tokens", "prompt_tokens")),
        ("output_tokens", ("output_tokens", "completion_tokens")),
        ("total_tokens", ("total_tokens",)),
    ):
        if not any(type(usage.get(key)) is int and usage[key] >= 0 for key in aliases):
            fields[name] = None
    return fields


def estimated_cost(
    usage: dict[str, Any],
    fields: dict[str, Any],
    pricing: dict[str, Any] | None,
) -> dict[str, Any]:
    """Estimate supported subset accounting; never claim billed USD."""
    result: dict[str, Any] = {
        "estimated_cost_usd": None,
        "cost_status": "unknown",
        "cost_calculation_version": 1,
        "pricing": pricing,
    }
    if pricing is None or fields["usage_status"] != "reported":
        return result
    input_tokens, output_tokens = fields["input_tokens"], fields["output_tokens"]
    if input_tokens is None or output_tokens is None:
        return result
    cached = fields["cached_input_tokens"]
    # Native cache-write/additive-input semantics need a separate billing contract.
    if fields["cache_write_tokens"] or fields["cache_creation_input_tokens"]:
        return result
    if cached and "prompt_tokens" not in usage:
        return result
    if cached > input_tokens:
        return result
    rates = pricing["rates"]
    if not all(key in rates for key in ("input_cost_per_mtok", "output_cost_per_mtok")):
        return result
    if cached and "cache_read_cost_per_mtok" not in rates:
        return result
    cost = (
        (input_tokens - cached) * rates["input_cost_per_mtok"]
        + cached * rates.get("cache_read_cost_per_mtok", 0)
        + output_tokens * rates["output_cost_per_mtok"]
    ) / 1_000_000
    if math.isfinite(cost):
        result.update(estimated_cost_usd=cost, cost_status="estimated")
    return result
