"""Synthetic palette qualification against a disposable database, never production.

Usage: uv run python scripts/benchmark_palette.py --url sqlite+aiosqlite:////tmp/palette-bench.db
By default the database must be empty; existing tables are refused.
Use --measure-only to re-read a task-owned dataset without schema or data writes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from cognis.core.palette import PaletteAdmission
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import (
    ArtifactRecordRow,
    Base,
    Conversation,
    DeliverableRow,
    Schedule,
    Task,
)
from cognis.store.palette_indexes import ensure_palette_indexes
from cognis.store.queries import create_agent, create_user


async def benchmark(url: str, count: int, other_count: int, *, measure_only: bool = False) -> None:
    """Measure real authorized SQL and report bounded metadata response costs."""
    engine = create_engine(url)
    if measure_only:
        try:
            await measure(engine, count, other_count)
        finally:
            await engine.dispose()
        return
    async with engine.begin() as conn:
        tables = await conn.run_sync(lambda connection: sa.inspect(connection).get_table_names())
        if tables:
            raise RuntimeError(
                "Refusing a non-empty database. Use a task-owned disposable database."
            )
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(ensure_palette_indexes)
    factory = create_session_factory(engine)
    async with factory() as session:
        await create_user(
            session,
            email="palette-benchmark@local.test",
            name="Palette benchmark",
            password_hash="test",
        )
        await create_agent(
            session,
            agent_id="palette-benchmark",
            owner_email="palette-benchmark@local.test",
            name="Benchmark",
        )
        for start in range(0, count, 500):
            await session.execute(
                sa.insert(Conversation),
                [
                    {
                        "conversation_id": f"palette-benchmark-{index:07}",
                        "title": f"{'Command palette' if index % 20 == 0 else 'Project discussion'} {index:07}",
                        "user_email": "palette-benchmark@local.test",
                        "agent_id": "palette-benchmark",
                        "context_type": "web",
                        "context_ref": None,
                    }
                    for index in range(start, min(start + 500, count))
                ],
            )
        owner = "palette-benchmark@local.test"
        for start in range(0, other_count, 250):
            indices = range(start, min(start + 250, other_count))
            await session.execute(
                sa.insert(Task),
                [
                    {
                        "task_id": f"palette-benchmark-task-{index:07}",
                        "agent_id": "palette-benchmark",
                        "created_by": owner,
                        "description": "Synthetic benchmark metadata",
                        "title": f"{'Command palette' if index % 20 == 0 else 'Project review'} {index:07}",
                    }
                    for index in indices
                ],
            )
            await session.execute(
                sa.insert(Schedule),
                [
                    {
                        "schedule_id": f"palette-benchmark-schedule-{index:07}",
                        "agent_id": "palette-benchmark",
                        "created_by": owner,
                        "task_template": {},
                        "name": f"{'Command palette' if index % 20 == 0 else 'Project weekly review'} {index:07}",
                    }
                    for index in indices
                ],
            )
            await session.execute(
                sa.insert(DeliverableRow),
                [
                    {
                        "deliverable_id": f"palette-benchmark-document-{index:07}",
                        "owner_email": owner,
                        "storage_object_id": f"palette-benchmark-document-{index:07}",
                        "content_mime": "text/markdown",
                        "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                        "status": "delivered",
                        "title": f"{'Command palette' if index % 20 == 0 else 'Project report'} {index:07}",
                    }
                    for index in indices
                ],
            )
            await session.execute(
                sa.insert(ArtifactRecordRow),
                [
                    {
                        "artifact_id": f"palette-benchmark-file-{index:07}",
                        "namespace": "artifacts",
                        "object_id": f"palette-benchmark-file-{index:07}",
                        "owner_email": owner,
                        "lineage_id": f"palette-benchmark-file-{index:07}",
                        "mime_type": "application/pdf",
                        "purpose": "artifact_write",
                        "status": "attached",
                        "filename": f"{'Command palette' if index % 20 == 0 else 'Project budget'} {index:07}.pdf",
                    }
                    for index in indices
                ],
            )
        await session.commit()
    if engine.dialect.name == "postgresql":
        async with engine.begin() as conn:
            await conn.execute(sa.text("ANALYZE"))
    try:
        await measure(engine, count, other_count)
    finally:
        await engine.dispose()


async def measure(engine: AsyncEngine, count: int, other_count: int) -> None:
    """Re-measure an existing task-owned dataset without schema/data writes."""
    factory = create_session_factory(engine)
    report = {}
    admission = PaletteAdmission(per_user_rate=1000, global_rate=1000)
    for query in ("", "command", "project", "command pallete", "zzzzzz"):
        times = []
        sizes = []
        for _ in range(12):
            async with factory() as session:
                started = time.perf_counter()
                page = await admission.run(session, "palette-benchmark@local.test", query)
                times.append((time.perf_counter() - started) * 1000)
                sizes.append(len(page.model_dump_json()))
        report[query or "(recent)"] = {
            "median_ms": round(statistics.median(times), 2),
            "p95_ms": round(sorted(times)[-1], 2),
            "response_bytes_max": max(sizes),
        }
    print(
        json.dumps(
            {
                "dialect": engine.dialect.name,
                "conversations": count,
                "each_other_entity": other_count,
                "results": report,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--count", type=int, default=20_000)
    parser.add_argument("--other-count", type=int, default=1000)
    parser.add_argument(
        "--measure-only",
        action="store_true",
        help="Read an existing task-owned benchmark dataset without modifying it",
    )
    args = parser.parse_args()
    asyncio.run(benchmark(args.url, args.count, args.other_count, measure_only=args.measure_only))
