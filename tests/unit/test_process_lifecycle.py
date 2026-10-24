import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from cognis.core.shell_target_evidence import shell_target_evidence
from cognis.providers.guardrails.intaris import IntarisProvider
from cognis.providers.guardrails.process_scope import build_binding


def binding(**overrides):
    values = dict(
        user_email="owner",
        agent_id="agent",
        session_id="session",
        conversation_id="conversation",
        execution_scope="task:work",
        logical_call_id="spawn-call",
        executor_id="executor",
        tool="bash",
        arguments={"command": "sleep 30", "run_in_background": True},
        target=None,
    )
    values.update(overrides)
    return build_binding(**values)


async def target():
    row = dict(
        user_email="owner",
        conversation_id="conversation",
        execution_scope="task:work",
        executor_id="executor",
        agent_id="agent",
        shell_id="shell-owned",
        admission_call_id="approved-spawn",
        admission_session_id="session",
        call_id="spawn-call",
        incarnation="incarnation",
        command="sleep 30",
        status="running",
        session_id="session",
    )
    executor = SimpleNamespace(
        executor_id="executor", background_shell_status=AsyncMock(return_value={"shells": [row]})
    )
    return await shell_target_evidence(
        executor,
        shell_id="shell-owned",
        user_id="owner",
        session_id="rotated-session",
        conversation_id="conversation",
    )


@pytest.mark.asyncio
async def test_only_controller_registered_exact_target_can_claim_lifecycle():
    assert binding() is not None
    args = {"shell_id": "shell-owned"}
    evidence = await target()
    assert binding(tool="bash_kill", arguments=args, target=evidence) is not None
    for field in (
        "source",
        "coverage",
        "user_id",
        "conversation_id",
        "executor_id",
        "shell_id",
        "target",
    ):
        changed = {**evidence, field: None}
        assert binding(tool="bash_kill", arguments=args, target=changed) is None
    for field in (
        "execution_scope",
        "agent_id",
        "admission_call_id",
        "admission_session_id",
        "call_id",
        "incarnation",
    ):
        changed = {**evidence, "target": {**evidence["target"], field: None}}
        assert binding(tool="bash_kill", arguments=args, target=changed) is None
    assert binding(tool="bash_kill", arguments={"shell_id": "other"}, target=evidence) is None
    assert binding(arguments={"command": "sleep 30"}) is None
    assert binding(tool="external:bash") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("supported", [True, False])
async def test_signed_producer_negotiates_and_requires_acknowledgment(supported):
    scoped = binding()
    calls, tokens = [], []

    def sign(subject, agent, **kwargs):
        tokens.append((subject, agent, kwargs))
        return "controller-token"

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"versions": [1]}) if supported else httpx.Response(404)
        payload = json.loads(request.content)
        calls.append(payload)
        metadata = {}
        if supported:
            assert request.headers["Authorization"] == "Bearer controller-token"
            assert payload["process_scope"] == scoped.declaration
            metadata["process_lifecycle"] = {
                "authenticated": True,
                "declaration": scoped.declaration,
            }
        else:
            assert "process_scope" not in payload
        return httpx.Response(
            200,
            json={
                "call_id": "admitted-call",
                "decision": "approve",
                "risk": "low",
                "reasoning": "bounded helper",
                "evaluation_metadata": metadata,
            },
        )

    provider = IntarisProvider(
        "http://intaris.test",
        SimpleNamespace(
            sign_service_jwt=lambda *a, **kw: "service-token",
            sign_process_scope_jwt=sign,
        ),
    )
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="http://intaris.test", transport=httpx.MockTransport(respond)
    )
    try:
        result = await provider.evaluate(
            "session",
            "bash",
            {"command": "sleep 30", "run_in_background": True},
            process_binding=scoped,
        )
        assert result.process_scope_digest == (scoped.digest if supported else None)
        assert len(tokens) == int(supported)
        assert len(calls) == 1
        with pytest.raises(ValueError, match="binding mismatch"):
            await provider.evaluate(
                "session", "bash", {"command": "different"}, process_binding=scoped
            )
    finally:
        await provider.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("acknowledged", [True, False])
