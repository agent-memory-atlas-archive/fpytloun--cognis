from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cognis.ui_assets import SPAMiddleware


async def _unused_app(
    scope, receive, send
) -> None:  # pragma: no cover - not called by these unit tests
    raise AssertionError("app should not be called")


def _middleware(directory: Path) -> SPAMiddleware:
    return SPAMiddleware(_unused_app, directory=directory)


def test_spa_static_service_worker_is_not_http_cached(tmp_path: Path) -> None:
    (tmp_path / "service-worker.js").write_text("self.skipWaiting();", encoding="utf-8")

    response = _middleware(tmp_path)._resolve_file("/service-worker.js")

    assert response is not None
    assert response.headers["cache-control"] == "no-cache"


def test_spa_static_html_shell_is_not_http_cached(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")

    response = _middleware(tmp_path)._resolve_file("/")

    assert response is not None
    assert response.headers["cache-control"] == "no-cache"


def test_spa_static_immutable_assets_use_long_cache(tmp_path: Path) -> None:
    asset = tmp_path / "_app" / "immutable" / "entry" / "app.abc123.js"
    asset.parent.mkdir(parents=True)
    asset.write_text("console.log('ok');", encoding="utf-8")

    response = _middleware(tmp_path)._resolve_file("/_app/immutable/entry/app.abc123.js")

    assert response is not None
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_bundled_ui_does_not_shadow_inference_routes(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>UI shell</html>")
    app = FastAPI()

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": []}

    app.add_middleware(SPAMiddleware, directory=tmp_path)
    with TestClient(app) as client:
        assert client.get("/v1/models").json() == {"object": "list", "data": []}
        assert client.get("/v1/missing").status_code == 404
        assert "UI shell" in client.get("/settings").text


def _write_with_sidecars(path: Path, content: bytes) -> None:
    import gzip

    import brotli

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.with_name(path.name + ".br").write_bytes(brotli.compress(content))
    path.with_name(path.name + ".gz").write_bytes(gzip.compress(content))


def test_spa_serves_precompressed_sidecars_by_client_preference(tmp_path: Path) -> None:
    content = b"console.log('cognis');" * 200
    asset = tmp_path / "_app" / "immutable" / "chunks" / "app.abc123.js"
    _write_with_sidecars(asset, content)
    (tmp_path / "index.html").write_text("<html>UI shell</html>")
    app = FastAPI()
    app.add_middleware(SPAMiddleware, directory=tmp_path)
    url = "/_app/immutable/chunks/app.abc123.js"

    with TestClient(app) as client:
        br = client.get(url, headers={"Accept-Encoding": "gzip, br"})
        assert br.headers["content-encoding"] == "br"
        assert br.headers["vary"] == "Accept-Encoding"
        assert br.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert "javascript" in br.headers["content-type"]
        assert br.content == content

        gz = client.get(url, headers={"Accept-Encoding": "gzip, br;q=0"})
        assert gz.headers["content-encoding"] == "gzip"
        assert gz.content == content

        identity = client.get(url, headers={"Accept-Encoding": "identity"})
        assert "content-encoding" not in identity.headers
        assert identity.content == content

        ranged = client.get(url, headers={"Accept-Encoding": "br", "Range": "bytes=0-9"})
        assert "content-encoding" not in ranged.headers
        assert ranged.content == content[:10]


def test_spa_does_not_shadow_files_ending_with_sidecar_suffix(tmp_path: Path) -> None:
    (tmp_path / "plain.txt").write_text("hello")
    response = _middleware(tmp_path)._resolve_file("/plain.txt", accept_encoding="br, gzip")
    assert response is not None
    assert "content-encoding" not in response.headers
    assert "vary" not in response.headers
