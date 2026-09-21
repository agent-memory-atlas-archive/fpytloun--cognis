"""Event-loop lag watchdog: observes stalls from a thread, one heartbeat at a time."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from cognis.core.loop_watchdog import LOOP_LAG_SECONDS, EventLoopWatchdog


async def test_watchdog_reports_lag_during_a_stall_and_dumps_the_stack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="cognis.core.loop_watchdog")
    watchdog = EventLoopWatchdog(
        interval_seconds=0.05,
        sample_seconds=0.02,
        stack_dump_seconds=0.2,
        stack_dump_cooldown_seconds=60.0,
    )
    watchdog.start()
    try:
        await asyncio.sleep(0.15)  # let a heartbeat round-trip while idle
        assert watchdog.max_lag_seconds < 0.1

        # Block the loop thread; the watchdog thread must see the lag *during* the stall.
        observed_during_stall: list[float] = []

        def _blocking() -> None:
            deadline = time.perf_counter() + 0.6
            while time.perf_counter() < deadline:
                time.sleep(0.05)
                observed_during_stall.append(LOOP_LAG_SECONDS._value.get())

        _blocking()
        await asyncio.sleep(0.1)
    finally:
        watchdog.stop()

    assert max(observed_during_stall) >= 0.4, observed_during_stall
    assert watchdog.max_lag_seconds >= 0.5
    stalls = [r for r in caplog.records if r.getMessage() == "event loop stalled"]
    assert len(stalls) == 1, "stack dumps are rate-limited by the cooldown"
    stack = stalls[0].extra_data["loop_thread_stack"]  # type: ignore[attr-defined]
    assert "_blocking" in stack, stack


async def test_watchdog_never_has_more_than_one_heartbeat_outstanding() -> None:
    watchdog = EventLoopWatchdog(interval_seconds=0.01, sample_seconds=0.01, stack_dump_seconds=60)
    marks: list[float] = []
    original_mark = watchdog._mark

    def _counting_mark(posted_at: float) -> None:
        marks.append(posted_at)
        original_mark(posted_at)

    watchdog._mark = _counting_mark  # type: ignore[method-assign]
    watchdog.start()
    try:
        time.sleep(0.3)  # stall: the thread must not queue ~30 callbacks
        await asyncio.sleep(0.05)
    finally:
        watchdog.stop()
    # One heartbeat was outstanding through the stall, plus a few after it.
    assert 1 <= len(marks) <= 6, marks


async def test_watchdog_stops_cleanly_when_loop_closes() -> None:
    watchdog = EventLoopWatchdog(interval_seconds=0.01, sample_seconds=0.01)

    def _run_and_close() -> None:
        loop = asyncio.new_event_loop()

        async def _start() -> None:
            watchdog.start()
            await asyncio.sleep(0.05)

        loop.run_until_complete(_start())
        loop.close()

    await asyncio.to_thread(_run_and_close)
    # The thread notices the closed loop and exits without raising.
    await asyncio.to_thread(time.sleep, 0.1)
    watchdog.stop()
    assert watchdog._thread is None
