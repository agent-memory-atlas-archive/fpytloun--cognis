"""Both schema evolution paths preserve unknown historical provenance."""

from __future__ import annotations

import importlib
import os
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from cognis.bootstrap import _ensure_workflow_creation_origin


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize("upgrade_path", ["bootstrap", "alembic", "bootstrap_then_alembic"])
async def test_origin_migration(tmp_path, backend, upgrade_path):
    admin = None
    schema = f"workflow_origin_{uuid.uuid4().hex}"
    if backend == "postgres":
        url = os.environ.get("COGNIS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("COGNIS_TEST_POSTGRES_URL is not configured")
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        admin = create_async_engine(url)
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/schema.db")

    def exercise(conn):
        for table in ("tasks", "schedules"):
            conn.execute(text(f"CREATE TABLE {table} (id VARCHAR PRIMARY KEY)"))
            conn.execute(text(f"INSERT INTO {table} (id) VALUES ('historical')"))
        migration = importlib.import_module(
            "cognis.store.migrations.versions.157_workflow_creation_origin"
        )
        if upgrade_path != "alembic":
            _ensure_workflow_creation_origin(conn)
            _ensure_workflow_creation_origin(conn)
        if upgrade_path != "bootstrap":
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                migration.upgrade()
        for table in ("tasks", "schedules"):
            assert conn.execute(text(f"SELECT creation_origin FROM {table}")).scalar_one() is None
            conn.execute(text(f"UPDATE {table} SET creation_origin='owner_configured'"))
        _ensure_workflow_creation_origin(conn)
        for table in ("tasks", "schedules"):
            assert (
                conn.execute(text(f"SELECT creation_origin FROM {table}")).scalar_one()
                == "owner_configured"
            )
        if upgrade_path != "bootstrap":
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()
            for table in ("tasks", "schedules"):
                assert "creation_origin" not in {
                    c["name"] for c in inspect(conn).get_columns(table)
                }
                assert conn.execute(text(f"SELECT id FROM {table}")).scalar_one() == "historical"

    try:
        async with engine.begin() as conn:
            await conn.run_sync(exercise)
    finally:
        await engine.dispose()
        if admin is not None:
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()
