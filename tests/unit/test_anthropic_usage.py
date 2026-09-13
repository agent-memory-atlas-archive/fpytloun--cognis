from __future__ import annotations

import httpx
import pytest

from cognis.providers.llm import anthropic_usage as subject
from cognis.providers.llm.anthropic_subscription import AnthropicSubscriptionAuth

_OAUTH_USAGE_PAYLOAD = {
    "five_hour": {
        "utilization": 84.0,
        "resets_at": "2026-09-12T11:19:59.982041+00:00",
        "locked_reason": None,
    },
    "seven_day": {
        "utilization": 7.0,
        "resets_at": "2026-09-17T16:59:59.982066+00:00",
        "locked_reason": None,
    },
    "seven_day_opus": None,
    "extra_usage": {
        "is_enabled": False,
        "monthly_limit": None,
        "used_credits": None,
        "user_disabled": True,
    },
    "limits": [
        {
            "kind": "session",
            "group": "session",
            "percent": 84,
            "severity": "warning",
            "resets_at": "2026-09-12T11:19:59.982041+00:00",
            "scope": None,
            "is_active": True,
        },
        {
            "kind": "weekly_all",
            "group": "weekly",
            "percent": 7,
            "severity": "normal",
            "resets_at": "2026-09-17T16:59:59.982066+00:00",
            "scope": None,
            "is_active": False,
        },
        {
            "kind": "weekly_scoped",
            "group": "weekly",
            "percent": 5,
            "severity": "normal",
            "resets_at": "2026-09-17T16:59:59.982327+00:00",
            "scope": {"model": {"id": None, "display_name": "Fable"}},
            "is_active": False,
        },
    ],
}


def test_subscription_usage_payload_normalizes_windows_and_scoped_limits() -> None:
    result = subject.normalize_subscription_usage_payload(_OAUTH_USAGE_PAYLOAD)

    assert result["ok"] is True
    assert result["source"] == "anthropic_subscription_usage"
    assert result["usage_url"] == subject.ANTHROPIC_USAGE_DASHBOARD_URL
    assert result["primary"]["used_percent"] == 84.0
    assert result["primary"]["window_duration_mins"] == 300
    assert result["primary"]["resets_at"] == "2026-09-12T11:19:59.982041+00:00"
    assert result["secondary"]["used_percent"] == 7.0
    assert result["secondary"]["window_duration_mins"] == 10080
    assert result["credits"] is None
    assert result["limit_reached"] is False
    assert result["allowed"] is True
    assert result["additional_rate_limits"] == [
        {
            "limit_id": "weekly_scoped",
            "limit_name": "Fable weekly limit",
            "primary": {
                "used_percent": 5.0,
                "window_duration_mins": 10080,
                "resets_at": "2026-09-17T16:59:59.982327+00:00",
                "reset_after_seconds": None,
            },
            "secondary": None,
            "allowed": None,
            "limit_reached": False,
        }
    ]


def test_subscription_usage_reports_exhausted_and_locked_windows() -> None:
    payload = {
        "five_hour": {"utilization": 100.0, "resets_at": None, "locked_reason": "session_cap"},
        "seven_day": {"utilization": 12.0, "resets_at": None, "locked_reason": None},
        "extra_usage": {"is_enabled": True, "monthly_limit": 50, "used_credits": 12.5},
        "limits": [{"kind": "session", "group": "session", "percent": 100, "scope": None}],
    }

    result = subject.normalize_subscription_usage_payload(payload)

    assert result["limit_reached"] is True
    assert result["allowed"] is False
    assert result["rate_limit_reached_type"] == "session"
    assert result["credits"] == {"has_credits": True, "unlimited": False, "balance": 37.5}
    assert result["additional_rate_limits"] == []


@pytest.mark.asyncio
async def test_fetch_subscription_usage_uses_oauth_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json=_OAUTH_USAGE_PAYLOAD)

    original_client = httpx.AsyncClient

    def client_factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(subject.httpx, "AsyncClient", client_factory)

    result = await subject.fetch_subscription_usage(AnthropicSubscriptionAuth("access-token"))

    assert seen["url"] == subject.ANTHROPIC_OAUTH_USAGE_URL
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer access-token"
    assert "oauth-2025-04-20" in headers["anthropic-beta"]
    assert result["primary"]["used_percent"] == 84.0


def test_rate_limit_snapshot_keeps_only_rate_limit_headers() -> None:
    snapshot = subject.rate_limit_snapshot_from_headers(
        {
            "Content-Type": "application/json",
            "x-api-key": "never",
            "anthropic-ratelimit-requests-limit": "1000",
            "anthropic-ratelimit-requests-remaining": "999",
            "anthropic-ratelimit-requests-reset": "2026-09-12T08:00:30Z",
            "anthropic-ratelimit-input-tokens-limit": "2000000",
            "anthropic-ratelimit-input-tokens-remaining": "1500000",
            "anthropic-ratelimit-input-tokens-reset": "2026-09-12T08:00:45Z",
            "anthropic-ratelimit-output-tokens-limit": "400000",
            "anthropic-ratelimit-output-tokens-remaining": "0",
            "anthropic-ratelimit-output-tokens-reset": "2026-09-12T08:01:00Z",
            "retry-after": "12",
        }
    )

    assert snapshot is not None
    assert "x-api-key" not in snapshot["headers"]
    assert "content-type" not in snapshot["headers"]
    assert snapshot["headers"]["retry-after"] == "12"
    assert subject.rate_limit_snapshot_from_headers({"content-type": "text/plain"}) is None

    usage = subject.rate_limit_usage_from_snapshot(snapshot)

    assert usage["ok"] is True
    assert usage["source"] == "anthropic_rate_limit_headers"
    assert usage["observed_at"] == snapshot["observed_at"]
    assert usage["limit_reached"] is True
    by_id = {limit["limit_id"]: limit for limit in usage["additional_rate_limits"]}
    assert by_id["requests"]["primary"]["used_percent"] == pytest.approx(0.1)
    assert by_id["requests"]["primary"]["resets_at"] == "2026-09-12T08:00:30+00:00"
    assert by_id["input-tokens"]["primary"]["used_percent"] == 25.0
    assert by_id["input-tokens"]["primary"]["remaining"] == 1500000
    assert by_id["output-tokens"]["limit_reached"] is True
    assert "tokens" not in by_id


def test_rate_limit_usage_without_snapshot_reports_no_observations() -> None:
    usage = subject.rate_limit_usage_from_snapshot(None)

    assert usage["ok"] is False
    assert usage["unavailable_reason"] == "no_requests_observed"
    assert usage["additional_rate_limits"] == []
    assert subject.unsupported_usage()["source"] == "unsupported"
