"""Anthropic usage and limit reporting.

Two data sources feed the provider usage panel:

* Claude subscription (OAuth) providers expose rolling five-hour and seven-day
  utilization through the OAuth usage endpoint, the same source Claude Code
  reads for its ``/usage`` view.
* Every native Messages response carries ``anthropic-ratelimit-*`` headers.
  The controller keeps the latest snapshot per provider so API-key providers,
  which have no usage endpoint, still report remaining per-minute capacity.

Both are normalized into the same window shape the Codex usage panel renders.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from cognis.providers.llm.anthropic_subscription import (
    AnthropicSubscriptionAuth,
    oauth_request_headers,
)

ANTHROPIC_OAUTH_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
ANTHROPIC_USAGE_DASHBOARD_URL = "https://claude.ai/settings/usage"
ANTHROPIC_CONSOLE_LIMITS_URL = "https://platform.claude.com/settings/limits"
SUBSCRIPTION_USAGE_SOURCE = "anthropic_subscription_usage"
RATE_LIMIT_HEADERS_SOURCE = "anthropic_rate_limit_headers"
UNSUPPORTED_USAGE_SOURCE = "unsupported"
_RATE_LIMIT_HEADER_PREFIXES = ("anthropic-ratelimit-", "anthropic-priority-", "anthropic-fast-")
_RATE_LIMIT_BUCKETS: tuple[tuple[str, str], ...] = (
    ("requests", "Requests per minute"),
    ("input-tokens", "Input tokens per minute"),
    ("output-tokens", "Output tokens per minute"),
    ("tokens", "Tokens per minute"),
)
_FIVE_HOURS_MINS = 5 * 60
_SEVEN_DAYS_MINS = 7 * 24 * 60


async def fetch_subscription_usage(
    auth: AnthropicSubscriptionAuth, *, timeout: float = 15.0
) -> dict[str, Any]:
    """Fetch rolling utilization windows for a Claude subscription token."""

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            ANTHROPIC_OAUTH_USAGE_URL, headers=oauth_request_headers(auth.access_token)
        )
        response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Claude subscription usage response was not an object")
    return normalize_subscription_usage_payload(payload)


def normalize_subscription_usage_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the OAuth usage payload into the shared provider usage shape."""

    primary = _subscription_window(payload.get("five_hour"), _FIVE_HOURS_MINS)
    secondary = _subscription_window(payload.get("seven_day"), _SEVEN_DAYS_MINS)
    additional: list[dict[str, Any]] = []
    reached_type: str | None = None
    limit_reached = False
    raw_limits = payload.get("limits")
    for item in raw_limits if isinstance(raw_limits, list) else []:
        if not isinstance(item, Mapping):
            continue
        percent = _float_or_none(item.get("percent"))
        kind = str(item.get("kind") or "")
        if percent is not None and percent >= 100:
            limit_reached = True
            reached_type = reached_type or kind or None
        scope = item.get("scope")
        if not isinstance(scope, Mapping):
            continue
        model = scope.get("model")
        model_name = (
            str(model.get("display_name") or model.get("id") or "")
            if isinstance(model, Mapping)
            else ""
        )
        additional.append(
            {
                "limit_id": kind or None,
                "limit_name": f"{model_name} weekly limit" if model_name else kind or None,
                "primary": {
                    "used_percent": percent if percent is not None else 0.0,
                    "window_duration_mins": (
                        _SEVEN_DAYS_MINS if str(item.get("group") or "") == "weekly" else None
                    ),
                    "resets_at": _iso_or_none(item.get("resets_at")),
                    "reset_after_seconds": None,
                },
                "secondary": None,
                "allowed": None,
                "limit_reached": bool(percent is not None and percent >= 100),
            }
        )
    for window in (primary, secondary):
        if window is not None and window["used_percent"] >= 100:
            limit_reached = True
    for key in ("five_hour", "seven_day"):
        raw = payload.get(key)
        if isinstance(raw, Mapping) and raw.get("locked_reason"):
            limit_reached = True
            reached_type = reached_type or str(raw["locked_reason"])
    return {
        "ok": True,
        "source": SUBSCRIPTION_USAGE_SOURCE,
        "usage_url": ANTHROPIC_USAGE_DASHBOARD_URL,
        "fetched_at": datetime.now(UTC).isoformat(),
        "plan_type": None,
        "primary": primary,
        "secondary": secondary,
        "credits": _extra_usage_credits(payload.get("extra_usage")),
        "rate_limit_reached_type": reached_type,
        "allowed": not limit_reached,
        "limit_reached": limit_reached,
        "additional_rate_limits": additional,
    }


