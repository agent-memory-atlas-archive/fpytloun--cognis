"""User-initiated foreground-to-background handoff for executor bash calls."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from cognis.executor.runner import ExecutorConfig, ExecutorRunner
from cognis.models.tool import ExecutorHandle
from cognis.tools.executor.shell import (
    handle_bash,
    handle_bash_kill,
    handle_bash_output,
    list_background_shell_statuses,
)
from cognis.tools.registry import (
    ToolBackgroundControl,
    ToolBackgroundRequestOutcome,
    ToolExecutionContext,
    parse_tool_background_rpc_result,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell semantics")


def _context(
    control: ToolBackgroundControl | None,
    *,
    shared: dict[str, Any],
    chunks: list[str] | None = None,
    completion: Any | None = None,
) -> ToolExecutionContext:
    runtime_metadata: dict[str, Any] = {
        "runtime_access": {
            "conversation_id": "conv-1",
            "session_id": "sess-1",
            "agent_id": "agent-1",
        },
        "turn_id": "turn-1",
        "tool_call_id": "call-1",
    }
    if completion is not None:
        runtime_metadata["background_shell_completion_callback"] = completion

    async def _chunk(text: str, _stream: str | None) -> None:
        if chunks is not None:
            chunks.append(text)

    return ToolExecutionContext(
        executor_handle=ExecutorHandle(executor_id="exec-a", executor_type="remote"),
        runtime_metadata=runtime_metadata,
        shared_runtime_metadata=shared,
        output_chunk_callback=_chunk,
        background_control=control,
    )


async def _wait_until(predicate: Any, *, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


def test_background_control_outcomes() -> None:
    control = ToolBackgroundControl()
    assert control.request() is ToolBackgroundRequestOutcome.NOT_BACKGROUNDABLE
    assert not control.requested.is_set()

    control.supported = True
    assert control.request() is ToolBackgroundRequestOutcome.ACCEPTED
    assert control.request() is ToolBackgroundRequestOutcome.ALREADY_REQUESTED


def test_parse_tool_background_rpc_result() -> None:
    assert (
        parse_tool_background_rpc_result({"accepted": True, "outcome": "accepted"})
        is ToolBackgroundRequestOutcome.ACCEPTED
    )
    assert (
        parse_tool_background_rpc_result({"accepted": False, "outcome": "unknown_call"})
        is ToolBackgroundRequestOutcome.UNKNOWN_CALL
    )
    assert (
        parse_tool_background_rpc_result({"outcome": "bogus"})
        is ToolBackgroundRequestOutcome.NOT_BACKGROUNDABLE
    )
    assert parse_tool_background_rpc_result(None) is ToolBackgroundRequestOutcome.NOT_BACKGROUNDABLE


@pytest.mark.asyncio
async def test_running_foreground_bash_moves_to_background_without_losing_output(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    shared: dict[str, Any] = {}
    chunks: list[str] = []
    completions: list[dict[str, Any]] = []
    completed = asyncio.Event()

    async def _completed(status: dict[str, Any]) -> None:
        completions.append(status)
        completed.set()

    control = ToolBackgroundControl()
    ctx = _context(control, shared=shared, chunks=chunks, completion=_completed)
    command = (
        "echo before; echo err-before >&2; "
        f"while [ ! -f '{release}' ]; do sleep 0.05; done; echo after"
    )
    task = asyncio.create_task(
        handle_bash({"command": command, "description": "slow build", "timeout": 30_000}, ctx)
    )

    await _wait_until(lambda: control.supported and "before" in "".join(chunks))
    assert control.request() is ToolBackgroundRequestOutcome.ACCEPTED
    result = await asyncio.wait_for(task, timeout=5)

    metadata = result.metadata or {}
    assert result.is_error is False
    assert metadata["moved_to_background"] is True
    assert metadata["background_initiator"] == "user"
    assert metadata["status"] == "running"
    shell_id = metadata["shell_id"]
    assert result.output.startswith(
        f"The user moved this running command to the background as shell {shell_id}."
    )
    assert "Output so far:" in result.output
    assert "before" in result.output
    assert "slow build" in result.output
    assert control.supported is False

    statuses = await list_background_shell_statuses(shared)
    assert [status["shell_id"] for status in statuses] == [shell_id]
    assert statuses[0]["initiator"] == "user"
    assert statuses[0]["call_id"] == "call-1"
    assert statuses[0]["conversation_id"] == "conv-1"

    release.write_text("go")
    await asyncio.wait_for(completed.wait(), timeout=5)
    assert completions[0]["shell_id"] == shell_id
    assert completions[0]["status"] == "completed"
    assert completions[0]["exit_code"] == 0

    output = await handle_bash_output({"shell_id": shell_id, "cursor": 0}, ctx)
    assert "before" in output.output
    assert "err-before" in output.output
    assert "after" in output.output
    assert output.output.index("before") < output.output.index("after")


@pytest.mark.asyncio
async def test_handoff_does_not_apply_foreground_timeout(tmp_path: Path) -> None:
    release = tmp_path / "release"
    shared: dict[str, Any] = {}
    control = ToolBackgroundControl()
    ctx = _context(control, shared=shared)
    task = asyncio.create_task(
        handle_bash(
            {
                "command": f"while [ ! -f '{release}' ]; do sleep 0.05; done",
                "timeout": 1_000,
            },
            ctx,
        )
    )
    await _wait_until(lambda: control.supported)
    control.request()
    result = await asyncio.wait_for(task, timeout=5)
    shell_id = (result.metadata or {})["shell_id"]

    await asyncio.sleep(1.5)
    statuses = await list_background_shell_statuses(shared)
    assert statuses and statuses[0]["status"] == "running"

    stopped = await handle_bash_kill({"shell_id": shell_id}, ctx)
    assert stopped.is_error is False


@pytest.mark.asyncio
async def test_completed_foreground_command_is_not_backgroundable() -> None:
    shared: dict[str, Any] = {}
    control = ToolBackgroundControl()
    result = await handle_bash({"command": "echo done"}, _context(control, shared=shared))

    assert "done" in result.output
    assert "moved_to_background" not in (result.metadata or {})
    assert control.request() is ToolBackgroundRequestOutcome.NOT_BACKGROUNDABLE
    assert await list_background_shell_statuses(shared, include_completed=True) == []


@pytest.mark.asyncio
async def test_agent_background_command_is_not_backgroundable_again() -> None:
    shared: dict[str, Any] = {}
    control = ToolBackgroundControl()
    ctx = _context(control, shared=shared)
    result = await handle_bash(
        {"command": "sleep 5", "run_in_background": True, "timeout": 100}, ctx
    )

    assert control.request() is ToolBackgroundRequestOutcome.NOT_BACKGROUNDABLE
    assert "moved_to_background" not in (result.metadata or {})
    await handle_bash_kill({"shell_id": (result.metadata or {})["shell_id"]}, ctx)


@pytest.mark.asyncio
async def test_foreground_timeout_still_kills_without_request() -> None:
    control = ToolBackgroundControl()
    result = await handle_bash({"command": "sleep 5", "timeout": 300}, _context(control, shared={}))

    assert result.is_error is True
    assert (result.metadata or {})["status"] == "timed_out"
    assert control.supported is False


@pytest.mark.asyncio
async def test_completion_wins_when_request_arrives_as_command_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A request racing process exit must yield the normal foreground result."""

    shared: dict[str, Any] = {}
    control = ToolBackgroundControl()
    original_wait = asyncio.wait

    async def _wait_then_request(*args: Any, **kwargs: Any) -> Any:
        result = await original_wait(*args, **kwargs)
        # Command already finished; a request in the same loop step must not
        # turn the completed result into a background handoff.
        control.requested.set()
        return result

    monkeypatch.setattr(asyncio, "wait", _wait_then_request)
    result = await handle_bash({"command": "echo finished"}, _context(control, shared=shared))
    monkeypatch.setattr(asyncio, "wait", original_wait)

    assert "finished" in result.output
    assert "moved_to_background" not in (result.metadata or {})
    assert await list_background_shell_statuses(shared, include_completed=True) == []


