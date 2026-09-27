"""Opt-in, content-free controller memory diagnostics."""

import asyncio
import contextlib
import logging
import os
import socket
import threading
import tracemalloc
from pathlib import Path

logger = logging.getLogger(__name__)
type TracebackKey = tuple[str, ...]
type TracebackTotals = dict[TracebackKey, tuple[int, int]]


def _traceback_frames(
    statistic: tracemalloc.Statistic | tracemalloc.StatisticDiff,
) -> tuple[str, ...]:
    return tuple(str(frame) for frame in statistic.traceback)


def _number(path: str) -> int | None:
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


class MemoryDiagnostics:
    def __init__(self) -> None:
        selected = os.getenv("COGNIS_MEMORY_PROFILE_POD", "")
        self.enabled = os.getenv("COGNIS_MEMORY_PROFILING", "").lower() in {"true", "1"}
        self.enabled &= not selected or selected == socket.gethostname()
        self.snapshots = os.getenv("COGNIS_MEMORY_PROFILE_SNAPSHOTS", "").lower() in {"true", "1"}
        default_depth = "10" if self.snapshots else "1"
        try:
            self.interval = max(
                10, min(3600, int(os.getenv("COGNIS_MEMORY_PROFILE_INTERVAL_SECONDS", "60")))
            )
            self.depth = max(
                1,
                min(10, int(os.getenv("COGNIS_MEMORY_PROFILE_TRACEBACK_DEPTH", default_depth))),
            )
        except ValueError:
            self.interval, self.depth = 60, 1
        self.previous: TracebackTotals | None = None
        self.task: asyncio.Task[None] | None = None
        self.stopping = asyncio.Event()
        self.application_started = threading.Event()
        self.owns_tracing = False

    def start(self) -> None:
        if not self.enabled or self.task is not None:
            return
        if not tracemalloc.is_tracing():
            tracemalloc.start(self.depth)
            self.owns_tracing = True
        self.task = asyncio.create_task(self.run(), name="memory-diagnostics")

    def mark_application_started(self) -> None:
        """Allow expensive snapshots after the application finishes startup."""

        self.application_started.set()

    def sample(self) -> None:
        rss = None
        try:
            for line in Path("/proc/self/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) * 1024
        except (OSError, ValueError):
            pass
        current, peak = tracemalloc.get_traced_memory()
        top = []
        growth = []
        if self.snapshots and self.application_started.is_set():
            snapshot = tracemalloc.take_snapshot()
            statistics = snapshot.statistics("traceback")
            top = [
                (_traceback_frames(statistic), statistic.size, statistic.count)
                for statistic in statistics[:10]
            ]
            current_totals = {
                _traceback_frames(statistic): (statistic.size, statistic.count)
                for statistic in statistics
            }
            if self.previous is not None:
                differences = [
                    (
                        traceback,
                        totals[0] - self.previous.get(traceback, (0, 0))[0],
                        totals[1] - self.previous.get(traceback, (0, 0))[1],
                    )
                    for traceback, totals in current_totals.items()
                ]
                differences.extend(
                    (traceback, -totals[0], -totals[1])
                    for traceback, totals in self.previous.items()
                    if traceback not in current_totals
                )
                growth = sorted(
                    differences,
                    key=lambda item: (abs(item[1]), item[1], abs(item[2])),
                    reverse=True,
                )[:10]
            self.previous = current_totals
            del statistics, snapshot
        logger.info(
            "memory_profile rss_bytes=%s cgroup_bytes=%s cgroup_limit_bytes=%s "
            "python_bytes=%s python_peak_bytes=%s profiler_bytes=%s top=%s delta=%s",
            rss,
            _number("/sys/fs/cgroup/memory.current"),
            _number("/sys/fs/cgroup/memory.max"),
            current,
            peak,
            tracemalloc.get_tracemalloc_memory(),
            top,
            growth,
        )

    async def run(self) -> None:
        while not self.stopping.is_set():
            try:
                await asyncio.to_thread(self.sample)
            except Exception:
                logger.warning("Memory profiling sample failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stopping.wait(), timeout=self.interval)

    async def stop(self) -> None:
        self.stopping.set()
        if self.task is not None:
            await asyncio.shield(self.task)
        self.previous = None
        if self.owns_tracing:
            tracemalloc.stop()
