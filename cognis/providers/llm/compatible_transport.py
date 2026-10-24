"""Canonical OpenAI-compatible endpoint and literal model-name handling."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

OPENAI_PRESETS = frozenset({"openai", "openai_compatible", "litellm_proxy", "groq", "openrouter"})


def openai_api_base(url: str) -> str:
    """Accept a service root or its /v1 API base without duplicating the version."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    if not path.endswith("/v1"):
        path += "/v1"
    return urlunsplit(parts._replace(path=path))


def openai_endpoint(url: str, operation: str) -> str:
    """Append an operation to the canonical API path, preserving URL components."""
    parts = urlsplit(openai_api_base(url))
    return urlunsplit(parts._replace(path=f"{parts.path}/{operation.lstrip('/')}"))


def proxy_service_root(url: str) -> str:
    """LiteLLM management endpoints live beside /v1, not beneath it."""
    parts = urlsplit(url.strip())
    return urlunsplit(parts._replace(path=parts.path.rstrip("/").removesuffix("/v1")))


def normalize_compatible_kwargs(
    config: dict[str, Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Use one effective base for inference, discovery and health checks."""
    if config.get("preset") in OPENAI_PRESETS:
        base = kwargs.get("api_base") or kwargs.get("base_url")
        if isinstance(base, str) and base:
            normalized = openai_api_base(base)
            return {**kwargs, "base_url": normalized, "api_base": normalized}
    return kwargs


def compatible_model(model: str, config: dict[str, Any]) -> str | None:
    """Keep the complete model ID advertised by a compatible endpoint.

    The first prefix belongs to LiteLLM; subsequent slashes belong to the
    upstream ID (e.g. openai/gpt-oss-20b or an organization's hosted model).
    Native provider presets keep their existing SDK naming semantics.
    """
    # LiteLLM's proxy adapter implements OpenAI wire pass-through for arbitrary
    # hosted IDs/capabilities, unlike its OpenAI adapter's fixed model catalog.
    # It does not require the upstream server to run LiteLLM.
    prefix = {
        "openai_compatible": "litellm_proxy",
        "litellm_proxy": "litellm_proxy",
        "openrouter": "openrouter",
        "groq": "groq",
    }.get(str(config.get("preset", "")))
    return f"{prefix}/{model}" if prefix else None
