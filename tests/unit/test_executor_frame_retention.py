from __future__ import annotations

import asyncio
import weakref
from typing import Any

import pytest

from cognis.models.tool import ExecutorCapabilities
from cognis.providers.executor.websocket import WebSocketExecutorConnection


class TrackedPayload(dict):
    pass


class Socket:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.waiting = asyncio.Event()

    async def receive_json(self) -> dict[str, Any]:
        self.waiting.set()
        return await self.queue.get()

    async def close(self, **kwargs) -> None:
        pass


@pytest.mark.asyncio
async def test_completed_response_is_released_before_waiting_and_after_heartbeats():
    socket = Socket()
    connection = WebSocketExecutorConnection(socket, "executor-memory", ExecutorCapabilities())
    response = TrackedPayload(content="large result " * 1000)
    reference = weakref.ref(response)
    future = asyncio.get_running_loop().create_future()
    connection._pending["retention-call"] = future
    socket.queue.put_nowait({"id": "retention-call", "result": response})
    del response
    connection.start_receiver()
    try:
        assert (await future)["content"].startswith("large result")
        del future
        await asyncio.sleep(0)
        assert reference() is None
        socket.queue.put_nowait({"method": "executor.heartbeat", "params": {}})
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert reference() is None
        assert connection._connected
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_frame_payload_is_not_kept_while_waiting_for_next_notification():
    socket = Socket()
    connection = WebSocketExecutorConnection(socket, "executor-memory", ExecutorCapabilities())
    payload = TrackedPayload(content="large unhandled notification " * 1000)
    reference = weakref.ref(payload)
    socket.queue.put_nowait({"method": "unhandled.test", "params": payload})
    del payload
    connection.start_receiver()
    try:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert reference() is None
        assert connection._connected
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["llm.chunk", "llm.done"])
async def test_consumed_inference_frame_does_not_remain_in_dispatch_closure(method):
    socket = Socket()
    connection = WebSocketExecutorConnection(socket, "executor-memory", ExecutorCapabilities())
    queue = asyncio.Queue()
    connection._inference_queues["inference-retention"] = queue
    params = TrackedPayload(request_id="inference-retention", delta="inference text " * 1000)
    reference = weakref.ref(params)
    socket.queue.put_nowait({"method": method, "params": params})
    del params
    connection.start_receiver()
    try:
        event = await asyncio.wait_for(queue.get(), timeout=1)
        assert event["request_id"] == "inference-retention"
        del event
        await asyncio.sleep(0)
        assert reference() is None
    finally:
        connection._inference_queues.clear()
        await connection.close()


@pytest.mark.asyncio
async def test_consumer_still_owns_result_until_it_releases_it():
    socket = Socket()
    connection = WebSocketExecutorConnection(socket, "executor-memory", ExecutorCapabilities())
    response = TrackedPayload(content="retained by consumer")
    reference = weakref.ref(response)
    future = asyncio.get_running_loop().create_future()
    connection._pending["consumer-owned-call"] = future
    socket.queue.put_nowait({"id": "consumer-owned-call", "result": response})
    del response
    connection.start_receiver()
    try:
        result = await future
        del future
        await asyncio.sleep(0)
        assert reference() is result
        del result
        assert reference() is None
    finally:
        await connection.close()
