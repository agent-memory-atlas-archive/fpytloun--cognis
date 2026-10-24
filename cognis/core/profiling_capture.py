"""Process-local profiling lifecycle and bounded, content-free reports."""

from __future__ import annotations

import asyncio
import contextlib
import time
import tracemalloc
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from cognis.core.resource_attribution import MemorySummary, ResourceAttribution


class CaptureOptions(BaseModel):
    """Profiles describe Python diagnostics, not distributed or native tracing."""

    model_config = ConfigDict(extra="forbid")
    level: Literal["light", "cpu", "allocations", "full"] = "cpu"
    duration_seconds: int = Field(default=120, ge=10, le=600)
    sample_interval_ms: int = Field(default=100, ge=50, le=1000)
    allocation_interval_seconds: int = Field(default=60, ge=30, le=300)
    traceback_depth: int = Field(default=5, ge=1, le=10)
    allocation_snapshots: bool = True


class AllocationCapture:
    """Own tracing only when started here; never stop an external tracer."""

    def __init__(self, depth: int) -> None:
        self.depth = depth
        self.owned = False
        self.previous: dict[tuple[str, ...], tuple[int, int]] = {}
        self.previous_truncated = False

    def start(self) -> None:
        if tracemalloc.is_tracing():
            raise RuntimeError("allocation_tracer_already_active")
        tracemalloc.start(self.depth)
        self.owned = True

    def sample(self, snapshots: bool = True) -> dict[str, Any]:
        current, peak = tracemalloc.get_traced_memory()
        if not snapshots:
            return {
                "python_bytes": current,
                "python_peak_bytes": peak,
                "profiler_bytes": tracemalloc.get_tracemalloc_memory(),
                "snapshots": False,
            }
        snapshot = tracemalloc.take_snapshot()
        statistics = snapshot.statistics("traceback")
        # Bound retained delta state; snapshot/grouping transient cost is not bounded.
        truncated = len(statistics) > 20_000
        totals = {
            tuple(f"{frame.filename[-240:]}:{frame.lineno}" for frame in item.traceback): (
                item.size,
                item.count,
            )
            for item in statistics[:20_000]
        }
        top = [(key, *value) for key, value in list(totals.items())[:10]]
        delta = (
            sorted(
                (
                    (key, size - self.previous.get(key, (0, 0))[0])
                    for key, (size, _) in totals.items()
                ),
                key=lambda row: abs(row[1]),
                reverse=True,
            )[:10]
            if self.previous
            else []
        )
        # Report frees as well, but never pretend evicted baseline entries are frees.
        if self.previous and not truncated:
            delta = sorted(
                delta
                + [(key, -value[0]) for key, value in self.previous.items() if key not in totals],
                key=lambda row: abs(row[1]),
                reverse=True,
            )[:10]
        result = {
            "python_bytes": current,
            "python_peak_bytes": peak,
            "profiler_bytes": tracemalloc.get_tracemalloc_memory(),
            "baseline_truncated": truncated,
            "delta_incomplete": truncated or self.previous_truncated,
            "top": top,
            "delta": delta,
        }
        self.previous = totals
        self.previous_truncated = truncated
        return result

    def stop(self) -> None:
        self.previous.clear()
        if self.owned:
            tracemalloc.stop()
            self.owned = False


async def finish(task: asyncio.Task[Any]) -> Any:
    """Do not abandon an owned worker on caller cancellation."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        with contextlib.suppress(Exception):
            task.result()
        raise asyncio.CancelledError
    return task.result()


class LocalCapture:
    """One immutable capture, with explicit stop and fresh collectors per run."""

    def __init__(
        self,
        capture_id: str,
        options: CaptureOptions,
        memory_summary: MemorySummary,
    ) -> None:
        self.capture_id = capture_id
        self.options = options
        self.memory_summary = memory_summary
        self.state = "pending"
        self.report: dict[str, Any] = {"allocations": [], "errors": []}
        self.stop_requested = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.owned_tracing = False

    def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self._run(), name="admin-profiling-capture")

    async def _run(self) -> None:
        resources = ResourceAttribution(
            configured=True,
            duration=self.options.duration_seconds,
            interval_ms=self.options.sample_interval_ms,
            stacks=self.options.level in {"cpu", "full"},
            log_details=False,
        )
        allocations = AllocationCapture(self.options.traceback_depth)
        try:
            if self.options.level in {"allocations", "full"}:
                allocations.start()
                self.owned_tracing = True
            self.state = "running"
            self.started_at = time.time()
            deadline = time.monotonic() + self.options.duration_seconds
            resources.start(self.memory_summary)
            while not self.stop_requested.is_set():
                if allocations.owned:
                    worker = asyncio.create_task(
                        asyncio.to_thread(allocations.sample, self.options.allocation_snapshots)
                    )
                    sample = await finish(worker)
                    sample["elapsed_seconds"] = self.options.duration_seconds - max(
                        0, deadline - time.monotonic()
                    )
                    self.report["allocations"].append(sample)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self.stop_requested.wait(),
                        timeout=min(self.options.allocation_interval_seconds, remaining),
                    )
        except asyncio.CancelledError:
            self.state = "interrupted"
            raise
        except Exception:
            self.state = "failed"
            self.report["errors"].append("capture_failed")
        finally:
            await resources.stop()
            self.report["resources"] = resources.report
            allocations.stop()
            self.owned_tracing = False
            self.finished_at = time.time()
            if self.state not in {"failed", "interrupted"}:
                self.state = "stopped" if self.stop_requested.is_set() else "completed"

    async def stop(self) -> None:
        if self.state in {"pending", "running"}:
            self.state = "stopping"
        self.stop_requested.set()
        if self.task is not None:
            await finish(self.task)

    def status(self) -> dict[str, Any]:
        return {
            "capture_id": self.capture_id,
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "owned_tracing": self.owned_tracing,
            "tracemalloc_active": tracemalloc.is_tracing(),
        }
