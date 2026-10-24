"""Untrusted provider diagnostics must never become log content."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError

from cognis.providers.llm.inference_errors import safe_inference_error
from tests.unit.test_inference_api import body, companion
from tests.unit.test_inference_api import gateway as _gateway

gateway = _gateway

SENSITIVE = "SECRET-PROMPT-COMPLETION-CREDENTIAL"


def provider_error(payload: object) -> BadRequestError:
    return BadRequestError(
        SENSITIVE,
        response=httpx.Response(
            400, request=httpx.Request("POST", "https://provider.test"), text=SENSITIVE
        ),
        body=payload,
    )


def test_nested_provider_envelope_and_exception_chain() -> None:
    inner = provider_error(
        {"error": {"error": {"code": "json_validate_failed", "message": SENSITIVE}}}
    )
    wrapper = RuntimeError(SENSITIVE)
    wrapper.__cause__ = inner
    result = safe_inference_error(wrapper)
    assert result == {
        "exception_class": "BadRequestError",
        "error_category": "request",
        "upstream_status": 400,
        "upstream_code": "json_validate_failed",
    }
    assert SENSITIVE not in json.dumps(result)


@pytest.mark.parametrize("status", [True, "400", 200, 600, -1, None])
def test_untrusted_status_and_code_are_not_copied(status: object) -> None:
    exc = type(SENSITIVE, (Exception,), {})(SENSITIVE)
    exc.status_code = status
    exc.code = SENSITIVE
    exc.body = {"error": {"code": SENSITIVE, "message": SENSITIVE}}
    result = safe_inference_error(exc)
    assert result == {
        "exception_class": "OtherError",
        "error_category": "unknown",
        "upstream_status": None,
        "upstream_code": None,
    }


def test_cycles_depth_and_suppressed_context() -> None:
    error: dict = {}
    error["error"] = error
    exc = provider_error(error)
    exc.__cause__ = exc
    assert safe_inference_error(exc)["upstream_code"] is None
    wrapper = RuntimeError(SENSITIVE)
    wrapper.__context__ = provider_error({"code": "invalid_json_schema"})
    wrapper.__suppress_context__ = True
    assert safe_inference_error(wrapper)["upstream_status"] is None


def test_response_status_and_fixed_category() -> None:
    exc = TimeoutError(SENSITIVE)
    exc.response = SimpleNamespace(status_code=504)
    assert safe_inference_error(exc)["error_category"] == "timeout"
    assert safe_inference_error(exc)["upstream_status"] == 504


def test_route_logs_only_safe_metadata_and_exposes_request_category(gateway, caplog) -> None:
    client, _, _, _, llm = gateway
    llm.generate.side_effect = provider_error(
        {"error": {"code": "json_validate_failed", "message": SENSITIVE}}
    )
    response = client.post("/v1/chat/completions", headers=companion(gateway), json=body())
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "upstream_json_validate_failed", "category": "request"}
    }
    event = next(r for r in caplog.records if r.message == "inference_provider_error")
    from cognis.logging import JSONFormatter, TextFormatter

    formatted = JSONFormatter().format(event)
    data = json.loads(formatted)
    assert data["request_id"] == response.headers["x-request-id"]
    assert data["exception_class"] == "BadRequestError"
    assert data["upstream_status"] == 400
    assert data["upstream_code"] == "json_validate_failed"
    text = TextFormatter().format(event)
    assert "json_validate_failed" in text
    assert SENSITIVE not in formatted + text
    assert event.exc_info is None
    assert SENSITIVE not in repr(vars(event))
    assert SENSITIVE not in caplog.text + response.text


def test_systemone_route_logs_only_safe_upstream_metadata(gateway, monkeypatch, caplog) -> None:
    from tests.unit.test_inference_api import configure_systemone, typed_body

    configure_systemone(gateway, monkeypatch)
    client, _, _, _, llm = gateway

    async def fail(*args, **kwargs):
        raise provider_error({"error": {"code": "json_validate_failed", "message": SENSITIVE}})

    monkeypatch.setattr(llm, "system_one", fail)
    response = client.post("/v1/systemone", headers=companion(gateway), json=typed_body())
    assert response.status_code == 422
    event = next(r for r in caplog.records if r.message == "inference_provider_error")
    from cognis.logging import JSONFormatter

    data = json.loads(JSONFormatter().format(event))
    assert data["request_id"] == response.headers["x-request-id"]
    assert data["request_id"].startswith("systemone-")
    assert data["operation"] == "systemone"
    assert data["provider_id"] == "typed-inference"
    assert data["model"] == "jev-1.13"
    assert data["upstream_status"] == 400
    assert data["upstream_code"] == "json_validate_failed"
    assert event.exc_info is None
    # No prompt, typed state or response content.
    assert SENSITIVE not in repr(vars(event)) + caplog.text + response.text
    assert "Is it aligned?" not in repr(vars(event))


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (provider_error({"code": "invalid_json_schema"}), 422, "upstream_invalid_json_schema"),
        (provider_error({"code": SENSITIVE}), 422, "upstream_request_error"),
        (TimeoutError(SENSITIVE), 502, "upstream_error"),
        (ConnectionError(SENSITIVE), 502, "upstream_error"),
        (RuntimeError(SENSITIVE), 502, "upstream_error"),
    ],
)
def test_request_errors_are_distinct_from_outages(gateway, error, status, code) -> None:
    client, _, _, _, llm = gateway
    llm.generate.side_effect = error
    response = client.post("/v1/chat/completions", headers=companion(gateway), json=body())
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert SENSITIVE not in response.text


@pytest.mark.parametrize("cached_broken", [False, True])
@pytest.mark.parametrize(
    "response_format",
    [
        {"type": "json_object"},
        {"type": "json_schema", "json_schema": {"name": "result", "schema": {"type": "object"}}},
    ],
)
def test_route_real_provider_preserves_schema_rejection(
    gateway, monkeypatch, cached_broken, response_format, caplog
) -> None:
    from cognis.providers.llm.service import LLMService

    client, _, _, _, llm = gateway
    # Restore the real facade/provider boundary. Only the upstream transport
    # is mocked, not generation, routing, metadata, or error classification.
    llm.generate = LLMService.generate.__get__(llm)
    key = ("shared-inference", "gpt-4o-mini")
    if cached_broken:
        llm._json_response_format_broken_keys.add(key)
    calls = []

    async def reject(**kwargs):
        calls.append(kwargs)
        raise provider_error({"error": {"code": "json_validate_failed", "message": SENSITIVE}})

    monkeypatch.setattr("cognis.providers.llm.litellm.litellm.acompletion", reject)
    response = client.post(
        "/v1/chat/completions",
        headers=companion(gateway),
        json={**body(), "response_format": response_format},
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "upstream_json_validate_failed", "category": "request"}
    }
    assert len(calls) == 1
    assert calls[0]["response_format"] == response_format
    assert "preserve_response_format" not in calls[0]
    assert (key in llm._json_response_format_broken_keys) is cached_broken
    assert SENSITIVE not in response.text + caplog.text
