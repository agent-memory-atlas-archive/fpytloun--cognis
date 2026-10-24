"""Runtime capture invariants and real Redis command/CAS integration."""

import asyncio
import os
import tracemalloc
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from cognis.api.authentication import AuthenticatedUser
from cognis.api.routes.profiling import router
from cognis.core.profiling_capture import AllocationCapture, CaptureOptions, LocalCapture
from cognis.core.profiling_control import ACTIVE, PREFIX, ProfilingConflict, ProfilingControl
from cognis.core.redis_service import RedisService, RedisUnavailableError


@pytest.mark.asyncio
async def test_local_light_capture_restart_stop_and_no_tracer() -> None:
    before = tracemalloc.is_tracing()
    for _ in range(2):
        capture = LocalCapture(str(uuid4()), CaptureOptions(level="light"), lambda: {"sessions": 0})
        capture.start()
        await asyncio.sleep(0.01)
        await capture.stop()
        assert capture.state == "stopped"
        assert capture.report["resources"]["cpu"] is None
        assert not capture.owned_tracing
        assert tracemalloc.is_tracing() == before


@pytest.mark.asyncio
async def test_full_capture_preserves_external_tracer() -> None:
    if tracemalloc.is_tracing():
        pytest.skip("requires an unowned process tracer")
    tracemalloc.start()
    try:
        capture = LocalCapture(str(uuid4()), CaptureOptions(level="full"), lambda: {})
        capture.start()
        await capture.task
        assert capture.state == "failed"
        assert tracemalloc.is_tracing()
        assert not capture.owned_tracing
    finally:
        tracemalloc.stop()


def test_allocation_report_does_not_expose_content() -> None:
    capture = AllocationCapture(1)
    capture.start()
    try:
        secret = ["never-expose-this-payload" * 100 for _ in range(100)]
        report = capture.sample()
        assert report["python_bytes"] > 0
        assert "never-expose" not in str(report)
        del secret
        assert capture.sample()["delta"]
    finally:
        capture.stop()
    assert not capture.previous
    assert not tracemalloc.is_tracing()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,auth_type", [("viewer", "api_key"), ("user", "jwt"), (None, None)])
async def test_all_routes_require_admin(role, auth_type) -> None:
    app = FastAPI()
    app.include_router(router)
    if role:

        @app.middleware("http")
        async def auth(request, call_next):
            request.state.user = AuthenticatedUser("reader@example.test", role, auth_type=auth_type)
            return await call_next(request)

    app.state.profiling_control = Mock()
    capture_id = str(uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for method, path, body in [
            ("GET", "", None),
            ("POST", "/captures", {"capture_id": capture_id}),
            ("GET", f"/captures/{capture_id}", None),
            ("GET", f"/captures/{capture_id}/report", None),
            ("POST", f"/captures/{capture_id}/stop", None),
        ]:
            response = await client.request(method, "/api/v1/system/profiling" + path, json=body)
            assert response.status_code == (403 if role else 401)
    assert not app.state.profiling_control.mock_calls


@pytest.mark.asyncio
async def test_admin_api_key_routes_and_response_contract() -> None:
    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def auth(request, call_next):
        request.state.user = AuthenticatedUser("admin@example.test", "admin", auth_type="api_key")
        return await call_next(request)

    service = Mock()
    service.admit = AsyncMock(return_value={"meta": {}, "desired": "start", "controllers": {}})
    app.state.profiling_control = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/system/profiling/captures", json={"capture_id": str(uuid4())}
        )
        assert response.status_code == 202
        assert response.json()["version"] == 1
        response = await client.post(
            "/api/v1/system/profiling/captures",
            json={
                "capture_id": str(uuid4()),
                "options": {"duration_seconds": 99999},
            },
        )
        assert response.status_code == 422
        service.admit.side_effect = RedisUnavailableError()
        response = await client.post(
            "/api/v1/system/profiling/captures", json={"capture_id": str(uuid4())}
        )
        assert response.status_code == 503


@pytest.fixture
async def redis_service():
    url = os.getenv("COGNIS_TEST_PROFILING_REDIS_URL")
    if not url:
        pytest.skip("set COGNIS_TEST_PROFILING_REDIS_URL to a disposable Redis database")
    if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("profiling Redis fixture must be disposable and loopback-only")
    redis = RedisService(url)
    assert await redis.ping()
    # Never use this fixture with production. Clean only the profiling test DB.
    await redis.eval("return redis.call('FLUSHDB')")
    try:
        yield redis
    finally:
        await redis.eval("return redis.call('FLUSHDB')")
        await redis.aclose()


def controllers(redis_service):
    owners = ["controller-a:incarnation-a", "controller-b:incarnation-b"]
    directory = SimpleNamespace(list_ready_owners=AsyncMock(return_value=owners))
    return [
        ProfilingControl(redis_service, directory, owner, lambda: {"sessions": 0})
        for owner in owners
    ]


