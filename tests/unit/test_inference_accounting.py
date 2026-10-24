"""Accounting observes requests without changing their dispatch contract."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import Headers

from cognis.logging import JSONFormatter
from cognis.providers.llm.inference_accounting import (
    attribution_from_headers,
    estimated_cost,
    pricing_snapshot,
    usage_log_fields,
)
from cognis.providers.llm.inference_api import (
    INFERENCE_REQUESTS,
    InferenceAPIService,
    InferencePrincipal,
    InferenceTarget,
)
from cognis.providers.llm.litellm import llm_token_values
from tests.unit import test_inference_api
from tests.unit.test_inference_api import body, companion

gateway = test_inference_api.gateway


def prices():
    return pricing_snapshot(
        SimpleNamespace(
            input_cost_per_mtok=2.0,
            output_cost_per_mtok=8.0,
            cache_read_cost_per_mtok=0.5,
            provider_metadata={
                "field_sources": {
                    "input_cost_per_mtok": "configured",
                    "output_cost_per_mtok": "catalog:groq",
                    "cache_read_cost_per_mtok": "provider",
                }
            },
        )
    )


def test_counts_and_estimates_do_not_double_count_subsets():
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "prompt_tokens_details": {"cached_tokens": 40},
        "completion_tokens_details": {"reasoning_tokens": 15},
    }
    fields = usage_log_fields(usage, llm_token_values(usage), "success")
    assert fields["input_tokens"] == 100
    assert fields["output_tokens"] == 20
    assert fields["reasoning_tokens"] == 15
    cost = estimated_cost(usage, fields, prices())
    assert cost["estimated_cost_usd"] == pytest.approx((60 * 2 + 40 * 0.5 + 20 * 8) / 1e6)
    assert cost["pricing"]["sources"]["input_cost_per_mtok"] == "configured"


@pytest.mark.parametrize(
    "usage,outcome",
    [
        ({}, "error"),
        ({}, "success"),
        ({"total_tokens": 0}, "success"),
        ({"prompt_tokens": 100, "completion_tokens": 20}, "cancelled"),
        ({"prompt_tokens": 100, "completion_tokens": 20, "cached_tokens": 101}, "success"),
        ({"input_tokens": 100, "output_tokens": 20, "cached_tokens": 40}, "success"),
        ({"prompt_tokens": 100, "completion_tokens": 20, "cache_write_tokens": 10}, "success"),
    ],
)
def test_unknown_and_unsupported_usage_is_not_free(usage, outcome):
    fields = usage_log_fields(usage, llm_token_values(usage), outcome)
    assert estimated_cost(usage, fields, prices())["estimated_cost_usd"] is None
    if not usage:
        assert fields["output_tokens"] is None
        assert fields["usage_status"] == "unknown"


def test_known_zero_and_missing_prices_are_distinct():
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    fields = usage_log_fields(usage, llm_token_values(usage), "success")
    assert estimated_cost(usage, fields, prices())["estimated_cost_usd"] == 0
    assert estimated_cost(usage, fields, None)["estimated_cost_usd"] is None
    assert pricing_snapshot(SimpleNamespace()) is None


@pytest.mark.parametrize("rate", [-1, float("nan"), float("inf"), None])
def test_invalid_prices_are_unknown(rate):
    info = SimpleNamespace(
        input_cost_per_mtok=rate,
        provider_metadata={"field_sources": {"input_cost_per_mtok": "configured"}},
    )
    assert pricing_snapshot(info) is None


@pytest.mark.parametrize("source", [None, "untrusted", 1])
def test_unknown_pricing_provenance_is_not_used(source):
    info = SimpleNamespace(
        input_cost_per_mtok=2,
        provider_metadata={"field_sources": {"input_cost_per_mtok": source}},
    )
    assert pricing_snapshot(info) is None


def test_cache_discount_requires_a_known_price():
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "cached_tokens": 40}
    fields = usage_log_fields(usage, llm_token_values(usage), "success")
    snapshot = prices()
    del snapshot["rates"]["cache_read_cost_per_mtok"]
    assert estimated_cost(usage, fields, snapshot)["estimated_cost_usd"] is None


def test_invalid_metadata_ignored_without_logging_values():
    attribution = attribution_from_headers(
        Headers(
            {
                "X-Cognis-Inference-Operation": "private payload",
                "X-Cognis-Inference-Operation-ID": "operation-1",
                "X-Cognis-Inference-Session-ID": "private\npayload",
                "X-Cognis-Inference-Task-ID": "x" * 129,
                "X-Cognis-Inference-Unrecognized": "private payload",
            }
        )
    )
    assert attribution.log_fields() == {"operation_id": "operation-1"}


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("attributed", [False, True])
def test_chat_attribution_only_changes_logs(gateway, caplog, monkeypatch, streaming, attributed):
    client, _, _, _, llm = gateway
    caplog.set_level(logging.INFO, logger="cognis.providers.llm.inference_api")
    captured = []

    async def stream(*args, **kwargs):
        captured.append(kwargs)
        yield {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20}}

    monkeypatch.setattr(llm, "stream_generate", stream)
    headers = companion(gateway)
    if attributed:
        headers.update(
            {
                "X-Cognis-Inference-Operation": "summary_window",
                "X-Cognis-Inference-Operation-ID": "operation-123",
                "X-Cognis-Inference-Session-ID": "session-123",
                "X-Cognis-Inference-Task-ID": "task-123",
                "X-Cognis-Inference-Client-Request-ID": "request-123",
            }
        )
    response = client.post("/v1/chat/completions", headers=headers, json=body(stream=streaming))
    assert response.status_code == 200
    record = next(r for r in caplog.records if r.message == "inference_request")
    event = json.loads(JSONFormatter().format(record))
    assert event["output_tokens"] == (20 if streaming else 3)
    assert event["attempt_accounting"] == "incomplete"
    assert event["request_id"] == response.headers["x-request-id"]
    assert event["llm_request_id"] == event["request_id"]
    assert event.get("client_operation") == ("summary_window" if attributed else None)
    kwargs = captured[0] if streaming else llm.generate.call_args.kwargs
    assert kwargs["cognis_llm_request_id"] == event["request_id"]
    assert not {"attribution", "operation_id", "session_id", "extra_headers"}.intersection(kwargs)
    assert not any(value == "operation-123" for value in kwargs.values())
    assert "output" not in event


def test_failure_logs_unknown_not_zero_and_preserves_correlation(gateway, caplog):
    client, _, _, _, llm = gateway
    llm.generate = AsyncMock(side_effect=TimeoutError("private provider payload"))
    caplog.set_level(logging.INFO, logger="cognis.providers.llm.inference_api")
    headers = {**companion(gateway), "X-Cognis-Inference-Operation-ID": "operation-123"}
    response = client.post("/v1/chat/completions", headers=headers, json=body())
    assert response.status_code == 502
    event = next(r.extra_data for r in caplog.records if r.message == "inference_request")
    assert event["usage_status"] == "unknown"
    assert event["output_tokens"] is None
    assert event["estimated_cost_usd"] is None
    assert event["operation_id"] == "operation-123"
    assert "private provider payload" not in json.dumps(event)


@pytest.mark.parametrize("operation", ["systemone", "embeddings"])
def test_other_transports_do_not_forward_attribution(gateway, caplog, monkeypatch, operation):
    client, app, _, _, llm = gateway
    caplog.set_level(logging.INFO, logger="cognis.providers.llm.inference_api")
    target = InferenceTarget(
        "routes/intaris_evaluation" if operation == "systemone" else "routes/intaris_embedding",
        "model",
        "shared-inference",
        "owner",
    )
    monkeypatch.setattr(app.state.inference_api, "resolve", AsyncMock(return_value=target))
    llm.system_one = AsyncMock(
        return_value={
            "model": "model",
            "answers": {},
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }
    )
    headers = {
        **companion(gateway),
        "X-Cognis-Inference-Operation": "evaluation",
        "X-Cognis-Inference-Operation-ID": "operation-123",
    }
    payload = (
        {
            "model": target.requested,
            "state": {},
            "questions": {"aligned": {"type": "noul", "instructions": "Check"}},
        }
        if operation == "systemone"
        else {"model": target.requested, "input": "private text"}
    )
    response = client.post(f"/v1/{operation}", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    event = next(r.extra_data for r in caplog.records if r.message == "inference_request")
    assert event["operation_id"] == "operation-123"
    assert event["client_operation"] == "evaluation"
    call = llm.system_one if operation == "systemone" else llm.embed_response
    assert not {"attribution", "operation_id", "extra_headers"}.intersection(call.call_args.kwargs)
    assert "operation-123" not in repr(call.call_args)


def test_log_redaction_remains_content_safe():
    record = logging.LogRecord("accounting", logging.INFO, "", 1, "inference_request", (), None)
    record.extra_data = {
        "output_tokens": 20,
        "output": "private completion",
        "messages": ["private prompt"],
    }
    event = json.loads(JSONFormatter().format(record))
    assert event["output_tokens"] == 20
    assert event["output"] == "[REDACTED]"
    assert "private" not in json.dumps(event)


@pytest.mark.parametrize(
    "reference,route",
    [
        ("routes/intaris_analysis", "intaris_analysis"),
        ("cognis/arbitrary-name", "named"),
        ("providers/arbitrary-provider/arbitrary-model", "direct"),
        ("routes/not-registered", "direct"),
    ],
)
def test_route_metric_cardinality_and_fallback_pricing(reference, route, caplog):
    caplog.set_level(logging.INFO, logger="cognis.providers.llm.inference_api")
    service = InferenceAPIService(None, None)
    principal = InferencePrincipal("owner", "intaris", "inference_companion")
    target = InferenceTarget(
        reference,
        "model",
        "provider",
        "owner",
        pricing=prices(),
        pricing_target=("provider", "model"),
    )
    usage = {"prompt_tokens": 100, "completion_tokens": 20}
    service.observe(principal, target, "chat", "request-1", monotonic(), "success", usage)
    event = caplog.records[-1].extra_data
    assert event["requested_route"] == route
    assert event["estimated_cost_usd"] is not None
    assert not {"operation_id", "session_id", "task_id", "request_id"}.intersection(
        INFERENCE_REQUESTS._labelnames
    )
    service.observe(
        principal,
        replace(target, model="fallback"),
        "chat",
        "request-2",
        monotonic(),
        "success",
        usage,
    )
    assert caplog.records[-1].extra_data["estimated_cost_usd"] is None
