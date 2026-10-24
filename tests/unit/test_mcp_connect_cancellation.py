from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import httpx
import pytest

from cognis import mcp_runtime
from cognis.mcp_runtime import MCPClientError, _SessionMCPClient
from cognis.models.tool import MCPServerConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["transport", "session", "initialize"])
@pytest.mark.parametrize("trigger", ["caller", "timeout"])
async def test_cancelled_connect_unwinds_in_owner_task(
    monkeypatch: pytest.MonkeyPatch, phase: str, trigger: str
) -> None:
    entered: list[tuple[str, asyncio.Task[Any] | None]] = []
    exited: list[tuple[str, asyncio.Task[Any] | None]] = []
    blocked = asyncio.Event()

    async def block() -> None:
        blocked.set()
        await asyncio.Event().wait()

    class Transport:
        async def __aenter__(self) -> tuple[object, object]:
            entered.append(("transport", asyncio.current_task()))
            return object(), object()

        async def __aexit__(self, *_args: object) -> None:
            await asyncio.sleep(0)
            exited.append(("transport", asyncio.current_task()))

    class Session:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Session:
            if phase == "session":
                await block()
            entered.append(("session", asyncio.current_task()))
            return self

        async def __aexit__(self, *_args: object) -> None:
            await asyncio.sleep(0)
            exited.append(("session", asyncio.current_task()))

        async def initialize(self) -> None:
            await block()

    class Client(_SessionMCPClient):
        async def _enter_transport(self, stack: AsyncExitStack) -> tuple[object, object]:
            streams = await stack.enter_async_context(Transport())
            if phase == "transport":
                await block()
            return streams

    monkeypatch.setattr(mcp_runtime, "ClientSession", Session)
    client = Client(
        MCPServerConfig(name="cancelled-connect", command="/bin/echo", connect_timeout_seconds=1)
    )
    connect = asyncio.create_task(client.connect())
    await asyncio.wait_for(blocked.wait(), timeout=2)
    owner = client._task
    assert owner is not None
    if trigger == "caller":
        connect.cancel()
        expected_error = asyncio.CancelledError
    else:
        expected_error = MCPClientError
    with pytest.raises(expected_error):
        await asyncio.wait_for(connect, timeout=3)

    assert owner.done()
    assert owner.cancelled()
    assert client._task is None
    assert exited == list(reversed(entered))
    assert all(task is owner for _name, task in exited)


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["caller", "timeout"])
async def test_streamable_http_cancelled_initialize_leaves_no_sdk_tasks(
    monkeypatch: pytest.MonkeyPatch, trigger: str
) -> None:
    """Exercise real SDK/AnyIO scope teardown without an external MCP server."""
    initializing = asyncio.Event()
    request_cancelled = asyncio.Event()
    clients: list[httpx.AsyncClient] = []
    original_client = httpx.AsyncClient
    tasks_before = asyncio.all_tasks()

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method != "POST":
            return httpx.Response(405)
        initializing.set()
        try:
            await asyncio.Event().wait()
        finally:
            request_cancelled.set()
        raise AssertionError("unreachable")

    def create_client(**kwargs: Any) -> httpx.AsyncClient:
        client = original_client(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(mcp_runtime.httpx, "AsyncClient", create_client)
    client = mcp_runtime.StreamableHTTPMCPClient(
        MCPServerConfig(
            name="http-cancelled-connect",
            transport="streamable_http",
            url="https://mcp.test/mcp",
            connect_timeout_seconds=1,
        )
    )
    connect = asyncio.create_task(client.connect())
    await asyncio.wait_for(initializing.wait(), timeout=2)
    owner = client._task
    assert owner is not None
    if trigger == "caller":
        connect.cancel()
        expected_error = asyncio.CancelledError
    else:
        expected_error = MCPClientError
    with pytest.raises(expected_error):
        await asyncio.wait_for(connect, timeout=3)

    assert owner.done()
    assert request_cancelled.is_set()
    assert all(http_client.is_closed for http_client in clients)
    assert not (asyncio.all_tasks() - tasks_before)
