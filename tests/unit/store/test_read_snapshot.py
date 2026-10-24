from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, insert, select, update

from cognis.store.database import create_engine, create_session_factory, read_snapshot


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_snapshot_remains_consistent_while_writer_commits(tmp_path: Path, dialect: str) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'snapshot.db'}"
    if dialect == "postgresql":
        url = os.environ.get("COGNIS_TEST_POSTGRES_URL", "")
        if not url:
            pytest.skip("COGNIS_TEST_POSTGRES_URL is not set")

    async def run() -> None:
        engine = create_engine(url)
        factory = create_session_factory(engine)
        metadata = MetaData()
        probe = Table(
            f"snapshot_probe_{uuid4().hex}",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("value", Integer),
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(metadata.create_all)
                await conn.execute(insert(probe).values(id=1, value=0))
            async with read_snapshot(factory) as snapshot:
                assert await snapshot.scalar(select(probe.c.value)) == 0
                for value in range(1, 4):
                    async with factory() as writer:
                        await writer.execute(update(probe).values(value=value))
                        await writer.commit()
                    assert await snapshot.scalar(select(probe.c.value)) == 0
            async with factory() as reader:
                assert await reader.scalar(select(probe.c.value)) == 3
            # The connection's per-transaction isolation did not leak.
            async with factory() as writer:
                await writer.execute(update(probe).values(value=4))
                await writer.commit()
            with pytest.raises(asyncio.CancelledError):
                async with read_snapshot(factory) as snapshot:
                    assert await snapshot.scalar(select(probe.c.value)) == 4
                    raise asyncio.CancelledError
            async with factory() as writer:
                await writer.execute(update(probe).values(value=5))
                await writer.commit()
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(metadata.drop_all)
            await engine.dispose()

    asyncio.run(run())
