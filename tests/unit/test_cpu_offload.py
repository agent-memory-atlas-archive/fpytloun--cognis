"""Bounded CPU offload: capacity follows the worker thread, not the awaiter."""

from __future__ import annotations

import asyncio
import contextvars
import threading
import time

import pytest

from cognis.core import cpu_offload
from cognis.core.cpu_offload import CpuOffloadSaturated, inflight_count, run_cpu_bound


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COGNIS_CPU_OFFLOAD_WORKERS", "1")
    monkeypatch.setenv("COGNIS_CPU_OFFLOAD_QUEUE", "3")
    cpu_offload._STATES.clear()


async def test_result_kwargs_and_exceptions_propagate() -> None:
    def add(a: int, *, b: int) -> int:
        return a + b

    assert await run_cpu_bound(add, 1, b=2) == 3

    def boom() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        await run_cpu_bound(boom)
    assert inflight_count() == 0


async def test_contextvars_reach_the_worker() -> None:
    var: contextvars.ContextVar[str] = contextvars.ContextVar("var", default="unset")
    var.set("loop-value")
    assert await run_cpu_bound(var.get) == "loop-value"


async def test_cancelled_awaiter_keeps_slot_until_thread_finishes() -> None:
    release = threading.Event()
    started = threading.Event()
    finished: list[float] = []

    def slow() -> str:
        started.set()
        release.wait(5.0)
        finished.append(time.perf_counter())
        return "late"

    first = asyncio.create_task(run_cpu_bound(slow))
    await asyncio.get_running_loop().run_in_executor(None, started.wait, 5.0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    # The thread is still running: the single worker slot must remain taken.
    assert inflight_count() == 1

    second_started = threading.Event()

    def fast() -> str:
        second_started.set()
        return "second"

    second = asyncio.create_task(run_cpu_bound(fast))
    await asyncio.sleep(0.1)
    assert not second_started.is_set(), "second task ran while the abandoned worker held the slot"
    assert not second.done()

    release.set()
    assert await second == "second"
    assert finished, "abandoned worker did not complete"
    await asyncio.sleep(0)
    assert inflight_count() == 0


async def test_admission_bound_rejects_overflow() -> None:
    release = threading.Event()
    started = threading.Event()

    def block() -> None:
        started.set()
        release.wait(5.0)

    running = asyncio.create_task(run_cpu_bound(block))
    await asyncio.get_running_loop().run_in_executor(None, started.wait, 5.0)
    queued = [asyncio.create_task(run_cpu_bound(block)) for _ in range(2)]
    await asyncio.sleep(0)
    assert inflight_count() == 3
    with pytest.raises(CpuOffloadSaturated):
        await run_cpu_bound(block)
    for task in queued:
        task.cancel()
    release.set()
    await running
    await asyncio.gather(*queued, return_exceptions=True)
    await asyncio.sleep(0.05)
    assert inflight_count() == 0


async def test_state_is_per_loop() -> None:
    first_loop_state = cpu_offload._state_for_running_loop()

    def other_loop() -> object:
        async def probe() -> object:
            return cpu_offload._state_for_running_loop()

        return asyncio.run(probe())

    other_state = await asyncio.to_thread(other_loop)
    assert other_state is not first_loop_state
