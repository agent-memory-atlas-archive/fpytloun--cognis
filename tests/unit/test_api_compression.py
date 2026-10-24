from __future__ import annotations

import gzip

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from cognis.api.compression import BufferedGZipMiddleware


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/big")
    def big() -> JSONResponse:
        return JSONResponse({"items": ["x" * 40] * 200})

    @app.get("/small")
    def small() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/stream")
    def stream() -> StreamingResponse:
        async def chunks():
            for _ in range(3):
                yield b"data: " + b"y" * 2000 + b"\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    @app.get("/ndjson")
    def ndjson() -> StreamingResponse:
        async def chunks():
            for _ in range(3):
                yield b'{"a":"' + b"z" * 2000 + b'"}\n'

        return StreamingResponse(chunks(), media_type="application/json")

    @app.get("/binary")
    def binary() -> StreamingResponse:
        return StreamingResponse(iter([b"\x00" * 5000]), media_type="image/png")

    app.add_middleware(BufferedGZipMiddleware)
    return app


def _raw_get(client: TestClient, path: str, encoding: str = "gzip"):
    return client.get(path, headers={"Accept-Encoding": encoding})


def test_compresses_large_buffered_json() -> None:
    with TestClient(_app()) as client:
        response = _raw_get(client, "/big")
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    assert response.json()["items"][0] == "x" * 40


def test_skips_small_bodies_and_clients_without_gzip() -> None:
    with TestClient(_app()) as client:
        assert "content-encoding" not in _raw_get(client, "/small").headers
        assert "content-encoding" not in _raw_get(client, "/big", "identity").headers
        assert "content-encoding" not in _raw_get(client, "/big", "gzip;q=0").headers


def test_streaming_responses_pass_through_uncompressed() -> None:
    with TestClient(_app()) as client:
        sse = _raw_get(client, "/stream")
        ndjson = _raw_get(client, "/ndjson")
        binary = _raw_get(client, "/binary")
    assert "content-encoding" not in sse.headers
    assert sse.text.count("data: ") == 3
    assert "content-encoding" not in ndjson.headers
    assert ndjson.text.count("\n") == 3
    assert "content-encoding" not in binary.headers


def test_gzip_body_round_trips() -> None:
    body = b'{"k":"' + b"v" * 4000 + b'"}'

    async def raw_app(scope, receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json"), (b"etag", b'"abc"')],
            }
        )
        await send({"type": "http.response.body", "body": body})

    app = BufferedGZipMiddleware(raw_app)
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    import asyncio

    asyncio.run(
        app(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [(b"accept-encoding", b"br, gzip")],
            },
            receive,
            send,
        )
    )
    headers = dict(sent[0]["headers"])
    assert headers[b"content-encoding"] == b"gzip"
    assert headers[b"etag"] == b'W/"abc"'
    assert gzip.decompress(sent[1]["body"]) == body
    assert int(headers[b"content-length"]) == len(sent[1]["body"])


def test_real_app_stack_compresses_buffered_api_json(monkeypatch, tmp_path) -> None:
    """Guard middleware order: BaseHTTPMiddleware layers must not hide bodies."""

    from tests.unit.test_app_auth import _create_test_client, _login, _seed_user

    with _create_test_client(monkeypatch, tmp_path) as client:
        _seed_user(client)
        _login(client)
        response = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "gzip"
        assert "paths" in response.json()


def _conditional_app():
    from cognis.api.compression import ConditionalJsonGetMiddleware

    app = FastAPI()
    state = {"items": ["a", "b"]}

    @app.get("/api/v1/agents")
    def agents() -> JSONResponse:
        return JSONResponse({"items": state["items"]})

    @app.get("/api/v1/other")
    def other() -> JSONResponse:
        return JSONResponse({"items": state["items"]})

    @app.get("/api/v1/user-preferences")
    def prefs() -> JSONResponse:
        return JSONResponse({"x": 1}, headers={"Cache-Control": "no-store"})

    app.add_middleware(ConditionalJsonGetMiddleware)
    app.add_middleware(BufferedGZipMiddleware)
    return app, state


def test_conditional_get_returns_304_for_unchanged_list_and_200_after_change() -> None:
    app, state = _conditional_app()
    with TestClient(app) as client:
        first = client.get("/api/v1/agents")
        etag = first.headers["etag"]
        assert etag.startswith('W/"')
        assert first.headers["cache-control"] == "private, no-cache"

        unchanged = client.get("/api/v1/agents", headers={"If-None-Match": etag})
        assert unchanged.status_code == 304
        assert unchanged.content == b""
        assert unchanged.headers["etag"] == etag

        state["items"] = ["a", "b", "c"]
        changed = client.get("/api/v1/agents", headers={"If-None-Match": etag})
        assert changed.status_code == 200
        assert changed.json()["items"] == ["a", "b", "c"]
        assert changed.headers["etag"] != etag


def test_conditional_get_skips_other_paths_and_explicit_cache_policies() -> None:
    app, _state = _conditional_app()
    with TestClient(app) as client:
        assert "etag" not in client.get("/api/v1/other").headers
        prefs = client.get("/api/v1/user-preferences")
        assert "etag" not in prefs.headers
        assert prefs.headers["cache-control"] == "no-store"
