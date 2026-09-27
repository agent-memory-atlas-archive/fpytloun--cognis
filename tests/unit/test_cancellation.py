"""Owned cleanup must settle before cancellation propagates."""

import asyncio

import pytest

from cognis.core.cancellation import join_owned_task


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_join_preserves_cancellation_until_child_settles(fails: bool) -> None:
    finish = asyncio.Event()

    async def child() -> int:
        await finish.wait()
        if fails:
            raise RuntimeError("cleanup failed")
        return 42

    task = asyncio.create_task(child())
    waiter = asyncio.create_task(join_owned_task(task))
    await asyncio.sleep(0)
    for _ in range(3):
        waiter.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not waiter.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert task.done()


@pytest.mark.asyncio
async def test_join_propagates_child_failure() -> None:
    async def child() -> None:
        raise RuntimeError("cleanup failed")

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await join_owned_task(asyncio.create_task(child()))


@pytest.mark.asyncio
async def test_join_propagates_child_cancellation() -> None:
    task = asyncio.create_task(asyncio.sleep(60))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await join_owned_task(task)
