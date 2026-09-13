"""Fast-mode capability and request policy, independent of account eligibility."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from cognis.models.config import ModelInfo

ANTHROPIC_FAST_BETA = "fast-mode-2026-02-01"


def enrich_fast_mode(
    entry: dict[str, Any], preset: str, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Expose executable fast-mode capabilities; preserve explicit restrictions."""
    result = dict(entry)
    model = str(entry.get("model_id", "")).removeprefix("anthropic/")
    config = config or {}
    endpoint = config.get("api_base") or config.get("base_url") or "https://api.anthropic.com"
    native_claude = (
        preset == "anthropic"
        and urlsplit(str(endpoint)).hostname == "api.anthropic.com"
        and config.get("protocol", "auto") != "litellm"
        and model in {"claude-opus-5", "claude-opus-4-8"}
    )
    if native_claude and entry.get("supports_fast_mode") is not False:
        result.update(supports_fast_mode=True, fast_mode_parameter="speed", fast_mode_tier="fast")
    elif preset == "anthropic":
        result.update(supports_fast_mode=False, fast_mode_parameter=None, fast_mode_tier=None)
    elif entry.get("supports_fast_mode") and entry.get("fast_mode_tier"):
        result["fast_mode_parameter"] = "service_tier"
    else:
        result.update(supports_fast_mode=False, fast_mode_parameter=None, fast_mode_tier=None)
    return result


def prepare_fast_mode(
    request: dict[str, Any], info: ModelInfo, *, unavailable: bool = False
) -> dict[str, Any]:
    """Translate tri-state selection without leaving inherited acceleration active."""
    result = dict(request)
    selected = result.pop("fast_mode", None)
    if selected is None:
        return result
    if not isinstance(selected, bool):
        raise ValueError("fast_mode must be a boolean or null")
    result.pop("service_tier", None)
    result.pop("speed", None)
    extra_body = result.get("extra_body")
    if isinstance(extra_body, dict):
        result["extra_body"] = {
            key: value for key, value in extra_body.items() if key not in {"speed", "service_tier"}
        }
    if isinstance(result.get("extra_headers"), dict):
        headers = dict(result["extra_headers"])
        for key in list(headers):
            if key.lower() == "anthropic-beta":
                tokens = [token.strip() for token in str(headers[key]).split(",")]
                remaining = [token for token in tokens if token and token != ANTHROPIC_FAST_BETA]
                if remaining:
                    headers[key] = ",".join(remaining)
                else:
                    del headers[key]
        result["extra_headers"] = headers
    if not selected or unavailable:
        return result
    if not info.supports_fast_mode or not info.fast_mode_tier:
        raise ValueError(f"Fast mode is unsupported for {info.model_id!r}")
    parameter = info.fast_mode_parameter or "service_tier"
    result[parameter] = info.fast_mode_tier
    if parameter == "speed":
        headers = dict(result.get("extra_headers") or {})
        betas = [str(headers.pop(key)) for key in list(headers) if key.lower() == "anthropic-beta"]
        headers["anthropic-beta"] = ",".join(
            dict.fromkeys(
                token.strip()
                for token in ",".join([*betas, ANTHROPIC_FAST_BETA]).split(",")
                if token.strip()
            )
        )
        result["extra_headers"] = headers
    return result
