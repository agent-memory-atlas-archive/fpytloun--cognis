"""Upgrade optional task deadlines from a previous-schema fixture."""

from __future__ import annotations

import importlib
import os
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from cognis.bootstrap import _ensure_task_escalation_timeout_column


@pytest.mark.parametrize("upgrade_path", ["bootstrap", "alembic"])
async def test_task_escalation_timeout_schema_upgrade(tmp_path, upgrade_path):
    url = os.environ.get("COGNIS_TEST_POSTGRES_URL")
    schema = f"task_timeout_{uuid.uuid4().hex}"
    admin = None
    if url:
        admin = create_async_engine(url)
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/schema.db")

    def exercise(conn):
        conn.execute(text("CREATE TABLE tasks (task_id VARCHAR PRIMARY KEY)"))
        conn.execute(text("INSERT INTO tasks (task_id) VALUES ('existing-task')"))
        migration = importlib.import_module(
            "cognis.store.migrations.versions.151_task_escalation_timeout"
        )
        if upgrade_path == "bootstrap":
            _ensure_task_escalation_timeout_column(conn)
            _ensure_task_escalation_timeout_column(conn)
        else:
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
        assert {column["name"] for column in inspect(conn).get_columns("tasks")} == {
            "task_id",
            "escalation_timeout_seconds",
        }
        assert conn.execute(
            text("SELECT task_id, escalation_timeout_seconds FROM tasks")
        ).one() == ("existing-task", None)
        if upgrade_path == "alembic":
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()
            assert {column["name"] for column in inspect(conn).get_columns("tasks")} == {"task_id"}

    try:
        async with engine.begin() as conn:
            await conn.run_sync(exercise)
    finally:
        await engine.dispose()
        if admin is not None:
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()