@pytest.mark.asyncio
async def test_ha_start_retry_stop_and_reports_through_other_replica(redis_service) -> None:
    a, b = controllers(redis_service)
    capture_id = str(uuid4())
    options = CaptureOptions(level="light")
    accepted = await a.admit(capture_id, options, None)
    assert len(accepted["controllers"]) == 2
    assert all(row["state"] == "pending" for row in accepted["controllers"].values())
    await asyncio.gather(a.reconcile(), b.reconcile())
    await asyncio.sleep(0.02)
    retry = await b.admit(capture_id, options, None)
    assert retry["meta"] == accepted["meta"]
    with pytest.raises(ProfilingConflict):
        await a.admit(capture_id, CaptureOptions(level="cpu"), None)
    with pytest.raises(ProfilingConflict):
        await b.admit(str(uuid4()), options, None)
    await a.request_stop(capture_id)
    await asyncio.gather(a.reconcile(), b.reconcile())
    final = await b.read(capture_id)
    assert all(row["state"] == "stopped" for row in final["controllers"].values())
    assert len(final["reports"]) == 2
    assert all(not row["owned_tracing"] for row in final["controllers"].values())
    tasks = [a.local.task, b.local.task]
    await asyncio.gather(a.reconcile(), b.reconcile())
    assert tasks == [a.local.task, b.local.task]
    next_id = str(uuid4())
    await a.admit(next_id, options, None)
    await a.request_stop(capture_id)  # Late stop must not stop successor.
    await asyncio.gather(a.reconcile(), b.reconcile())
    await asyncio.sleep(0.01)
    assert a.local.capture_id == next_id and a.local.state == "running"
    await a.stop()
    await b.stop()


@pytest.mark.asyncio
async def test_stop_before_start_and_incarnation_fencing(redis_service) -> None:
    a, b = controllers(redis_service)
    capture_id = str(uuid4())
    await a.admit(capture_id, CaptureOptions(), None)
    replacement = ProfilingControl(redis_service, a.directory, "controller-a:replacement", Mock())
    await replacement.reconcile()
    assert replacement.local is None
    await b.request_stop(capture_id)
    await asyncio.gather(a.reconcile(), b.reconcile())
    assert a.local.state == b.local.state == "stopped"
    assert a.local.task is b.local.task is None


@pytest.mark.asyncio
async def test_lost_write_response_retry_and_report_retention(redis_service, monkeypatch) -> None:
    a, b = controllers(redis_service)
    capture_id = str(uuid4())
    original = a._eval
    lost = False

    async def ambiguous(script, keys, args):
        nonlocal lost
        result = await original(script, keys, args)
        if keys and keys[0] == ACTIVE and not lost:
            lost = True
            raise RedisUnavailableError()
        return result

    monkeypatch.setattr(a, "_eval", ambiguous)
    with pytest.raises(RedisUnavailableError):
        await a.admit(capture_id, CaptureOptions(), None)
    assert (await b.admit(capture_id, CaptureOptions(), None))["meta"]["capture_id"] == capture_id
    for _ in range(5):
        await a.request_stop(capture_id)
        await asyncio.gather(a.reconcile(), b.reconcile())
        capture_id = str(uuid4())
        await a.admit(capture_id, CaptureOptions(), None)
    keys = await redis_service.eval(
        "return redis.call('KEYS', ARGV[1])", args=[PREFIX + "capture:*"]
    )
    assert len(keys) == 4
    await a.request_stop(capture_id)
    await asyncio.gather(a.reconcile(), b.reconcile())
    await a.stop()
    await b.stop()


@pytest.mark.asyncio
async def test_redis_outage_is_not_reported_as_disabled() -> None:
    redis = Mock(
        available=False, get=AsyncMock(return_value=None), eval=AsyncMock(return_value=None)
    )
    directory = SimpleNamespace(list_ready_owners=AsyncMock(return_value=[]))
    service = ProfilingControl(redis, directory, "owner:incarnation", Mock())
    with pytest.raises(RedisUnavailableError):
        await service.reconcile()
    with pytest.raises(RedisUnavailableError):
        await service.read(str(uuid4()))


def test_legacy_boot_selection_and_snapshot_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("COGNIS_PROFILING_BOOT_LEVEL", raising=False)
    monkeypatch.delenv("COGNIS_PROFILING_BOOT_POD", raising=False)
    monkeypatch.setenv("COGNIS_MEMORY_PROFILING", "true")
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_POD", "selected")
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_SNAPSHOTS", "false")
    monkeypatch.setenv("COGNIS_RESOURCE_PROFILING", "false")
    monkeypatch.setattr("socket.gethostname", lambda: "selected")
    control = ProfilingControl(Mock(), Mock(), "selected:incarnation", Mock())
    assert control.boot_targets == ["selected:incarnation"]
    assert control.boot_options.level == "allocations"
    assert not control.boot_options.allocation_snapshots
    monkeypatch.setattr("socket.gethostname", lambda: "other")
    assert ProfilingControl(Mock(), Mock(), "other:incarnation", Mock()).boot_options is None


def test_counters_mode_never_takes_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(tracemalloc, "take_snapshot", Mock(side_effect=AssertionError("expensive")))
    assert AllocationCapture(1).sample(False)["snapshots"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_before_reconcile", [True, False])
async def test_publish_unreported_predecessor_before_successor(
    redis_service, monkeypatch, finish_before_reconcile
) -> None:
    a, b = controllers(redis_service)
    capture_id = str(uuid4())
    await a.admit(capture_id, CaptureOptions(level="light"), None)
    await a.reconcile()
    await asyncio.sleep(0.01)
    if finish_before_reconcile:
        await a.local.stop()
    # Model completion while Redis was unavailable, then expiration of active lease.
    await redis_service.delete(ACTIVE)
    successor = str(uuid4())
    await b.admit(successor, CaptureOptions(level="light"), None)
    previous = a.local
    publish = a._publish
    monkeypatch.setattr(a, "_publish", AsyncMock(side_effect=RedisUnavailableError()))
    with pytest.raises(RedisUnavailableError):
        await a.reconcile()
    assert a.local is previous
    monkeypatch.setattr(a, "_publish", publish)
    await a.reconcile()
    assert a.local.capture_id == successor
    old = await b.read(capture_id)
    assert old["controllers"][a.owner_id]["state"] == "stopped"
    assert a.owner_id in old["reports"]
    await a.stop()
    await b.stop()
