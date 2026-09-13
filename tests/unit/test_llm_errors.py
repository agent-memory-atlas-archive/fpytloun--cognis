from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx

from cognis.providers.llm.anthropic_subscription import AnthropicSubscriptionError
from cognis.providers.llm.errors import (
    MidStreamErrorCategory,
    classify_llm_exception,
    classify_response_failure,
    is_deterministic_client_error_status,
    retry_after_seconds_from_headers,
)


def test_classify_anthropic_subscription_rate_limit_preserves_retry_after_header() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        429,
        headers={"Retry-After": "23"},
        json={"error": {"type": "rate_limit_error", "message": "slow down"}},
        request=request,
    )
    exc = AnthropicSubscriptionError(
        429,
        response.text,
        response=response,
        body=response.json(),
    )

    payload = classify_llm_exception(exc)

    assert payload["category"] == MidStreamErrorCategory.RATE_LIMIT.value
    assert payload["code"] == "rate_limit_error"
    assert payload["retry_after_seconds"] == 23


def test_retry_after_parser_accepts_http_date() -> None:
    retry_at = datetime.now(UTC) + timedelta(seconds=90)
    seconds = retry_after_seconds_from_headers(
        {"Retry-After": format_datetime(retry_at, usegmt=True)}
    )

    assert seconds is not None
    assert 0 < seconds <= 90


def test_retry_after_parser_rejects_non_finite_values() -> None:
    assert retry_after_seconds_from_headers({"Retry-After": "Infinity"}) is None
    assert retry_after_seconds_from_headers({"Retry-After": "NaN"}) is None


def test_deterministic_client_error_statuses_exclude_recoverable_ones() -> None:
    for status in (400, 401, 403, 404, 413, 415, 422):
        assert is_deterministic_client_error_status(status), status
    # These can clear without changing the request, so they keep their previous
    # classification and stay eligible for recovery.
    for status in (408, 409, 423, 425, 429, 500, 503):
        assert not is_deterministic_client_error_status(status), status
    assert not is_deterministic_client_error_status(None)
    assert not is_deterministic_client_error_status(True)
    assert not is_deterministic_client_error_status("400")


def test_classify_unsupported_model_rejection_is_invalid_request() -> None:
    # Regression: this 400 classified as "other" and was retried four times per
    # turn across three automatically continued turns.
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        400,
        json={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": (
                    "Claude Code 2.1.87 does not support this model; "
                    "version 2.1.251 or newer is required."
                ),
            },
        },
        request=request,
    )
    exc = AnthropicSubscriptionError(
        400,
        response.text,
        response=response,
        body=response.json(),
    )

    assert classify_llm_exception(exc)["category"] == MidStreamErrorCategory.INVALID_REQUEST.value


def test_deterministic_status_outranks_server_error_wording() -> None:
    payload = classify_response_failure(
        {
            "status_code": 400,
            "message": "internal_error while validating the request",
        }
    )

    assert payload["category"] == MidStreamErrorCategory.INVALID_REQUEST.value


def test_context_overflow_keeps_its_category_on_a_deterministic_status() -> None:
    payload = classify_response_failure(
        {
            "status_code": 400,
            "message": "prompt is too long for the model context window",
        }
    )

    assert payload["category"] == MidStreamErrorCategory.CONTEXT_OVERFLOW.value
