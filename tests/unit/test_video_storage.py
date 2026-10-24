"""Migration and HTTP range checks independent of provider APIs."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from cognis.api.routes.artifacts import _serve_signed_artifact
from cognis.artifacts.store import ArtifactStore, ArtifactStoreConfig


def test_video_migration_up_and_down_repeat(tmp_path):
    migration = importlib.import_module("cognis.store.migrations.versions.167_video_provider_jobs")
    engine = sa.create_engine(f"sqlite:///{tmp_path}/migration.db")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        for _ in range(2):
            migration.upgrade()
            inspector = sa.inspect(connection)
            assert {
                "video_jobs",
                "video_attempts",
                "video_budgets",
                "video_mutations",
                "video_transfers",
            } <= set(inspector.get_table_names())
            columns = {column["name"] for column in inspector.get_columns("video_attempts")}
            assert {"version", "dispatched", "result"} <= columns
            migration.downgrade()
    engine.dispose()


def test_http_video_stream_ranges_preserve_original(tmp_path, monkeypatch):
    store = ArtifactStore(
        ArtifactStoreConfig(
            path=str(tmp_path),
            signing_secret="range-test",
            base_url="https://cognis.test",
        )
    )
    content = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256))
    store.save("videos", "range-video", "movie.mp4", content, content_type="video/mp4")
    app = FastAPI()
    session = AsyncMock()
    app.state.session_factory = lambda: session
    app.state.artifact_store = store
    record = SimpleNamespace(
        namespace="videos",
        object_id="range-video",
        filename="movie.mp4",
        mime_type="video/mp4",
        size_bytes=len(content),
        status="saved",
        expires_at=None,
    )
    monkeypatch.setattr(
        "cognis.api.routes.artifacts.get_artifact_record", AsyncMock(return_value=record)
    )
    query = parse_qs(
        urlsplit(store.get_public_url("videos", "range-video", "movie.mp4", mode="view")).query
    )

    @app.get("/video")
    async def video(request: Request):
        return await _serve_signed_artifact(
            request,
            namespace="videos",
            object_id="range-video",
            filename="movie.mp4",
            exp=int(query["exp"][0]),
            sig=query["sig"][0],
            mode="view",
        )

    with TestClient(app) as client:
        response = client.get("/video")
        assert response.status_code == 200 and response.content == content
        response = client.get("/video", headers={"Range": "bytes=10-20"})
        assert response.status_code == 206 and response.content == content[10:21]
        assert response.headers["content-range"] == f"bytes 10-20/{len(content)}"
        response = client.get("/video", headers={"Range": "bytes=99999-"})
        assert response.status_code == 416
