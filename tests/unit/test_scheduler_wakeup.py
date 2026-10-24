"""Barrier-driven coverage of scheduler wake consumption."""

import asyncio

import pytest

from cognis.core.events import EventBus
from cognis.core.scheduler import Scheduler


@pytest.mark.asyncio
@pytest.mark.parametrize("during_error", [False, True])
async def test_wakes_during_pass_are_coalesced_not_lost(during_error):
    scheduler = Scheduler(None, None, EventBus())
    entered, release, repeated = asyncio.Event(), asyncio.Event(), asyncio.Event()
    passes = 0

    async def tick():
        nonlocal passes
        passes += 1
        if passes == 1:
            entered.set()
            await release.wait()
            if during_error:
                raise RuntimeError("transient discovery error")
            await scheduler._interruptible_sleep(60)
        else:
            repeated.set()
            scheduler._stop_event.set()

    scheduler._tick = tick
    worker = asyncio.create_task(scheduler._timer_loop())
    try:
        await entered.wait()
        for _ in range(10):
            scheduler.wake()
        release.set()
        await asyncio.wait_for(repeated.wait(), timeout=2)
        await worker
        assert passes == 2
    finally:
        scheduler._stop_event.set()
        scheduler.wake()
        await worker


@pytest.mark.asyncio
async def test_stop_during_pass_does_not_wait_for_recovery_sweep():
    scheduler = Scheduler(None, None, EventBus())
    entered, release = asyncio.Event(), asyncio.Event()
    scheduler._running = True

    async def tick():
        entered.set()
        await release.wait()
        await scheduler._interruptible_sleep(60)

    scheduler._tick = tick
    scheduler._timer_task = asyncio.create_task(scheduler._timer_loop())
    await entered.wait()
    # stop() signals synchronously before awaiting the worker.
    stopping = asyncio.create_task(scheduler.stop())
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(stopping, timeout=2)
    assert scheduler._timer_task is None


@pytest.mark.asyncio
async def test_idle_wait_still_has_bounded_fallback(monkeypatch):
    scheduler = Scheduler(None, None, EventBus())
    waits = []

    async def wait(awaitable, timeout):
        waits.append(timeout)
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", wait)
    await scheduler._interruptible_sleep(60)
    assert waits == [60]
