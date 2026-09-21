"""Event-loop lag watchdog (diagnostics only).

A daemon thread posts a heartbeat callback onto the loop and measures how
long it takes to run. Because the thread does not depend on the loop, it can
observe and report a stall *while* the loop is blocked and capture the loop
thread's stack so the blocking call site is named, not guessed. It never
touches ownership, leases or probes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
import traceback

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

LOOP_LAG_SECONDS = Gauge(
    "cognis_event_loop_lag_seconds",
    "Current event-loop lag as observed by the watchdog thread",
)
LOOP_LAG_HISTOGRAM = Histogram(
    "cognis_event_loop_lag_histogram_seconds",
    "Completed heartbeat round-trips through the event loop",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)
LOOP_STALLS_TOTAL = Counter(
    "cognis_event_loop_stalls_total",
    "Heartbeats whose lag exceeded the stack-dump threshold",
)

DEFAULT_INTERVAL_SECONDS = 1.0
DEFAULT_SAMPLE_SECONDS = 0.25
DEFAULT_STACK_DUMP_SECONDS = 5.0
DEFAULT_STACK_DUMP_COOLDOWN_SECONDS = 30.0


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


class EventLoopWatchdog:
    """Measure loop lag from a thread and dump the loop's stack on long stalls."""

    def __init__(
        self,
        *,
        interval_seconds: float | None = None,
        sample_seconds: float | None = None,
        stack_dump_seconds: float | None = None,
        stack_dump_cooldown_seconds: float | None = None,
    ) -> None:
        self.interval_seconds = interval_seconds or _env_float(
            "COGNIS_LOOP_LAG_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS
        )
        self.sample_seconds = sample_seconds or _env_float(
            "COGNIS_LOOP_LAG_SAMPLE_SECONDS", DEFAULT_SAMPLE_SECONDS
        )
        self.stack_dump_seconds = stack_dump_seconds or _env_float(
            "COGNIS_LOOP_LAG_STACK_DUMP_SECONDS", DEFAULT_STACK_DUMP_SECONDS
        )
        self.stack_dump_cooldown_seconds = stack_dump_cooldown_seconds or _env_float(
            "COGNIS_LOOP_LAG_STACK_DUMP_COOLDOWN_SECONDS", DEFAULT_STACK_DUMP_COOLDOWN_SECONDS
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Only one heartbeat is ever outstanding; a stalled loop must not
        # accumulate callbacks it will have to drain afterwards.
        self._outstanding_since: float | None = None
        self._state_lock = threading.Lock()
        self._last_dump_at = 0.0
        self.max_lag_seconds = 0.0

    def start(self) -> None:
        """Start from the loop thread so the loop and its thread id are captured."""

        if self._thread is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="cognis-loop-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the thread; safe to call before the loop closes."""

        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def _mark(self, posted_at: float) -> None:
        lag = time.perf_counter() - posted_at
        with self._state_lock:
            self._outstanding_since = None
        LOOP_LAG_SECONDS.set(lag)
        LOOP_LAG_HISTOGRAM.observe(lag)
        self.max_lag_seconds = max(self.max_lag_seconds, lag)

    def _post_heartbeat(self) -> bool:
        loop = self._loop
        if loop is None or loop.is_closed():
            return False
        posted_at = time.perf_counter()
        with self._state_lock:
            self._outstanding_since = posted_at
        try:
            loop.call_soon_threadsafe(self._mark, posted_at)
        except RuntimeError:
            # Loop closed between the check and the call.
            with self._state_lock:
                self._outstanding_since = None
            return False
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._state_lock:
                outstanding_since = self._outstanding_since
            if outstanding_since is None:
                if not self._post_heartbeat():
                    return
                self._stop.wait(self.interval_seconds)
                continue
            # The loop has not run the heartbeat yet: report the live lag so the
            # stall is visible while it is happening.
            lag = time.perf_counter() - outstanding_since
            LOOP_LAG_SECONDS.set(lag)
            self.max_lag_seconds = max(self.max_lag_seconds, lag)
            if lag >= self.stack_dump_seconds:
                self._maybe_dump_stack(lag)
            self._stop.wait(self.sample_seconds)

    def _maybe_dump_stack(self, lag: float) -> None:
        now = time.monotonic()
        if now - self._last_dump_at < self.stack_dump_cooldown_seconds:
            return
        self._last_dump_at = now
        LOOP_STALLS_TOTAL.inc()
        frame = (
            sys._current_frames().get(self._loop_thread_id)
            if self._loop_thread_id is not None
            else None
        )
        stack = "".join(traceback.format_stack(frame)) if frame is not None else "<unavailable>"
        logger.warning(
            "event loop stalled",
            extra={
                "extra_data": {
                    "lag_seconds": round(lag, 3),
                    "stack_dump_threshold_seconds": self.stack_dump_seconds,
                    "loop_thread_stack": stack,
                }
            },
        )