def rate_limit_snapshot_from_headers(headers: Mapping[str, Any]) -> dict[str, Any] | None:
    """Keep only rate-limit headers from one Messages response, with a timestamp."""

    kept: dict[str, str] = {}
    for key, value in headers.items():
        lowered = str(key).lower()
        if lowered == "retry-after" or lowered.startswith(_RATE_LIMIT_HEADER_PREFIXES):
            kept[lowered] = str(value)
    if not kept:
        return None
    return {"observed_at": datetime.now(UTC).isoformat(), "headers": kept}


def rate_limit_usage_from_snapshot(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Render the latest header snapshot as provider usage windows."""

    headers = snapshot.get("headers") if isinstance(snapshot, Mapping) else None
    headers = dict(headers) if isinstance(headers, Mapping) else {}
    observed_at = snapshot.get("observed_at") if isinstance(snapshot, Mapping) else None
    additional: list[dict[str, Any]] = []
    limit_reached = False
    for bucket, label in _RATE_LIMIT_BUCKETS:
        limit = _float_or_none(headers.get(f"anthropic-ratelimit-{bucket}-limit"))
        remaining = _float_or_none(headers.get(f"anthropic-ratelimit-{bucket}-remaining"))
        if limit is None or limit <= 0 or remaining is None:
            continue
        used_percent = max(0.0, min(100.0, (limit - remaining) / limit * 100.0))
        if remaining <= 0:
            limit_reached = True
        additional.append(
            {
                "limit_id": bucket,
                "limit_name": label,
                "primary": {
                    "used_percent": used_percent,
                    "window_duration_mins": 1,
                    "resets_at": _iso_or_none(headers.get(f"anthropic-ratelimit-{bucket}-reset")),
                    "reset_after_seconds": None,
                    "limit": int(limit),
                    "remaining": int(remaining),
                },
                "secondary": None,
                "allowed": remaining > 0,
                "limit_reached": remaining <= 0,
            }
        )
    return {
        "ok": bool(headers),
        "source": RATE_LIMIT_HEADERS_SOURCE,
        "usage_url": ANTHROPIC_CONSOLE_LIMITS_URL,
        "fetched_at": observed_at if isinstance(observed_at, str) else None,
        "observed_at": observed_at if isinstance(observed_at, str) else None,
        "plan_type": None,
        "primary": None,
        "secondary": None,
        "credits": None,
        "rate_limit_reached_type": "rate_limit" if limit_reached else None,
        "allowed": not limit_reached,
        "limit_reached": limit_reached,
        "additional_rate_limits": additional,
        "rate_limit_headers": headers or None,
        "unavailable_reason": None if headers else "no_requests_observed",
    }


def unsupported_usage(reason: str = "unsupported_provider") -> dict[str, Any]:
    """Return the shape reported for providers without usage reporting."""

    return {
        "ok": False,
        "source": UNSUPPORTED_USAGE_SOURCE,
        "usage_url": None,
        "fetched_at": None,
        "plan_type": None,
        "primary": None,
        "secondary": None,
        "credits": None,
        "rate_limit_reached_type": None,
        "allowed": None,
        "limit_reached": None,
        "additional_rate_limits": [],
        "unavailable_reason": reason,
    }


def _subscription_window(raw: Any, duration_mins: int) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    utilization = _float_or_none(raw.get("utilization"))
    resets_at = _iso_or_none(raw.get("resets_at"))
    return {
        "used_percent": utilization if utilization is not None else 0.0,
        "window_duration_mins": duration_mins,
        "resets_at": resets_at,
        "reset_after_seconds": _seconds_until(resets_at),
    }


def _extra_usage_credits(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping) or raw.get("is_enabled") is not True:
        return None
    limit = _float_or_none(raw.get("monthly_limit"))
    used = _float_or_none(raw.get("used_credits"))
    balance: float | None = None
    if limit is not None and used is not None:
        balance = max(0.0, limit - used)
    return {
        "has_credits": bool(balance is None or balance > 0),
        "unlimited": False,
        "balance": balance,
    }


def _seconds_until(resets_at: str | None) -> int | None:
    if not resets_at:
        return None
    try:
        target = datetime.fromisoformat(resets_at)
    except ValueError:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    remaining = int((target - datetime.now(UTC)).total_seconds())
    return remaining if remaining > 0 else None


def _iso_or_none(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
