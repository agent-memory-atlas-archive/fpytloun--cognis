from __future__ import annotations

import importlib
import os
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from cognis.bootstrap import _ensure_notification_inbox


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize("upgrade_path", ["bootstrap", "alembic", "bootstrap_then_alembic"])
async def test_inbox_schema_upgrade_is_idempotent(tmp_path, backend, upgrade_path):
    admin = None
    schema = f"inbox_schema_{uuid.uuid4().hex}"
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
        conn.execute(text("CREATE TABLE users (email VARCHAR PRIMARY KEY)"))
        conn.execute(text("INSERT INTO users (email) VALUES ('existing@example.com')"))
        migration = importlib.import_module(
            "cognis.store.migrations.versions.156_notification_inbox"
        )
        if upgrade_path != "alembic":
            _ensure_notification_inbox(conn)
            _ensure_notification_inbox(conn)
        if upgrade_path != "bootstrap":
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                migration.upgrade()
        assert {column["name"] for column in inspect(conn).get_columns("inbox_notifications")} == {
            "notification_id",
            "user_email",
            "kind",
            "title",
            "body",
            "href",
            "created_at",
            "read_at",
        }
        assert {index["name"] for index in inspect(conn).get_indexes("inbox_notifications")} == {
            "ix_inbox_user_created",
            "ix_inbox_user_read",
        }
        assert conn.execute(text("SELECT email FROM users")).scalar_one() == "existing@example.com"
        if upgrade_path != "bootstrap":
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()
                migration.downgrade()
            assert "inbox_notifications" not in inspect(conn).get_table_names()

    try:
        async with engine.begin() as conn:
            await conn.run_sync(exercise)
    finally:
        await engine.dispose()
        if admin is not None:
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()
