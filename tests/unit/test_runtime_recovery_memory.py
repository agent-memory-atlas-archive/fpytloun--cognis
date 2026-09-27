from __future__ import annotations

import asyncio
import weakref
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cognis.api import runtime_support
from cognis.core.executor_pin_lifecycle import _target_ready
from cognis.core.executor_policy import ExecutorPolicy
from cognis.core.executor_recovery import ExecutorRecoveryTimeout, ExecutorRecoveryWindow
from cognis.core.runtime import TransientExecutorUnavailable
from cognis.models.agent import AgentDefinition
from cognis.models.tool import ExecutorCapabilities, ExecutorHandle
from cognis.providers.executor.forwarding import ForwardedExecutorConnection
from cognis.providers.executor.websocket import WebSocketExecutorProvider
from cognis.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_pin_and_waiter_agree_on_lazy_forwarded_readiness() -> None:
    connection = ForwardedExecutorConnection(
        executor_id="exec-1",
        capabilities=ExecutorCapabilities(),
        owner_id="controller-b:boot-b",
        epoch=7,
        owner_internal_url="http://controller-b:8000",
        requester_owner_id="controller-a:boot-a",
        auth_provider=None,
    )
    provider = WebSocketExecutorProvider()
    provider._forwarded_by_executor["exec-1"] = connection
    provider._handles["exec-1"] = ExecutorHandle(
        executor_id="exec-1", executor_type="websocket", status="ready"
    )
    target = SimpleNamespace(usable=True, executor_type="websocket", executor_id="exec-1")
    try:
        assert not connection.connected
        assert await provider.wait_for_connection("exec-1", timeout=0.01) is connection
        assert _target_ready(target, provider)
        provider._handles["exec-1"].status = "suspended"
        assert not _target_ready(target, provider)
        provider._handles["exec-1"].status = "ready"
        await connection.close()
        assert not _target_ready(target, provider)
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["retry", "wait_deadline", "backoff_deadline", "cancel"])
async def test_runtime_recovery_releases_failed_attempt_catalogs(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    class Catalog:
        pass

    class StopProbe(Exception):
        pass

    live: weakref.WeakSet[Catalog] = weakref.WeakSet()
    retained: list[int] = []
    attempts = 0

    @asynccontextmanager
    async def session():
        yield None

    async def resolve(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts > 4:
            raise StopProbe
        catalog = Catalog()
        live.add(catalog)
        retained.append(len(live))
        raise TransientExecutorUnavailable("Not ready", executor_id="exec-1")

    cancel_event = asyncio.Event()

    async def wait(*args, **kwargs):
        if mode == "wait_deadline":
            await asyncio.sleep(0.02)
        if mode == "cancel":
            cancel_event.set()
        return object()

    waiter = AsyncMock(side_effect=wait)
    providers = SimpleNamespace(
        _session_factory=session,
        executor=SimpleNamespace(websocket=SimpleNamespace(wait_for_connection=waiter)),
    )
    monkeypatch.setattr(
        runtime_support,
        "load_executor_policy",
        AsyncMock(return_value=ExecutorPolicy(allow_in_process=False, allow_subprocess=True)),
    )
    monkeypatch.setattr(runtime_support, "_resolve_eligible_executor_config", resolve)
    duration = 0.01 if mode.endswith("deadline") else 10
    now = datetime.now(UTC)
    window = ExecutorRecoveryWindow(
        executor_id="exec-1",
        unavailable_since=now,
        deadline=now + timedelta(seconds=duration),
        database_remaining_seconds=duration,
    )
    monkeypatch.setattr(
        runtime_support,
        "begin_executor_recovery",
        AsyncMock(return_value=window),
    )
    monkeypatch.setattr("cognis.store.queries.get_conversation", AsyncMock(return_value=None))
    factory = runtime_support.build_step_runtime_factory(
        providers=providers,
        shared_registry=ToolRegistry(),
        shared_connection=None,
        session_factory=session,
    )
    expected_error = (
        StopProbe
        if mode == "retry"
        else asyncio.CancelledError
        if mode == "cancel"
        else ExecutorRecoveryTimeout
    )
    with pytest.raises(expected_error):
        await asyncio.wait_for(
            factory(
                AgentDefinition(agent_id="agent-1", name="Agent", owner_email="owner@test.local"),
                "owner@test.local",
                conversation_id="conv-1",
                cancel_event=cancel_event,
            ),
            timeout=2,
        )
    count = 4 if mode == "retry" else 1
    assert retained == [1] * count
    assert waiter.await_count == count