@pytest.mark.asyncio
async def test_cancellation_before_handoff_kills_foreground_process(tmp_path: Path) -> None:
    marker = tmp_path / "survived"
    control = ToolBackgroundControl()
    shared: dict[str, Any] = {}
    task = asyncio.create_task(
        handle_bash(
            {"command": f"sleep 1; touch '{marker}'", "timeout": 30_000},
            _context(control, shared=shared),
        )
    )
    await _wait_until(lambda: control.supported)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert control.supported is False
    assert control.request() is ToolBackgroundRequestOutcome.NOT_BACKGROUNDABLE
    await asyncio.sleep(1.5)
    assert not marker.exists()
    assert await list_background_shell_statuses(shared, include_completed=True) == []


@pytest.mark.asyncio
async def test_handoff_under_sustained_stdout_and_stderr_keeps_every_line(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    shared: dict[str, Any] = {}
    control = ToolBackgroundControl()
    ctx = _context(control, shared=shared, chunks=[])
    command = (
        "i=0; while [ ! -f '"
        f"{release}"
        "' ] || [ $i -lt 400 ]; do i=$((i+1)); echo out-$i; echo err-$i >&2; done; echo end"
    )
    task = asyncio.create_task(handle_bash({"command": command, "timeout": 30_000}, ctx))
    await _wait_until(lambda: control.supported)
    await asyncio.sleep(0.05)
    control.request()
    result = await asyncio.wait_for(task, timeout=10)
    shell_id = (result.metadata or {})["shell_id"]
    release.write_text("go")

    async def _done() -> bool:
        statuses = await list_background_shell_statuses(shared, include_completed=True)
        return bool(statuses) and statuses[0]["done"]

    async with asyncio.timeout(10):
        while not await _done():
            await asyncio.sleep(0.05)
    output = (await handle_bash_output({"shell_id": shell_id, "cursor": 0}, ctx)).output
    last = max(int(line[4:]) for line in output.splitlines() if line.startswith("out-"))
    for index in range(1, last + 1):
        assert f"out-{index}\n" in output
        assert f"err-{index}\n" in output
    assert "end" in output


class _IncomingWebSocket:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = messages
        self.sent: list[dict[str, Any]] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def __aiter__(self) -> Any:
        async def _iterate() -> Any:
            for message in self._messages:
                yield json.dumps(message)

        return _iterate()


@pytest.mark.asyncio
async def test_runner_tool_background_rpc_routes_to_active_call_control() -> None:
    runner = ExecutorRunner(ExecutorConfig(executor_id="remote", controller_token="t"))
    control = ToolBackgroundControl(supported=True)
    runner._background_controls["call-1"] = control
    ws = _IncomingWebSocket(
        [
            {
                "jsonrpc": "2.0",
                "id": "m1",
                "method": "tool.background",
                "params": {"call_id": "call-1"},
            },
            {
                "jsonrpc": "2.0",
                "id": "m2",
                "method": "tool.background",
                "params": {"call_id": "call-1"},
            },
            {
                "jsonrpc": "2.0",
                "id": "m3",
                "method": "tool.background",
                "params": {"call_id": "missing"},
            },
        ]
    )

    await runner._message_loop(ws)

    results = {message["id"]: message["result"] for message in ws.sent}
    assert results["m1"] == {"call_id": "call-1", "accepted": True, "outcome": "accepted"}
    assert results["m2"] == {
        "call_id": "call-1",
        "accepted": False,
        "outcome": "already_requested",
    }
    assert results["m3"] == {"call_id": "missing", "accepted": False, "outcome": "unknown_call"}
    assert control.requested.is_set()
