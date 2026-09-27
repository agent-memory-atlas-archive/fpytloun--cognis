"""Cancellation-safe joins for owned lifecycle cleanup."""

from __future__ import annotations

import asyncio


async def join_owned_task[T](task: asyncio.Task[T]) -> T:
    """Wait for owned work to settle before propagating caller cancellation.

    Unlike shield alone, this keeps the caller alive until the child finishes.
    The child is never cancelled here; its owner must request cancellation when
    appropriate before joining it.
    """
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()
