from __future__ import annotations

import importlib

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select

from cognis.bootstrap import run_schema_bootstrap
from cognis.store.database import create_engine
from cognis.store.models import VideoBudgetRow


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", ["empty", "partial", "bootstrap"])
async def test_video_migration_preserves_bootstrap_and_partial_tables(
    tmp_path, monkeypatch, existing
):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'video-migration.db'}")
    migration = importlib.import_module("cognis.store.migrations.versions.167_video_provider_jobs")
    tables = {
        "video_jobs",
        "video_attempts",
        "video_budgets",
        "video_mutations",
        "video_transfers",
    }
    try:
        if existing == "bootstrap":
            await run_schema_bootstrap(engine)
            await run_schema_bootstrap(engine)
        async with engine.begin() as connection:
            if existing == "partial":
                await connection.run_sync(VideoBudgetRow.__table__.create)
            if existing != "empty":
                await connection.execute(
                    VideoBudgetRow.__table__.insert().values(
                        owner_email="owner@example.com",
                        day="2026-01-01",
                        exposure_microusd=12345,
                    )
                )

            def exercise(sync):
                monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(sync)))
                migration.upgrade()
                migration.upgrade()
                inspector = inspect(sync)
                assert tables <= set(inspector.get_table_names())
                assert {"ix_video_due", "ix_video_owner_conversation"} <= {
                    index["name"] for index in inspector.get_indexes("video_jobs")
                }
                assert "ix_video_transfers_job_id" in {
                    index["name"] for index in inspector.get_indexes("video_transfers")
                }

            await connection.run_sync(exercise)
            if existing != "empty":
                assert (await connection.scalar(select(VideoBudgetRow.exposure_microusd))) == 12345

            def roundtrip(sync):
                migration.downgrade()
                assert not tables & set(inspect(sync).get_table_names())
                migration.upgrade()
                assert tables <= set(inspect(sync).get_table_names())

            await connection.run_sync(roundtrip)
    finally:
        await engine.dispose()
