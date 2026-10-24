from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup
from fastapi import FastAPI
from starlette.testclient import TestClient

from cognis.api.authentication import AuthenticatedUser
from cognis.api.routes import artifacts, deliverables
from cognis.core.content_refs import get_deliverable_ref_unscoped
from cognis.core.deliverable_links import (
    DeliverableShareUnavailable,
    signed_deliverable_view_link,
    verify_deliverable_share_token,
)

pytest_plugins = ("tests.unit.test_task_continuation_tools",)


def _client(factory, email: str | None = None, role: str = "user") -> TestClient:
    app = FastAPI()
    app.include_router(artifacts.router)
    app.include_router(deliverables.router)
    app.state.session_factory = factory
    app.state.artifact_store = factory.artifact_store
    if email:

        @app.middleware("http")
        async def authenticate(request, call_next):
            request.state.user = AuthenticatedUser(email=email, role=role)
            return await call_next(request)

    return TestClient(app)


@pytest.mark.asyncio
async def test_virtual_view_redirects_to_original_document_without_renewal(
    task_continuation_db, monkeypatch
) -> None:
    factory = task_continuation_db
    store = factory.artifact_store
    async with factory() as session:
        ref = await get_deliverable_ref_unscoped(session, store, "dlv_owner")
    assert ref is not None
    signed = store.get_public_url(
        "deliverables", "dlv_owner", ref.filename, ttl_seconds=60, mode="view"
    )
    signed = signed.replace(
        "/artifacts/view/deliverables/", "/artifacts/virtual/deliverables/view/"
    )
    original_exp = int(parse_qs(urlsplit(signed).query)["exp"][0])
    monkeypatch.setattr(deliverables, "_standalone_assets_available", lambda request: False)
    client = _client(factory)
    redirect = client.get(signed, follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["cache-control"] == "no-store"
    token = redirect.headers["location"].rsplit("/", 1)[1]
    assert verify_deliverable_share_token(store, token) == ("dlv_owner", original_exp)
    page = client.get(redirect.headers["location"])
    assert page.status_code == 200
    assert ref.deliverable.title in page.text
    assert ref.filename not in BeautifulSoup(page.text, "html.parser").title.get_text()
    assert (
        client.get(signed.replace("sig=", "sig=wrong"), follow_redirects=False).status_code == 403
    )
    download = store.get_public_url(
        "deliverables", "dlv_owner", ref.filename, ttl_seconds=60, mode="download"
    )
    download = download.replace(
        "/artifacts/content/deliverables/", "/artifacts/virtual/deliverables/"
    )
    assert client.get(download).content == ref.content_bytes
    assert client.get(download.replace("/deliverables/", "/deliverables/view/")).status_code == 403


@pytest.mark.parametrize("remaining", [1, 59, 60, 300])
def test_share_conversion_preserves_exact_expiry(task_continuation_db, remaining) -> None:
    store = task_continuation_db.artifact_store
    expires_at = int(time.time()) + remaining
    link = signed_deliverable_view_link(
        store, "dlv_owner", base_url="http://testserver", expires_at=expires_at
    )
    assert verify_deliverable_share_token(store, link.url.rsplit("/", 1)[1]) == (
        "dlv_owner",
        expires_at,
    )
    with pytest.raises(DeliverableShareUnavailable, match="expired"):
        signed_deliverable_view_link(
            store, "dlv_owner", base_url="http://testserver", expires_at=int(time.time()) - 1
        )


def test_owner_context_requires_actual_ownership(task_continuation_db) -> None:
    assert _client(task_continuation_db, "owner@example.com").get(
        "/api/v1/deliverables/dlv_owner/viewer-context"
    ).json() == {"share_link_url": "/api/v1/deliverables/dlv_owner/share-link"}
    assert (
        _client(task_continuation_db)
        .get("/api/v1/deliverables/dlv_owner/viewer-context")
        .status_code
        == 401
    )
    assert (
        _client(task_continuation_db, "other@example.com", "admin")
        .get("/api/v1/deliverables/dlv_owner/viewer-context")
        .status_code
        == 404
    )


@pytest.mark.asyncio
async def test_expired_links_recover_only_through_authenticated_owner_access(
    task_continuation_db, monkeypatch
) -> None:
    store = task_continuation_db.artifact_store
    now = int(time.time())
    with monkeypatch.context() as clock:
        clock.setattr("cognis.core.deliverable_links.time.time", lambda: now - 120)
        token = signed_deliverable_view_link(
            store, "dlv_owner", base_url="http://testserver", ttl_seconds=60
        ).url.rsplit("/", 1)[1]
    path = f"/api/v1/deliverables/share/{token}/view"
    monkeypatch.setattr(deliverables, "_standalone_assets_available", lambda request: False)
    assert _client(task_continuation_db).get(path).status_code == 404
    owner = _client(task_continuation_db, "owner@example.com")
    owner.cookies.set("cognis_session", "test-session")
    redirect = owner.get(path, follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/api/v1/deliverables/dlv_owner/view?expired_link=true"
    assert owner.get(redirect.headers["location"]).status_code == 200
    other = _client(task_continuation_db, "other@example.com", "admin")
    other.cookies.set("cognis_session", "test-session")
    assert other.get(path).status_code == 404
    assert owner.get(f"/api/v1/deliverables/share/{token}/download.md").status_code == 404
    assert (
        owner.get(path.replace(token, token[:-3] + "abc"), follow_redirects=False).status_code
        == 404
    )


@pytest.mark.parametrize("days", [1, 7, 30, 90])
def test_share_expiry_presets(task_continuation_db, days) -> None:
    client = _client(task_continuation_db, "owner@example.com")
    now = int(time.time())
    result = client.post(
        "/api/v1/deliverables/dlv_owner/share-link", json={"ttl_seconds": days * 86400}
    )
    assert result.status_code == 200
    _, expiration = verify_deliverable_share_token(
        task_continuation_db.artifact_store, result.json()["url"].rsplit("/", 1)[1]
    )
    assert now + days * 86400 <= expiration <= now + days * 86400 + 2


def test_custom_expiry_validation(task_continuation_db) -> None:
    client = _client(task_continuation_db, "owner@example.com")
    path = "/api/v1/deliverables/dlv_owner/share-link"
    date = datetime.now(UTC) + timedelta(days=2)
    result = client.post(path, json={"expires_at": date.isoformat()})
    assert result.status_code == 200
    _, expiration = verify_deliverable_share_token(
        task_continuation_db.artifact_store, result.json()["url"].rsplit("/", 1)[1]
    )
    assert expiration == int(date.timestamp())
    for value in [
        {"ttl_seconds": 0},
        {"ttl_seconds": 91 * 86400},
        {"expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat()},
        {"expires_at": date.replace(tzinfo=None).isoformat()},
        {"expires_at": date.isoformat(), "ttl_seconds": 86400},
    ]:
        assert client.post(path, json=value).status_code == 422


def test_readonly_owner_cannot_publish_new_share_links(task_continuation_db) -> None:
    client = _client(task_continuation_db, "owner@example.com", "viewer")
    assert client.get("/api/v1/deliverables/dlv_owner/viewer-context").status_code == 403
    assert (
        client.post(
            "/api/v1/deliverables/dlv_owner/share-link", json={"ttl_seconds": 86400}
        ).status_code
        == 403
    )
