from __future__ import annotations

import importlib

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect

from cognis.bootstrap import run_schema_bootstrap
from cognis.store.database import create_engine
from cognis.store.models import DocumentFavorite


@pytest.mark.asyncio
async def test_document_favorites_bootstrap_and_migration_are_idempotent(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'favorites.db'}")
    migration = importlib.import_module("cognis.store.migrations.versions.166_document_favorites")
    try:
        await run_schema_bootstrap(engine)
        await run_schema_bootstrap(engine)
        async with engine.begin() as connection:

            def exercise(sync):
                monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(sync)))
                migration.upgrade()
                DocumentFavorite.__table__.drop(sync)
                migration.upgrade()
                migration.upgrade()
                return inspect(sync).get_pk_constraint("document_favorites")

            primary_key = await connection.run_sync(exercise)
        assert primary_key["constrained_columns"] == ["user_email", "kind", "lineage_id"]
    finally:
        await engine.dispose()
