"""Evaluation-only cooldown retries preserve the logical call and fail closed."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from cognis.providers.guardrails.intaris import IntarisProvider
from cognis.providers.guardrails.resolution_errors import ResolutionRejected
from cognis.providers.retry import with_retry


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header", "delay"),
    [("5", 5.0), ("900", 30.0), ("invalid", 0.5), ("-1", 0.5), ("nan", 0.5), ("inf", 0.5)],
)
async def test_retry_after_is_bounded_and_validated(monkeypatch, header, delay):
    sleep = AsyncMock()
    monkeypatch.setattr("cognis.providers.retry.asyncio.sleep", sleep)
    response = httpx.Response(
        503, headers={"Retry-After": header}, request=httpx.Request("POST", "http://test/evaluate")
    )
    action = AsyncMock(
        side_effect=[
            httpx.HTTPStatusError("temporary", request=response.request, response=response),
            "ok",
        ]
    )
    assert (
        await with_retry(
            action, max_retries=1, base_delay=0.5, jitter=False, respect_retry_after=True
        )
        == "ok"
    )
    sleep.assert_awaited_once_with(delay)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [409, 403])
async def test_retry_after_never_retries_policy_or_conflict_errors(monkeypatch, status):
    sleep = AsyncMock()
    monkeypatch.setattr("cognis.providers.retry.asyncio.sleep", sleep)
    response = httpx.Response(
        status, headers={"Retry-After": "5"}, request=httpx.Request("POST", "http://test/evaluate")
    )
    action = AsyncMock(
        side_effect=httpx.HTTPStatusError("blocked", request=response.request, response=response)
    )
    with pytest.raises(httpx.HTTPStatusError):
        await with_retry(action, respect_retry_after=True)
    assert action.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_evaluation_waits_for_cooldown_and_preserves_request(monkeypatch):
    from unittest.mock import Mock

    from cognis.core.workflow_step_scope import WorkflowEvaluationBinding
    from tests.unit.test_workflow_step_scope import declaration

    item = declaration()
    binding = WorkflowEvaluationBinding(
        declaration=item, user_email="owner@test.local", agent_id="agent_scope"
    )
    requests = []
    sleep = AsyncMock()
    monkeypatch.setattr("cognis.providers.retry.asyncio.sleep", sleep)

    def respond(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(
                503,
                headers={"Retry-After": "5"},
                json={"detail": {"code": "evaluation_backend_unavailable"}},
            )
        return httpx.Response(
            200,
            json={
                "decision": "approve",
                "risk": "low",
                "reasoning": "assessed",
                "call_id": "evaluated-call",
            },
        )

    auth = Mock()
    auth.sign_workflow_step_jwt.return_value = "signed-token"
    provider = IntarisProvider("http://intaris.test", auth)
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="http://intaris.test", transport=httpx.MockTransport(respond)
    )
    try:
        result = await provider.evaluate(
            item.session_id, "bash", {"command": "printf %s café"}, workflow_binding=binding
        )
        assert result.decision == "approve"
        assert requests[0] == requests[1]
        assert requests[0]["logical_call_id"] == item.logical_call_id
        sleep.assert_awaited_once_with(5.0)
    finally:
        await provider.client.aclose()


def test_stale_resolution_is_explicit_not_refreshable_or_a_user_refusal():
    error = ResolutionRejected(
        409, {"detail": {"code": "stale_resolution", "message": "private body"}}
    )
    assert error.code == "stale_resolution"
    assert "evaluate the action again" in error.message
    assert "Refreshing this approval won't renew it" in error.message
    assert "private body" not in error.message
    assert not error.permanent
    assert not error.resolved_locally


@pytest.mark.asyncio
async def test_cooldown_retries_remain_bounded_and_opt_in(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("cognis.providers.retry.asyncio.sleep", sleep)
    response = httpx.Response(
        503,
        headers={"Retry-After": "5"},
        request=httpx.Request("POST", "http://test/evaluate"),
    )
    action = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "temporary",
            request=response.request,
            response=response,
        )
    )
    with pytest.raises(httpx.HTTPStatusError):
        await with_retry(
            action, max_retries=2, base_delay=0.5, jitter=False, respect_retry_after=True
        )
    assert action.await_count == 3
    assert [c.args[0] for c in sleep.await_args_list] == [5.0, 5.0]
    sleep.reset_mock()
    action.reset_mock()
    with pytest.raises(httpx.HTTPStatusError):
        await with_retry(action, max_retries=1, base_delay=0.5, jitter=False)
    sleep.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
async def test_cancellation_during_cooldown_does_not_retry(monkeypatch):
    import asyncio

    monkeypatch.setattr(
        "cognis.providers.retry.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)
    )
    response = httpx.Response(
        503,
        headers={"Retry-After": "5"},
        request=httpx.Request("POST", "http://test/evaluate"),
    )
    action = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "temporary",
            request=response.request,
            response=response,
        )
    )
    with pytest.raises(asyncio.CancelledError):
        await with_retry(action, respect_retry_after=True)
    assert action.await_count == 1
