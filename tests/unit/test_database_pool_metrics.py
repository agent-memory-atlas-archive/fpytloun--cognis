from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cognis.store.database import DB_POOL_CHECKED_OUT, _instrument_pool, pool_snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_failed_pre_ping_does_not_count_unmatched_checkin(tmp_path, monkeypatch, failure):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/pool.db", pool_pre_ping=True)
    _instrument_pool(engine)
    baseline = DB_POOL_CHECKED_OUT._value.get()
    try:
        async with engine.connect():
            assert DB_POOL_CHECKED_OUT._value.get() == baseline + 1

        def fail_ping(_connection):
            raise failure()

        with monkeypatch.context() as patch:
            patch.setattr(engine.sync_engine.dialect, "do_ping", fail_ping)
            with pytest.raises(failure):
                await engine.connect()
        assert pool_snapshot(engine)["checkedout"] == 0
        assert DB_POOL_CHECKED_OUT._value.get() == baseline

        for _ in range(2):
            async with engine.connect() as connection:
                assert DB_POOL_CHECKED_OUT._value.get() == baseline + 1
                # Invalidation clears connection.info, but not record_info.
                record = connection.sync_connection.connection._connection_record
                await connection.invalidate()
                assert DB_POOL_CHECKED_OUT._value.get() == baseline
                # Duplicate checkin must not subtract another engine's occupancy.
                engine.sync_engine.pool.dispatch.checkin(None, record)
                assert DB_POOL_CHECKED_OUT._value.get() == baseline
        assert pool_snapshot(engine)["checkedout"] == 0
    finally:
        await engine.dispose()
    assert DB_POOL_CHECKED_OUT._value.get() == baseline


@pytest.mark.asyncio
async def test_pool_gauge_sums_engines_and_returns_connection_on_cancellation(tmp_path):
    engines = [
        create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/queue.db"),
        create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/null.db", poolclass=NullPool),
    ]
    for engine in engines:
        _instrument_pool(engine)
    baseline = DB_POOL_CHECKED_OUT._value.get()
    entered = asyncio.Event()

    async def hold_connection():
        async with engines[1].connect():
            entered.set()
            await asyncio.Event().wait()

    try:
        async with engines[0].connect():
            task = asyncio.create_task(hold_connection())
            await asyncio.wait_for(entered.wait(), timeout=2)
            assert DB_POOL_CHECKED_OUT._value.get() == baseline + 2
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert DB_POOL_CHECKED_OUT._value.get() == baseline + 1
        assert pool_snapshot(engines[0])["checkedout"] == 0
        assert DB_POOL_CHECKED_OUT._value.get() == baseline
    finally:
        for engine in engines:
            await engine.dispose()
