"""Short-lived single-flight cache for Intaris MCP catalog listings.

Effective-tool planning (runtime turns and editor previews) reads the full
Intaris MCP catalog on every call. Under bursts this multiplied identical
upstream requests and the parsed payload held in memory. Listings are cached
per (operation, user) for a short TTL, and concurrent misses share one
upstream fetch. Failed fetches are not cached.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

DEFAULT_MCP_LISTING_TTL_SECONDS = 15.0
_MAX_ENTRIES = 256


class MCPListingCache:
    """Per-key TTL cache with single-flight loading for list payloads."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_MCP_LISTING_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[Hashable, tuple[float, list[dict[str, Any]]]] = {}
        self._inflight: dict[Hashable, asyncio.Task[list[dict[str, Any]]]] = {}

    async def get(
        self,
        key: Hashable,
        load: Callable[[], Awaitable[list[dict[str, Any]]]],
    ) -> list[dict[str, Any]]:
        """Return a cached listing or load it once for all concurrent callers.

        ``load`` must raise on failure; exceptions propagate to every waiter
        and leave nothing cached. Callers receive a new list object; rows are
        shared and must be treated as read-only.
        """
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None and now - entry[0] < self._ttl:
            return list(entry[1])

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._load(key, load))
            # Waiters may all be cancelled; consume the outcome so a failure
            # is not reported as an unretrieved task exception.
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
            self._inflight[key] = task
        # Shield so a cancelled caller (e.g. client disconnect) does not
        # cancel the shared fetch other callers are waiting on.
        return list(await asyncio.shield(task))

    async def _load(
        self,
        key: Hashable,
        load: Callable[[], Awaitable[list[dict[str, Any]]]],
    ) -> list[dict[str, Any]]:
        try:
            value = await load()
            if len(self._entries) >= _MAX_ENTRIES:
                self._entries.clear()
            self._entries[key] = (self._clock(), value)
            return value
        finally:
            self._inflight.pop(key, None)

    def clear(self) -> None:
        """Drop all cached listings."""
        self._entries.clear()
