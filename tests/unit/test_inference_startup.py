"""Managed inference startup and migration acceptance."""

from __future__ import annotations

import importlib
import os

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
async def test_inference_migration_is_idempotent(tmp_path, backend):
    url = f"sqlite+aiosqlite:///{tmp_path}/migration.db"
    if backend == "postgresql":
        url = os.environ.get("COGNIS_E2E_POSTGRES_URL")
        if not url:
            pytest.skip("Set COGNIS_E2E_POSTGRES_URL to a task-owned disposable database")
    migration = importlib.import_module("cognis.store.migrations.versions.153_inference_companions")
    engine = create_async_engine(url)

    def verify(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
            columns = {
                column["name"] for column in inspect(connection).get_columns("inference_companions")
            }
            assert {
                "service",
                "enabled",
                "token_version",
                "embedding_reference",
                "embedding_dimensions",
            } <= columns
            migration.downgrade()
            assert "inference_companions" not in inspect(connection).get_table_names()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(verify)
    finally:
        await engine.dispose()


def test_control_plane_boots_without_companions_or_routes(monkeypatch, tmp_path):
    from cognis.api.app import create_app

    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path / "controller"))
    monkeypatch.setenv("COGNIS_INFERENCE_CREDENTIAL_DIR", str(tmp_path / "credentials"))
    monkeypatch.setenv("COGNIS_MNEMORY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("COGNIS_INTARIS_URL", "http://127.0.0.1:1")
    app = create_app()
    with TestClient(app) as client:
        token = (tmp_path / "credentials/intaris/token.jwt").read_text().strip()
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model": "routes/intaris_evaluation",
                "messages": [{"role": "user", "content": "startup check"}],
            },
        )
        assert response.status_code == 503, response.text
        assert client.get("/.well-known/jwks.json").status_code == 200
