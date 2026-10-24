"""Controller approval receipts must reach Intaris on every evaluated path."""

import json
from unittest.mock import Mock

import httpx
import pytest

from cognis.core.tool_router import ToolRouter
from cognis.models.agent import Permission
from cognis.models.tool import ToolCall
from cognis.providers.guardrails.intaris import IntarisProvider
from tests.unit.test_tool_router import _agent, _readonly_registry, _session


@pytest.mark.asyncio
@pytest.mark.parametrize("non_bypassable", [False, True])
@pytest.mark.parametrize("mode", ["default", "plan"])
@pytest.mark.parametrize("decision", ["approve", "deny"])
async def test_approved_read_receipt_reaches_intaris_without_outcome_floor(
    non_bypassable, mode, decision
):
    captured = []

    def respond(request):
        data = json.loads(request.content)
        captured.append(data)
        return httpx.Response(
            200,
            json={
                "decision": decision,
                "reasoning": "Exact receipt checked",
                "call_id": "evaluated-read",
                "risk": "low",
                "path": "fast",
                "latency_ms": 1,
            },
        )

    auth = Mock()
    auth.sign_access_token.return_value = "test-only-token"
    provider = IntarisProvider("https://intaris.test", auth)
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="https://intaris.test", transport=httpx.MockTransport(respond)
    )
    registry = _readonly_registry("read")
    registry.get("read").definition.non_bypassable = non_bypassable
    router = ToolRouter(guardrails=provider)
    call = ToolCall(
        call_id="controller-retry",
        name="read",
        arguments={"path": "/tmp/README.md"},
        runtime_metadata={"approval_call_id": "approved-original", "chat_mode": mode},
    )
    try:
        result = await router.evaluate_tool_call(
            call, _agent({"*": Permission.EVALUATE}), _session(), registry
        )
        changed = ToolCall(
            call_id="different-action",
            name="read",
            arguments={"path": "/tmp/OTHER.md"},
            runtime_metadata={"chat_mode": mode},
        )
        await router.evaluate_tool_call(
            changed, _agent({"*": Permission.EVALUATE}), _session(), registry
        )
        # Even after a normal read warms the existing cache, a receipt must be
        # validated by Intaris, never accepted from that generic read bucket.
        await router.evaluate_tool_call(
            call, _agent({"*": Permission.EVALUATE}), _session(), registry
        )
    finally:
        await provider.client.aclose()
    assert result.decision == decision
    assert captured[0]["approval_call_id"] == "approved-original"
    assert "minimum_outcome" not in captured[0]
    assert captured[0]["args"] == call.arguments
    assert captured[0]["session_id"] == _session().session_id
    assert captured[0]["context"]["chat_mode"] == mode
    assert len(captured) == 3
    assert "approval_call_id" not in captured[1]
    assert captured[1]["args"] == changed.arguments


@pytest.mark.asyncio
async def test_tool_arguments_cannot_supply_controller_receipt():
    provider = Mock()
    from unittest.mock import AsyncMock

    from cognis.models.tool import EvaluationResult

    provider.evaluate = AsyncMock(
        return_value=EvaluationResult(
            decision="deny",
            reasoning="No controller receipt",
            call_id="unapproved-action",
            risk="low",
            path="fast",
            latency_ms=1,
        )
    )
    router = ToolRouter(guardrails=provider)
    call = ToolCall(
        call_id="argument-injection",
        name="read",
        arguments={"approval_call_id": "untrusted-argument", "path": "/tmp/changed"},
    )
    result = await router.evaluate_tool_call(
        call, _agent({"*": Permission.EVALUATE}), _session(), _readonly_registry("read")
    )
    assert result.decision == "deny"
    assert "approval_call_id" not in provider.evaluate.call_args.kwargs["context"]


@pytest.mark.asyncio
@pytest.mark.parametrize("permission", [Permission.EVALUATE, Permission.DENY])
@pytest.mark.parametrize("self_mutation", [False, True])
async def test_receipt_mutation_floor_and_agent_denial(permission, self_mutation):
    from cognis.models.tool import EvaluationResult
    from tests.unit.test_tool_router import MANAGE_AGENTS_TOOL, RegisteredTool, ToolRegistry

    seen = []
    auth = Mock()
    auth.sign_access_token.return_value = "test-only-token"
    provider = IntarisProvider("https://intaris.test", auth)
    await provider.client.aclose()

    def respond(request):
        data = json.loads(request.content)
        seen.append(data)
        return httpx.Response(
            200,
            json=EvaluationResult(
                decision="deny",
                reasoning="Receipt cannot override denial",
                call_id="denied-mutation",
                risk="low",
                path="fast",
                latency_ms=1,
            ).model_dump()
            | {"minimum_outcome": data.get("minimum_outcome")},
        )

    provider.client = httpx.AsyncClient(
        base_url="https://intaris.test", transport=httpx.MockTransport(respond)
    )
    agent = _agent({"*": permission})
    if self_mutation:
        registry = ToolRegistry()
        registry.register(RegisteredTool(definition=MANAGE_AGENTS_TOOL))
        name = "manage_agents"
        args = {"action": "update", "agent_id": agent.agent_id, "name": "Updated"}
    else:
        agent.capabilities.minimum_outcome = "escalate"
        registry = _readonly_registry("write")
        registry.get("write").definition.read_only = False
        name, args = "write", {"path": "/tmp/file", "content": "data"}
    call = ToolCall(
        call_id="mutation-retry",
        name=name,
        arguments=args,
        runtime_metadata={
            "approval_call_id": "approved-mutation",
            "chat_mode": "default",
        },
    )
    try:
        result = await ToolRouter(guardrails=provider).evaluate_tool_call(
            call, agent, _session(), registry
        )
    finally:
        await provider.client.aclose()
    assert result.decision == "deny"
    if permission == Permission.DENY:
        assert seen == []
    else:
        assert seen[0]["approval_call_id"] == "approved-mutation"
        assert seen[0]["minimum_outcome"] == "escalate"
        assert seen[0]["args"] == args
