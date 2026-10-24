"""Tests for effective-tools preview admission control."""

from __future__ import annotations

import asyncio

import pytest

from cognis.api.effective_tools_preview_gate import EffectiveToolsPreviewGate


@pytest.mark.asyncio
async def test_identical_concurrent_previews_share_one_resolution() -> None:
    gate: EffectiveToolsPreviewGate[str] = EffectiveToolsPreviewGate()
    calls = 0
    release = asyncio.Event()

    async def resolve() -> str:
        nonlocal calls
        calls += 1
        await release.wait()
        return "result"

    waiters = [asyncio.create_task(gate.run(("u", "p"), resolve)) for _ in range(20)]
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(*waiters) == ["result"] * 20
    assert calls == 1


@pytest.mark.asyncio
async def test_distinct_previews_are_bounded() -> None:
    gate: EffectiveToolsPreviewGate[int] = EffectiveToolsPreviewGate(max_concurrent=2)
    active = 0
    peak = 0

    async def resolve() -> int:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return 1

    await asyncio.gather(*(gate.run(("u", i), resolve) for i in range(8)))
    assert peak == 2


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_cancel_shared_resolution() -> None:
    gate: EffectiveToolsPreviewGate[str] = EffectiveToolsPreviewGate()
    release = asyncio.Event()

    async def resolve() -> str:
        await release.wait()
        return "ok"

    first = asyncio.create_task(gate.run("k", resolve))
    second = asyncio.create_task(gate.run("k", resolve))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert await second == "ok"


@pytest.mark.asyncio
async def test_last_cancelled_caller_cancels_resolution() -> None:
    gate: EffectiveToolsPreviewGate[str] = EffectiveToolsPreviewGate()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def resolve() -> str:
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "never"

    caller = asyncio.create_task(gate.run("k", resolve))
    await started.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    await asyncio.wait_for(cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_failure_propagates_and_is_not_reused() -> None:
    gate: EffectiveToolsPreviewGate[str] = EffectiveToolsPreviewGate()
    calls = 0

    async def resolve() -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await gate.run("k", resolve)
    with pytest.raises(RuntimeError):
        await gate.run("k", resolve)
    assert calls == 2


@pytest.mark.asyncio
async def test_replacement_after_last_cancel_starts_fresh_resolution() -> None:
    gate: EffectiveToolsPreviewGate[str] = EffectiveToolsPreviewGate()
    calls = 0

    async def resolve() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                # Slow cleanup keeps the cancelled task alive briefly.
                await asyncio.sleep(0.05)
                raise
        return "fresh"

    caller = asyncio.create_task(gate.run("k", resolve))
    await asyncio.sleep(0)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert await gate.run("k", resolve) == "fresh"
    assert calls == 2
