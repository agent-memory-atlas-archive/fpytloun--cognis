"""Admission control for effective-tools preview requests.

Preview resolution builds the full tool catalog (executor manifests, Intaris
MCP listings, classifications) per request. A client re-sending the same
preview in a loop previously ran dozens of these concurrently per replica and
exhausted memory. Identical in-flight previews (same user and payload) share
one resolution, and distinct previews are bounded per process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass

DEFAULT_MAX_CONCURRENT_PREVIEWS = 4


@dataclass
class _Flight[T]:
    task: asyncio.Task[T]
    waiters: int = 0


class EffectiveToolsPreviewGate[T]:
    """Single-flight plus bounded concurrency for preview resolution."""

    def __init__(self, *, max_concurrent: int = DEFAULT_MAX_CONCURRENT_PREVIEWS) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._inflight: dict[Hashable, _Flight[T]] = {}

    async def run(self, key: Hashable, resolve: Callable[[], Awaitable[T]]) -> T:
        """Resolve ``key`` once for all concurrent callers.

        The shared resolution keeps running when one caller is cancelled so
        other waiters still receive the result; it is cancelled only when the
        last interested caller goes away.
        """
        flight = self._inflight.get(key)
        if flight is None:
            task = asyncio.create_task(self._resolve(resolve))
            # All waiters may be gone; consume the outcome so failures are not
            # reported as unretrieved task exceptions.
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
            flight = _Flight(task=task)
            self._inflight[key] = flight
            created = flight
            task.add_done_callback(lambda _t: self._forget(key, created))
        flight.waiters += 1
        try:
            return await asyncio.shield(flight.task)
        except asyncio.CancelledError:
            if flight.waiters <= 1 and not flight.task.done():
                # Unregister before cancelling so a replacement request
                # starts a fresh resolution instead of joining this one.
                self._forget(key, flight)
                flight.task.cancel()
            raise
        finally:
            flight.waiters -= 1

    async def _resolve(self, resolve: Callable[[], Awaitable[T]]) -> T:
        async with self._semaphore:
            return await resolve()

    def _forget(self, key: Hashable, flight: _Flight[T]) -> None:
        if self._inflight.get(key) is flight:
            del self._inflight[key]
