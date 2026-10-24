"""Controller routing and agent notice policy for user-initiated tool backgrounding."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from cognis.bootstrap import bootstrap_runtime
from cognis.config import load_config
from cognis.core.agent_loop import AgentLoop, StepContext
from cognis.core.message_markers import ALL_INTERNAL_MARKERS, TOOL_BACKGROUND_NOTICE
from cognis.core.tool_backgrounding import (
    TOOL_BACKGROUND_NOTICE_KIND,
    ToolBackgroundError,
    ToolBackgroundErrorCode,
    ToolBackgroundingService,
    tool_background_notice_from_result,
)
from cognis.models.tool import ExecutorCapabilities, ExecutorConfig, ToolResult
from cognis.providers.executor.forwarding import ForwardedExecutorConnection
from cognis.providers.executor.in_process import InProcessExecutorProvider
from cognis.providers.executor.websocket import WebSocketExecutorConnection
from cognis.security import create_password_hasher
from cognis.tools.executor.definitions import BASH_TOOL
from cognis.tools.registry import ToolBackgroundRequestOutcome
from tests.unit.test_in_process_executor import _contract_call


def _row(*descriptors: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        session_id="sess-1",
        turn_id="turn-1",
        outcome={
            "tool_dispatch_groups": [
                {"session_id": "sess-1", "turn_id": "turn-1", "tool_calls": list(descriptors)}
            ]
        },
    )


class _Store:
    def __init__(self, row: Any) -> None:
        self.row = row
        self.calls: list[str] = []

    async def get_conversation_active(self, conversation_id: str) -> Any:
        self.calls.append(conversation_id)
        return self.row


class _Connection:
    def __init__(
        self,
        *,
        instance_id: str | None = "inst-1",
        outcome: ToolBackgroundRequestOutcome = ToolBackgroundRequestOutcome.ACCEPTED,
        error: BaseException | None = None,
    ) -> None:
        self.executor_instance_id = instance_id
        self.outcome = outcome
        self.error = error
        self.requested: list[str] = []

    async def request_background(self, call_id: str) -> ToolBackgroundRequestOutcome:
        self.requested.append(call_id)
        if self.error is not None:
            raise self.error
        return self.outcome


def _service(row: Any, connection: _Connection | None = None, in_process: Any = None) -> Any:
    websocket = SimpleNamespace(get_connection=lambda executor_id: connection)
    return ToolBackgroundingService(
        direct_turn_store=cast(Any, _Store(row)),
        executor_provider=SimpleNamespace(websocket=websocket, in_process=in_process),
    )


_BASH = {
    "call_id": "call-1",
    "tool_name": "bash",
    "executor_id": "exec-a",
    "executor_instance_id": "inst-1",
    "dispatch_state": "sent",
}


@pytest.mark.asyncio
async def test_request_routes_to_bound_executor_instance() -> None:
    connection = _Connection()
    result = await _service(_row(_BASH), connection).request_background(
        conversation_id="conv-1", call_id="call-1"
    )

    assert connection.requested == ["call-1"]
    assert result.call_id == "call-1"
    assert result.tool_name == "bash"
    assert result.executor_id == "exec-a"
    assert result.already_requested is False


@pytest.mark.asyncio
async def test_repeated_request_is_idempotent() -> None:
    connection = _Connection(outcome=ToolBackgroundRequestOutcome.ALREADY_REQUESTED)
    result = await _service(_row(_BASH), connection).request_background(
        conversation_id="conv-1", call_id="call-1"
    )

    assert result.already_requested is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service_factory", "code"),
    [
        (
            lambda: ToolBackgroundingService(direct_turn_store=None, executor_provider=None),
            ToolBackgroundErrorCode.NO_ACTIVE_TURN,
        ),
        (lambda: _service(None, _Connection()), ToolBackgroundErrorCode.NO_ACTIVE_TURN),
        (
            lambda: _service(_row({**_BASH, "call_id": "other"}), _Connection()),
            ToolBackgroundErrorCode.UNKNOWN_CALL,
        ),
        (
            lambda: _service(_row({**_BASH, "tool_name": "read"}), _Connection()),
            ToolBackgroundErrorCode.UNSUPPORTED_TOOL,
        ),
        (
            lambda: _service(
                _row(_BASH),
                _Connection(outcome=ToolBackgroundRequestOutcome.NOT_BACKGROUNDABLE),
            ),
            ToolBackgroundErrorCode.NOT_BACKGROUNDABLE,
        ),
        (
            lambda: _service(
                _row(_BASH), _Connection(outcome=ToolBackgroundRequestOutcome.UNKNOWN_CALL)
            ),
            ToolBackgroundErrorCode.NOT_BACKGROUNDABLE,
        ),
        (
            lambda: _service(_row(_BASH), _Connection(error=TimeoutError())),
            ToolBackgroundErrorCode.EXECUTOR_UNSUPPORTED,
        ),
        (
            lambda: _service(_row(_BASH), _Connection(error=RuntimeError("socket closed"))),
            ToolBackgroundErrorCode.EXECUTOR_UNAVAILABLE,
        ),
        (lambda: _service(_row(_BASH), None), ToolBackgroundErrorCode.EXECUTOR_UNAVAILABLE),
    ],
)
async def test_request_rejections(service_factory: Any, code: ToolBackgroundErrorCode) -> None:
    with pytest.raises(ToolBackgroundError) as error:
        await service_factory().request_background(conversation_id="conv-1", call_id="call-1")

    assert error.value.code is code


@pytest.mark.asyncio
async def test_replacement_executor_instance_is_never_asked() -> None:
    connection = _Connection(instance_id="inst-2")

    with pytest.raises(ToolBackgroundError) as error:
        await _service(_row(_BASH), connection).request_background(
            conversation_id="conv-1", call_id="call-1"
        )

    assert error.value.code is ToolBackgroundErrorCode.EXECUTOR_UNAVAILABLE
    assert connection.requested == []


@pytest.mark.asyncio
async def test_cold_forwarded_proxy_without_instance_identity_is_routed() -> None:
    connection = _Connection(instance_id=None)

    result = await _service(_row(_BASH), connection).request_background(
        conversation_id="conv-1", call_id="call-1"
    )

    assert connection.requested == ["call-1"]
    assert result.already_requested is False


@pytest.mark.asyncio
async def test_unbound_call_falls_back_to_in_process_executor() -> None:
    in_process = SimpleNamespace(
        request_background=AsyncMock(return_value=ToolBackgroundRequestOutcome.ACCEPTED)
    )
    descriptor = {"call_id": "call-1", "tool_name": "bash", "dispatch_state": "pending"}

    result = await _service(_row(descriptor), None, in_process).request_background(
        conversation_id="conv-1", call_id="call-1"
    )

    assert result.executor_id is None
    in_process.request_background.assert_awaited_once_with("call-1")


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell semantics")
async def test_in_process_bash_moves_to_background_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    _, engine, session_factory, _ = await bootstrap_runtime(load_config(), create_password_hasher())
    provider = InProcessExecutorProvider(session_factory=session_factory)
    completed: list[dict[str, Any]] = []
    done = asyncio.Event()

    async def on_completed(_executor_id: str, status: dict[str, Any]) -> None:
        completed.append(status)
        done.set()

    provider.register_background_shell_completed_callback(on_completed)
    handle = await provider.spawn(ExecutorConfig(executor_id="exec-bash", tools=[BASH_TOOL]))
    connection = await provider.get_executor(handle)
    release = tmp_path / "release"
    execution = asyncio.create_task(
        connection.tool_execute(
            _contract_call(
                connection,
                call_id="call-1",
                name="bash",
                arguments={
                    "command": f"echo started; while [ ! -f '{release}' ]; do sleep 0.05; done",
                    "timeout": 30_000,
                },
                runtime_metadata={
                    "turn_id": "turn-1",
                    "tool_call_id": "call-1",
                    "runtime_access": {"conversation_id": "conv-1"},
                },
            )
        )
    )
    service = ToolBackgroundingService(
        direct_turn_store=cast(
            Any,
            _Store(_row({"call_id": "call-1", "tool_name": "bash", "dispatch_state": "pending"})),
        ),
        executor_provider=SimpleNamespace(websocket=None, in_process=provider),
    )

    try:
        async with asyncio.timeout(5):
            while True:
                try:
                    await service.request_background(conversation_id="conv-1", call_id="call-1")
                    break
                except ToolBackgroundError as exc:
                    # Until the handler is waiting on the process the call is
                    # either not registered yet or not backgroundable yet.
                    assert exc.code in {
                        ToolBackgroundErrorCode.EXECUTOR_UNAVAILABLE,
                        ToolBackgroundErrorCode.NOT_BACKGROUNDABLE,
                    }
                    await asyncio.sleep(0.02)
        result = await asyncio.wait_for(execution, timeout=5)
        metadata = result.metadata or {}
        assert metadata["moved_to_background"] is True
        notice = tool_background_notice_from_result(
            call_id="call-1", tool_name="bash", executor_native=True, result=result
        )
        assert notice is not None and notice.shell_id == metadata["shell_id"]

        release.write_text("go")
        await asyncio.wait_for(done.wait(), timeout=5)
        assert completed[0]["shell_id"] == metadata["shell_id"]
        assert completed[0]["initiator"] == "user"
        assert completed[0]["conversation_id"] == "conv-1"
    finally:
        release.write_text("go")
        await provider.cleanup()
        await engine.dispose()


@pytest.mark.asyncio
async def test_websocket_connection_sends_tool_background_rpc() -> None:
    class PhysicalSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, Any]] = []

        async def send_json(self, request: dict[str, Any]) -> None:
            self.sent.append(request)
            physical._pending[request["id"]].set_result(
                {"call_id": "call-1", "accepted": True, "outcome": "accepted"}
            )

    socket = PhysicalSocket()
    physical = WebSocketExecutorConnection(cast(Any, socket), "exec-a", ExecutorCapabilities())

    outcome = await physical.request_background("call-1", timeout=1)

    assert outcome is ToolBackgroundRequestOutcome.ACCEPTED
    assert [(request["method"], request["params"]) for request in socket.sent] == [
        ("tool.background", {"call_id": "call-1"})
    ]


@pytest.mark.asyncio
async def test_forwarded_connection_routes_tool_background_to_owner_replica() -> None:
    forwarded = ForwardedExecutorConnection(
        executor_id="exec-a",
        capabilities=ExecutorCapabilities(),
        owner_id="controller-b",
        epoch=1,
        owner_internal_url="http://controller-b",
        requester_owner_id="controller-a",
        auth_provider=None,
    )
    rpc_call = AsyncMock(return_value={"accepted": False, "outcome": "already_requested"})
    forwarded.rpc_call = rpc_call  # type: ignore[method-assign]

    outcome = await forwarded.request_background("call-1", timeout=3)

    assert outcome is ToolBackgroundRequestOutcome.ALREADY_REQUESTED
    rpc_call.assert_awaited_once_with("tool.background", {"call_id": "call-1"}, timeout=3)


def _moved_result(**overrides: Any) -> ToolResult:
    metadata = {
        "shell_id": "shell_abc",
        "executor_id": "exec-a",
        "moved_to_background": True,
        "background_initiator": "user",
        **overrides,
    }
    return ToolResult(output="moved", metadata=metadata)


def test_notice_built_for_executor_native_user_handoff() -> None:
    notice = tool_background_notice_from_result(
        call_id="call-1", tool_name="bash", executor_native=True, result=_moved_result()
    )

    assert notice is not None
    assert notice.notice_id == f"{TOOL_BACKGROUND_NOTICE_KIND}:call-1"
    assert "The user moved your running bash command (call_id call-1)" in notice.agent_context
    assert "shell_id='shell_abc'" in notice.agent_context
    assert "target_executor='exec-a'" in notice.agent_context
    assert notice.metadata()["kind"] == TOOL_BACKGROUND_NOTICE_KIND
    assert notice.metadata()["agent_context"] == notice.agent_context


@pytest.mark.parametrize(
    ("tool_name", "executor_native", "result"),
    [
        ("bash", False, _moved_result()),
        ("mcp_bash", True, _moved_result()),
        ("bash", True, _moved_result(background_initiator="agent")),
        ("bash", True, _moved_result(moved_to_background="true")),
        ("bash", True, _moved_result(shell_id="")),
        ("bash", True, ToolResult(output="moved_to_background: true")),
    ],
)
def test_notice_rejects_untrusted_or_incomplete_results(
    tool_name: str, executor_native: bool, result: ToolResult
) -> None:
    assert (
        tool_background_notice_from_result(
            call_id="call-1",
            tool_name=tool_name,
            executor_native=executor_native,
            result=result,
        )
        is None
    )


@pytest.mark.asyncio
async def test_agent_loop_drains_notice_once_into_next_model_call() -> None:
    notice = tool_background_notice_from_result(
        call_id="call-1", tool_name="bash", executor_native=True, result=_moved_result()
    )
    assert notice is not None
    ctx = SimpleNamespace(
        pending_tool_background_notices=[notice], recorded_tool_background_notice_ids=set()
    )
    fake_loop = SimpleNamespace(_emit_recovery_notice=AsyncMock())
    fake_loop._record_tool_background_notices = lambda ctx, on_token=None: (
        AgentLoop._record_tool_background_notices(cast(Any, fake_loop), ctx, on_token=on_token)
    )
    messages: list[dict[str, Any]] = []

    # Post-batch hook records first (covers turn exits without another cycle).
    await AgentLoop._record_tool_background_notices(cast(Any, fake_loop), cast(Any, ctx))
    assert messages == []
    fake_loop._emit_recovery_notice.assert_awaited_once()

    await AgentLoop._drain_tool_background_notices(cast(Any, fake_loop), cast(Any, ctx), messages)
    await AgentLoop._drain_tool_background_notices(cast(Any, fake_loop), cast(Any, ctx), messages)

    assert messages == [
        {"role": "system", "content": notice.agent_context, TOOL_BACKGROUND_NOTICE: True}
    ]
    fake_loop._emit_recovery_notice.assert_awaited_once()
    kwargs = fake_loop._emit_recovery_notice.await_args.kwargs
    assert fake_loop._emit_recovery_notice.await_args.args[1] == notice.message
    assert kwargs["persist"] is True
    assert kwargs["metadata"]["notice_id"] == notice.notice_id
    assert ctx.pending_tool_background_notices == []
    assert TOOL_BACKGROUND_NOTICE in ALL_INTERNAL_MARKERS
    assert "pending_tool_background_notices" in StepContext.__dataclass_fields__
