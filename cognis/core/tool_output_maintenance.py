"""Periodic retention maintenance for saved tool outputs."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from time import monotonic
from typing import Any

from cognis.core.maintenance_lease import run_periodic_maintenance
from cognis.logging import get_logger
from cognis.store.coordination import DatabaseLeaseStore

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ToolOutputMaintenanceResult:
    """Summary of one tool-output maintenance pass."""

    expired_deleted: int
    size_cap_deleted: int
    cleanup_failed: bool
    size_cap_failed: bool
    duration_seconds: float


class ToolOutputMaintenanceService:
    """Periodically enforce tool-output TTL and storage-size limits."""

    def __init__(
        self,
        tool_output_store: Any,
        *,
        interval_seconds: float = 300.0,
        lease_store: DatabaseLeaseStore | None = None,
    ) -> None:
        self._tool_output_store = tool_output_store
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._lease_store = lease_store

    async def start(self) -> None:
        """Start an immediate background pass followed by periodic maintenance."""

        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run_loop(),
            name="tool-output-maintenance",
        )

    async def stop(self) -> None:
        """Cancel and await the maintenance loop."""

        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def run_once(self) -> ToolOutputMaintenanceResult:
        """Run one failure-isolated retention and size-cap pass."""

        started_at = monotonic()
        retention = await self._tool_output_store.maintain()
        expired_deleted = retention.expired_deleted
        size_cap_deleted = retention.size_cap_deleted
        cleanup_failed = retention.cleanup_failed
        size_cap_failed = retention.size_cap_failed

        duration_seconds = monotonic() - started_at
        if expired_deleted or size_cap_deleted or duration_seconds >= 1.0:
            logger.info(
                "tool output maintenance completed",
                extra={
                    "extra_data": {
                        "expired_deleted": expired_deleted,
                        "size_cap_deleted": size_cap_deleted,
                        "cleanup_failed": cleanup_failed,
                        "size_cap_failed": size_cap_failed,
                        "duration_seconds": round(duration_seconds, 3),
                    }
                },
            )

        return ToolOutputMaintenanceResult(
            expired_deleted=expired_deleted,
            size_cap_deleted=size_cap_deleted,
            cleanup_failed=cleanup_failed,
            size_cap_failed=size_cap_failed,
            duration_seconds=duration_seconds,
        )

    async def _run_loop(self) -> None:
        await run_periodic_maintenance(
            self.run_once,
            stop=self._stop,
            interval_seconds=self._interval_seconds,
            resource_key="maintenance:tool-outputs",
            lease_store=self._lease_store,
        )