@pytest.mark.parametrize("task_attempt", [None, 2])
async def test_real_router_provider_registry_and_executor_lifecycle(
    acknowledged, task_attempt, monkeypatch
):
    import re
    import sys

    from cognis.core.tool_router import ToolRouter
    from cognis.models.agent import Permission
    from cognis.models.tool import ToolCall
    from cognis.tools.executor.definitions import executor_tool_definitions
    from cognis.tools.executor.shell import (
        handle_bash,
        handle_bash_kill,
        list_background_shell_statuses,
    )
    from cognis.tools.registry import RegisteredTool, ToolRegistry
    from tests.unit.test_executor_tools import _context
    from tests.unit.test_tool_router import _agent, _session

    session, agent = _session(), _agent({"*": Permission.EVALUATE})
    if task_attempt is not None:
        fence = SimpleNamespace(
            claim=SimpleNamespace(
                task_id="lifecycle-task",
                attempt_number=task_attempt,
            )
        )
        monkeypatch.setattr(
            "cognis.core.task_execution.current_task_execution_fence", lambda: fence
        )
    execution_scope = (
        f"task:lifecycle-task:attempt:{task_attempt}"
        if task_attempt is not None
        else f"conversation:{session.conversation_id}"
    )
    context = _context("lifecycle-router-integration")
    metadata = {
        "runtime_access": {
            "user_email": session.user_email,
            "conversation_id": session.conversation_id,
            "session_id": session.session_id,
            "agent_id": agent.agent_id,
        }
    }
    shared = {}
    context = replace(context, runtime_metadata=metadata, shared_runtime_metadata=shared)
    declarations = []

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"versions": [1]})
        body = json.loads(request.content)
        declaration = body.get("process_scope")
        if declaration is None:
            return httpx.Response(
                200,
                json={
                    "call_id": "ordinary-review",
                    "decision": "escalate",
                    "risk": "medium",
                    "reasoning": "No lifecycle receipt",
                },
            )
        declarations.append(declaration)
        return httpx.Response(
            200,
            json={
                "call_id": f"admission-{len(declarations)}",
                "decision": "approve",
                "risk": "medium",
                "reasoning": "Admitted lifecycle",
                "evaluation_metadata": {
                    "process_lifecycle": {
                        "authenticated": True,
                        "declaration": declaration,
                    }
                }
                if acknowledged
                else {},
            },
        )

    provider = IntarisProvider(
        "http://intaris.test",
        SimpleNamespace(
            sign_service_jwt=lambda *a, **kw: "service",
            sign_process_scope_jwt=lambda *a, **kw: "scoped",
        ),
    )
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="http://intaris.test", transport=httpx.MockTransport(respond)
    )

    class Connection:
        executor_id = "test"  # Real connections have no .config.

        async def background_shell_status(self, **kwargs):
            return {"shells": await list_background_shell_statuses(shared, **kwargs)}

        async def tool_execute(self, call, **kwargs):
            assert "_process_binding" not in call.runtime_metadata
            runtime = {**metadata, **call.runtime_metadata}
            runtime["runtime_access"] = metadata["runtime_access"]
            runtime["tool_call_id"] = call.call_id
            scoped = replace(context, runtime_metadata=runtime)
            handler = handle_bash if call.name == "bash" else handle_bash_kill
            return await handler(call.arguments, scoped)

    registry = ToolRegistry()
    for definition in executor_tool_definitions():
        if definition.name in {"bash", "bash_kill"}:
            registry.register(RegisteredTool(definition=definition))
    router, connection = ToolRouter(guardrails=provider, non_bypassable_patterns=[]), Connection()
    shell = None
    try:
        result = await router.execute(
            ToolCall(
                call_id="lifecycle-start",
                name="bash",
                arguments={
                    "command": f'"{sys.executable}" -c "import time; time.sleep(30)"',
                    "run_in_background": True,
                },
            ),
            session,
            agent,
            registry,
            connection,
        )
        assert not result.is_error, result.output
        shell = re.search(r"shell_[a-z0-9]+", str(result.output)).group()
        snapshot = (await list_background_shell_statuses(shared))[0]
        assert snapshot["execution_scope"] == (execution_scope if acknowledged else None)
        assert snapshot["admission_call_id"] == "admission-1"
        assert snapshot["incarnation"]
        # Even a stale controller decision cannot terminate another incarnation.
        wrong = {
            "incarnation": "replaced-incarnation",
            "spawn_logical_call_id": snapshot["call_id"],
            "spawn_call_id": snapshot["admission_call_id"],
            "spawn_session_id": snapshot["admission_session_id"],
            "execution_scope": snapshot["execution_scope"],
            "conversation_id": snapshot["conversation_id"],
        }
        stale = await handle_bash_kill(
            {"shell_id": shell},
            replace(context, runtime_metadata={**metadata, "expected_process": wrong}),
        )
        assert stale.is_error
        assert not (await list_background_shell_statuses(shared))[0]["done"]
        if task_attempt is not None:
            fence.claim.attempt_number += 1
            foreign_attempt = await router.execute(
                ToolCall(
                    call_id="wrong-attempt-stop", name="bash_kill", arguments={"shell_id": shell}
                ),
                session,
                agent,
                registry,
                connection,
            )
            assert foreign_attempt.is_error
            assert not (await list_background_shell_statuses(shared))[0]["done"]
            fence.claim.attempt_number = task_attempt
        result = await router.execute(
            ToolCall(
                call_id="lifecycle-stop",
                name="bash_kill",
                arguments={"shell_id": shell},
            ),
            session,
            agent,
            registry,
            connection,
        )
        if acknowledged:
            assert not result.is_error, result.output
            assert [row["operation"] for row in declarations] == ["spawn", "terminate"]
            assert declarations[1]["spawn_call_id"] == "admission-1"
            assert declarations[1]["incarnation"] == snapshot["incarnation"]
            assert (await list_background_shell_statuses(shared, include_completed=True))[0]["done"]
        else:
            assert result.is_error
            assert [row["operation"] for row in declarations] == ["spawn"]
            assert not (await list_background_shell_statuses(shared))[0]["done"]
    finally:
        if shell:
            await handle_bash_kill({"shell_id": shell}, context)
        await provider.client.aclose()
