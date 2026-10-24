"""Admission conflicts stay fail-closed and model-visible through real routing."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from cognis.core.agent_loop import AgentLoop, PauseResolution
from cognis.core.tool_router import ToolRouter
from cognis.models.tool import Permission, ToolCall
from cognis.providers.guardrails.conflicts import EvaluationConflict
from cognis.providers.guardrails.intaris import IntarisProvider
from tests.unit.test_tool_router import (
    MANAGE_AGENTS_TOOL,
    RegisteredTool,
    ToolRegistry,
    _agent,
    _Executor,
    _readonly_registry,
    _session,
)


@pytest_asyncio.fixture
async def transport() -> AsyncIterator[tuple[IntarisProvider, list[dict], list[httpx.Response]]]:
    requests: list[dict] = []
    responses: list[httpx.Response] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/evaluate"
        requests.append(json.loads(request.content))
        return responses.pop(0)

    provider = IntarisProvider(
        "http://intaris.test",
        SimpleNamespace(sign_service_jwt=lambda *args, **kwargs: "signed-token"),
    )
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="http://intaris.test", transport=httpx.MockTransport(respond)
    )
    try:
        yield provider, requests, responses
    finally:
        await provider.client.aclose()


def _conflict(code: str) -> httpx.Response:
    return httpx.Response(409, json={"detail": {"code": code, "message": "Admission changed"}})


def _evaluation(decision: str, call_id: str = "evaluation-new") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "decision": decision,
            "call_id": call_id,
            "minimum_outcome": "escalate",
        },
    )


def _call() -> ToolCall:
    return ToolCall(
        name="read",
        call_id="controller-call",
        arguments={"path": "/tmp/README.md"},
        runtime_metadata={"approval_call_id": "approved-original"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("detail", "code", "message"),
    [
        (
            {"code": "stale_admission", "message": "Session changed"},
            "stale_admission",
            "Session changed",
        ),
        ("Legacy conflict", "evaluation_conflict", "Legacy conflict"),
        ({"code": "raw secret text", "message": "Changed"}, "evaluation_conflict", "Changed"),
        (None, "evaluation_conflict", "Intaris could not admit this tool call."),
    ],
)
async def test_provider_maps_409_without_retry_or_content_logging(
    transport: tuple, caplog: pytest.LogCaptureFixture, detail: object, code: str, message: str
) -> None:
    provider, requests, responses = transport
    responses.append(httpx.Response(409, json={"detail": detail}))
    with pytest.raises(EvaluationConflict) as raised:
        await provider.evaluate(
            "session-a",
            "read",
            {"secret": "do-not-log"},
            context={"tool_call_id": "controller-call"},
        )
    assert raised.value.code == code
    assert raised.value.message == message
    assert len(requests) == 1
    record = next(r for r in caplog.records if r.message == "intaris: evaluate conflict")
    assert record.extra_data == {
        "code": code,
        "status_code": 409,
        "session_id": "session-a",
        "tool_name": "read",
        "call_id": "controller-call",
    }
    assert "do-not-log" not in caplog.text
    assert message not in caplog.text


@pytest.mark.asyncio
async def test_malformed_409_does_not_poison_evaluation_breaker(transport: tuple) -> None:
    provider, requests, responses = transport
    responses.extend(httpx.Response(409, text="private non-JSON body") for _ in range(6))
    for _ in range(6):
        with pytest.raises(EvaluationConflict, match="evaluation_conflict"):
            await provider.evaluate("session-a", "read", {})
    responses.append(_evaluation("approve"))
    assert (await provider.evaluate("session-a", "read", {})).decision == "approve"
    assert len(requests) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["stale_admission", "stale_task_context", "expired_admission"])
@pytest.mark.parametrize("succeeds", [True, False])
async def test_router_re_evaluates_once_preserving_exact_receipt(
    transport: tuple, code: str, succeeds: bool
) -> None:
    provider, requests, responses = transport
    responses.extend([_conflict(code), _evaluation("approve") if succeeds else _conflict(code)])
    executor = _Executor()
    result = await ToolRouter(guardrails=provider).execute(
        _call(),
        _session(),
        _agent({"*": Permission.EVALUATE}),
        _readonly_registry("read"),
        executor,
    )
    assert result.is_error is not succeeds
    assert executor.calls == int(succeeds)
    assert len(requests) == 2
    assert requests[0] == requests[1]
    assert requests[0]["approval_call_id"] == "approved-original"
    assert requests[0]["args"] == _call().arguments
    if not succeeds:
        assert code in result.output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    [
        "mandatory_denial",
        "duplicate_admission",
        "human_approval_required",
        "read_only_ceiling",
        "stale_policy_revision",
        "stale_policy_hash",
        "policy_version_mismatch",
        "alignment_not_ready",
        "logical_call_conflict",
        "invalid_active_policy",
        "future_unknown_code",
    ],
)
async def test_router_returns_error_without_execution_or_retry(transport: tuple, code: str) -> None:
    provider, requests, responses = transport
    responses.append(_conflict(code))
    executor = _Executor()
    result = await ToolRouter(guardrails=provider).execute(
        _call(),
        _session(),
        _agent({"*": Permission.EVALUATE}),
        _readonly_registry("read"),
        executor,
    )
    assert result.is_error
    assert code in result.output
    assert result.metadata["evaluation"]["decision"] == "deny"
    assert result.metadata["evaluation"]["conflict_code"] == code
    assert executor.calls == 0
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["non_bypassable", "self_mutation"])
async def test_other_evaluation_branches_contain_conflicts(transport: tuple, route: str) -> None:
    provider, requests, responses = transport
    responses.append(_conflict("mandatory_denial"))
    agent = _agent({"*": Permission.EVALUATE})
    call = _call()
    registry = _readonly_registry("read")
    if route == "self_mutation":
        agent.tools = {"opt_in_builtin_tools": ["manage_agents"]}
        registry = ToolRegistry()
        registry.register(RegisteredTool(definition=MANAGE_AGENTS_TOOL))
        call = ToolCall(
            name="manage_agents",
            call_id="self-mutation-call",
            arguments={"action": "update", "agent_id": agent.agent_id, "name": "Changed"},
        )
    executor = _Executor()
    result = await ToolRouter(guardrails=provider, non_bypassable_patterns=["read"]).execute(
        call, _session(), agent, registry, executor
    )
    assert result.is_error
    assert result.metadata["evaluation"]["conflict_code"] == "mandatory_denial"
    assert executor.calls == 0
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh_decision", ["escalate", "approve", "deny", "conflict"])
async def test_stale_approval_requests_new_escalation_not_old_receipt_retry(
    transport: tuple, fresh_decision: str
) -> None:
    provider, requests, responses = transport
    responses.extend(
        [
            _conflict("stale_approval"),
            _conflict("stale_approval")
            if fresh_decision == "conflict"
            else _evaluation(fresh_decision),
        ]
    )
    executor = _Executor()
    result = await ToolRouter(guardrails=provider).execute(
        _call(),
        _session(),
        _agent({"*": Permission.EVALUATE}),
        _readonly_registry("read"),
        executor,
    )
    assert result.is_error
    assert "approval no longer matches this action or its authorization state" in result.output
    assert result.metadata["evaluation"]["decision"] == (
        "escalate" if fresh_decision == "escalate" else "deny"
    )
    assert executor.calls == 0
    assert len(requests) == 2
    assert "approval_call_id" not in requests[1]
    assert requests[1]["minimum_outcome"] == "escalate"
    assert requests[0]["args"] == requests[1]["args"]


@pytest.mark.asyncio
@pytest.mark.parametrize("changes_again", [False, True])
async def test_agent_loop_post_approval_conflict_allows_fresh_approval_once(
    transport: tuple, changes_again: bool
) -> None:
    provider, requests, responses = transport
    responses.extend(
        [
            _evaluation("escalate", "evaluation-original"),
            _conflict("stale_approval"),
            _evaluation("escalate", "evaluation-fresh"),
        ]
    )
    responses.extend(
        [_conflict("stale_approval"), _evaluation("escalate", "evaluation-later")]
        if changes_again
        else [_evaluation("approve", "evaluation-final")]
    )
    router = ToolRouter(guardrails=provider)
    executor = _Executor()
    registry = _readonly_registry("read")
    agent = _agent({"*": Permission.EVALUATE})
    agent.capabilities.escalation_timeout_seconds = 30
    from cognis.core.agent_loop import StepContext
    from cognis.models.workflow import StepDefinition

    ctx = StepContext(
        step_definition=StepDefinition(name="review", type="run"),
        interaction_mode="explicit_gates",
        task_id=None,
        agent=agent,
        session=_session(),
        conversation=SimpleNamespace(conversation_id="conversation-a", context=None),
        tool_registry=registry,
        executor_connection=executor,
    )
    loop = object.__new__(AgentLoop)
    loop.session_manager = SimpleNamespace(session_factory=lambda: AsyncMock())
    loop.notification_service = SimpleNamespace(create=AsyncMock())
    loop.event_bus = SimpleNamespace(publish=AsyncMock())
    loop.tool_router = router
    loop._wait_for_escalation_resolution = AsyncMock(
        return_value=PauseResolution(decision="approve")
    )
    loop._get_tool_registry = lambda ctx: registry
    loop._get_classified_tool_registry = lambda ctx, registry: registry
    loop._get_executor = lambda ctx: executor
    loop._tool_runtime_metadata_for_call = lambda ctx, tc: {}
    loop._sync_guardrails_terminal_result = AsyncMock()
    loop._stale_session_step_output = AsyncMock(return_value=None)
    loop._record_execution_evidence = lambda *args, **kwargs: None
    call = _call().model_copy(update={"runtime_metadata": {}})
    initial = await router.execute(call, ctx.session, agent, registry, executor)
    call = call.model_copy(update={"arguments": {**call.arguments, "target_executor": ""}})
    result = await loop._handle_escalation(initial, call, ctx, [], None)
    assert result.is_error is changes_again
    assert executor.calls == int(not changes_again)
    notifications = loop.notification_service.create.await_args_list
    assert [n.kwargs["notification_id"] for n in notifications] == [
        "evaluation-original",
        "evaluation-fresh",
    ]
    assert "approval no longer matches" in notifications[1].kwargs["payload"]["reasoning"]
    assert requests[1]["approval_call_id"] == "evaluation-original"
    assert "approval_call_id" not in requests[2]
    assert requests[3]["approval_call_id"] == "evaluation-fresh"
    expected_args = {k: v for k, v in call.arguments.items() if k != "target_executor"}
    assert all(request["args"] == expected_args for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["stale_admission", "stale_task_context", "expired_admission"])
@pytest.mark.parametrize("succeeds", [True, False])
async def test_fresh_escalation_admission_retries_transient_race_once(
    transport: tuple, code: str, succeeds: bool
) -> None:
    provider, requests, responses = transport
    responses.extend(
        [
            _conflict("stale_approval"),
            _conflict(code),
            _evaluation("escalate") if succeeds else _conflict(code),
        ]
    )
    executor = _Executor()
    result = await ToolRouter(guardrails=provider).execute(
        _call(),
        _session(),
        _agent({"*": Permission.EVALUATE}),
        _readonly_registry("read"),
        executor,
    )
    assert result.is_error
    assert result.metadata["evaluation"]["decision"] == ("escalate" if succeeds else "deny")
    assert result.metadata["evaluation"]["conflict_code"] == (
        "stale_approval" if succeeds else code
    )
    assert len(requests) == 3
    assert requests[1] == requests[2]
    assert requests[1]["args"] == _call().arguments
    assert requests[1]["minimum_outcome"] == "escalate"
    assert "approval_call_id" not in requests[1]
    assert executor.calls == 0
