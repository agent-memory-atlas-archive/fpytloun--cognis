"""Offline lifecycle tests: no provider credentials or billable calls."""

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from cognis.artifacts.store import ArtifactStore, ArtifactStoreConfig
from cognis.core.video import VideoService
from cognis.models.video import (
    VideoJobCreate,
    VideoMutation,
    VideoOutput,
    VideoRemoteResult,
    VideoRequest,
    VideoSpendPolicy,
)
from cognis.providers.video import VideoConnection, VideoHTTPAdapter
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import Base, VideoBudgetRow
from cognis.store.video_jobs import job_view


@pytest_asyncio.fixture
async def service(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/video.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = VideoService(
        session_factory=create_session_factory(engine),
        artifacts=ArtifactStore(
            ArtifactStoreConfig(
                path=str(tmp_path / "artifacts"),
                base_url="https://cognis.test",
                signing_secret="test-signature",
            )
        ),
        llm=None,
    )
    service.context = AsyncMock(
        return_value=SimpleNamespace(
            conversation_id="video-conversation",
            agent_id="video-agent",
            project_id=None,
        )
    )
    service.connection = AsyncMock(
        return_value=(
            VideoConnection(
                adapter="veo",
                model="veo-3.1-generate-preview",
                api_key="test-key",
                base_url="https://generativelanguage.googleapis.com/v1beta",
            ),
            {
                "provider_id": "google",
                "model": "veo-3.1-generate-preview",
                "adapter": "veo",
                "runtime": "controller",
            },
        )
    )
    service.policy = AsyncMock(
        return_value=VideoSpendPolicy(
            enabled=True,
            model_max_cost_usd={"google/veo-3.1-generate-preview": Decimal("2")},
        )
    )
    yield service
    await engine.dispose()


def create_input(key=None, **changes):
    request = VideoRequest(prompt="A waterfall", max_cost_usd=3, **changes)
    return VideoJobCreate(
        conversation_id="video-conversation",
        idempotency_key=key or uuid.uuid4().hex,
        request=request,
    )


async def step(service, job_id):
    row = await service.store.get(job_id)
    await service.advance(row)
    return await service.store.get(job_id)


@pytest.mark.asyncio
async def test_duplicate_admission_reserves_once(service):
    request = create_input()
    first = await service.create("owner@test", request)
    second = await service.create("owner@test", request)
    assert first["job_id"] == second["job_id"]
    async with service.sessions() as db:
        budgets = list(await db.scalars(select(VideoBudgetRow)))
    assert sum(row.exposure_microusd for row in budgets) == 2_000_000
    with pytest.raises(ValueError, match="different"):
        await service.create(
            "owner@test",
            request.model_copy(
                update={"request": request.request.model_copy(update={"prompt": "Different"})}
            ),
        )


@pytest.mark.asyncio
async def test_default_policy_allows_video_without_pricing_setup(service, monkeypatch):
    service.policy.return_value = VideoSpendPolicy()
    request = create_input()
    request.request.max_cost_usd = None
    job = await service.create("owner@test", request)
    assert job["estimated_cost_usd"] is None
    assert job["cost_status"] == "unknown"
    submit = AsyncMock(return_value=VideoRemoteResult(handle="operations/render", state="running"))
    monkeypatch.setattr(VideoHTTPAdapter, "submit", submit)
    await step(service, job["job_id"])
    row = await step(service, job["job_id"])
    assert row.status == "running"
    submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_request_limit_still_requires_estimate_when_budgets_off(service):
    service.policy.return_value = VideoSpendPolicy()
    with pytest.raises(ValueError, match="estimate is required"):
        await service.create("owner@test", create_input())


@pytest.mark.asyncio
async def test_opt_in_budget_cannot_ignore_unknown_previous_charges(service):
    service.policy.return_value = VideoSpendPolicy()
    request = create_input()
    request.request.max_cost_usd = None
    job = await service.create("owner@test", request)
    service.policy.return_value = VideoSpendPolicy(
        enabled=True, model_max_cost_usd={"google/veo-3.1-generate-preview": Decimal("2")}
    )
    with pytest.raises(ValueError, match="Unresolved video charges"):
        await service.create("owner@test", create_input())
    await service.store.settle(job["job_id"], 1_000_000)
    async with service.sessions() as session:
        assert (
            sum(b.exposure_microusd for b in await session.scalars(select(VideoBudgetRow)))
            == 1_000_000
        )
    assert (await service.create("owner@test", create_input()))["status"] == "queued"


@pytest.mark.asyncio
async def test_enabling_budget_before_dispatch_blocks_unpriced_job(service, monkeypatch):
    service.policy.return_value = VideoSpendPolicy()
    request = create_input()
    request.request.max_cost_usd = None
    job = await service.create("owner@test", request)
    await step(service, job["job_id"])
    service.policy.return_value = VideoSpendPolicy(enabled=True)
    submit = AsyncMock()
    monkeypatch.setattr(VideoHTTPAdapter, "submit", submit)
    assert (await step(service, job["job_id"])).status == "blocked"
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_cap_enforced_even_with_account_limits_disabled(service):
    service.policy.return_value = VideoSpendPolicy(
        enabled=False, model_max_cost_usd={"google/veo-3.1-generate-preview": Decimal("5")}
    )
    with pytest.raises(ValueError, match="per-job limit"):
        await service.create("owner@test", create_input())


@pytest.mark.asyncio
async def test_dispatch_timeout_never_resubmits(service, monkeypatch):
    submit = AsyncMock(side_effect=httpx.ReadTimeout("lost response"))
    monkeypatch.setattr(VideoHTTPAdapter, "submit", submit)
    job = await service.create("owner@test", create_input())
    await step(service, job["job_id"])
    row = await step(service, job["job_id"])
    assert row.status == "needs_reconciliation"
    await step(service, job["job_id"])
    assert submit.await_count == 1
    assert (await service.store.get(row.job_id)).cost_status == "unknown"


@pytest.mark.asyncio
async def test_crash_after_dispatch_blocks_resubmit(service, monkeypatch):
    submit = AsyncMock()
    monkeypatch.setattr(VideoHTTPAdapter, "submit", submit)
    job = await service.create("owner@test", create_input())
    row = await step(service, job["job_id"])
    assert await service.store.dispatch(row)
    row = await step(service, job["job_id"])
    assert row.status == "needs_reconciliation"
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_queued_releases_exposure(service):
    job = await service.create("owner@test", create_input())
    await service.cancel(
        "owner@test",
        job["job_id"],
        VideoMutation(
            expected_version=job["version"],
            idempotency_key=uuid.uuid4().hex,
        ),
    )
    row = await step(service, job["job_id"])
    assert row.status == "cancelled"
    assert row.cost_status == "not_submitted"
    assert row.actual_microusd == 0


@pytest.mark.asyncio
async def test_cancel_commit_failure_rolls_back_state_receipt_and_budget(service, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    job = await service.create("owner@test", create_input())
    mutation = VideoMutation(expected_version=job["version"], idempotency_key=uuid.uuid4().hex)
    with monkeypatch.context() as patch:
        patch.setattr(
            AsyncSession, "commit", AsyncMock(side_effect=RuntimeError("commit interrupted"))
        )
        with pytest.raises(RuntimeError, match="commit interrupted"):
            await service.cancel("owner@test", job["job_id"], mutation)
    row = await service.store.get(job["job_id"])
    assert row.status == "queued" and row.actual_microusd is None
    result = await service.cancel("owner@test", row.job_id, mutation)
    assert result["status"] == "cancelled" and result["cost_status"] == "not_submitted"
    assert await service.cancel("owner@test", row.job_id, mutation) == result
    async with service.sessions() as session:
        assert sum(b.exposure_microusd for b in await session.scalars(select(VideoBudgetRow))) == 0


@pytest.mark.asyncio
async def test_foreign_owner_or_conversation_cannot_read(service):
    job = await service.create("owner@test", create_input())
    with pytest.raises(PermissionError):
        await service.get("other@test", job["job_id"])
    with pytest.raises(PermissionError):
        await service.get("owner@test", job["job_id"], conversation_id="other-conversation")


@pytest.mark.asyncio
async def test_admission_budget_and_dry_run(service):
    request = create_input()
    result = await service.create("owner@test", request.model_copy(update={"dry_run": True}))
    assert result["dry_run"]
    assert (
        await service.store.existing("owner@test", request.conversation_id, request.idempotency_key)
        is None
    )
    await service.create("owner@test", request)
    await service.create("owner@test", create_input())
    with pytest.raises(ValueError, match="concurrency"):
        await service.create("owner@test", create_input())


@pytest.mark.asyncio
async def test_stale_cancel_cannot_overwrite_state(service):
    job = await service.create("owner@test", create_input())
    await step(service, job["job_id"])
    with pytest.raises(ValueError, match="version changed"):
        await service.cancel(
            "owner@test",
            job["job_id"],
            VideoMutation(
                expected_version=job["version"],
                idempotency_key=uuid.uuid4().hex,
            ),
        )


@pytest.mark.asyncio
async def test_changed_price_blocks_before_paid_call(service, monkeypatch):
    submit = AsyncMock()
    monkeypatch.setattr(VideoHTTPAdapter, "submit", submit)
    job = await service.create("owner@test", create_input())
    await step(service, job["job_id"])
    service.policy.return_value.model_max_cost_usd["google/veo-3.1-generate-preview"] = Decimal("4")
    row = await step(service, job["job_id"])
    assert row.status == "blocked"
    submit.assert_not_called()
    cancelled = await service.cancel(
        "owner@test",
        row.job_id,
        VideoMutation(
            expected_version=row.version,
            idempotency_key=uuid.uuid4().hex,
        ),
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled["cost_status"] == "not_submitted"


@pytest.mark.asyncio
async def test_cancel_blocked_after_dispatch_preserves_exposure(service):
    job = await service.create("owner@test", create_input())
    row = await step(service, job["job_id"])
    assert await service.store.dispatch(row)
    await service.store.transition(await service.store.get(row.job_id), "blocked")
    row = await service.store.get(row.job_id)
    cancelled = await service.cancel(
        "owner@test",
        row.job_id,
        VideoMutation(
            expected_version=row.version,
            idempotency_key=uuid.uuid4().hex,
        ),
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled["actual_cost_usd"] is None
    async with service.sessions() as session:
        assert (
            sum(b.exposure_microusd for b in await session.scalars(select(VideoBudgetRow)))
            == 2_000_000
        )


@pytest.mark.asyncio
async def test_staging_retry_reuses_object_and_terminal_cleanup(service):
    from cognis.core.video_transfer import VideoTransfers
    from cognis.store.models import VideoTransferRow

    transfers = VideoTransfers(service)
    job = await service.create("owner@test", create_input())
    row = await service.store.get(job["job_id"])

    async def content():
        yield b"\x00\x00\x00\x18ftypmp42media-content"

    artifacts = set()
    for _ in range(4):
        ticket = await transfers.issue(row)
        result = await transfers.receive(ticket["token"], content())
        artifacts.add(result["artifact_id"])
    assert len(artifacts) == 1
    await service.cancel(
        "owner@test",
        row.job_id,
        VideoMutation(
            expected_version=row.version,
            idempotency_key=uuid.uuid4().hex,
        ),
    )
    await transfers.cleanup()
    async with service.sessions() as session:
        assert list(await session.scalars(select(VideoTransferRow))) == []
    for artifact_id in artifacts:
        assert (
            await service.artifacts.async_load_metadata("video_staging", artifact_id, "video-1.mp4")
            is None
        )


@pytest.mark.asyncio
async def test_known_charge_settles_even_without_delivery(service):
    job = await service.create("owner@test", create_input())
    row = await service.store.get(job["job_id"])
    await service.store.transition(row, "failed")
    await service.store.settle(row.job_id, 1_500_000)
    await service.store.settle(row.job_id, 1_500_000)
    async with service.sessions() as db:
        budgets = list(await db.scalars(select(VideoBudgetRow)))
    assert sum(b.exposure_microusd for b in budgets) == 1_500_000
    view = job_view(await service.store.get(row.job_id))
    assert view.actual_cost_usd == "1.5"


@pytest.mark.asyncio
async def test_success_streams_and_publishes_once(service, monkeypatch):
    result = VideoRemoteResult(
        handle="operations/completed-render",
        state="completed",
        outputs=[VideoOutput(locator="https://generativelanguage.googleapis.com/video")],
        cost_usd=Decimal("1.5"),
    )
    monkeypatch.setattr(VideoHTTPAdapter, "submit", AsyncMock(return_value=result))

    async def stream(self, output, max_bytes):
        yield b"\x00\x00\x00\x18ftypmp42"
        yield b"video-content"

    monkeypatch.setattr(VideoHTTPAdapter, "output_stream", stream)
    job = await service.create("owner@test", create_input())
    await step(service, job["job_id"])
    row = await step(service, job["job_id"])
    assert row.status == "ingesting"
    row = await step(service, job["job_id"])
    assert row.status == "succeeded" and len(row.outputs) == 1
    assert row.actual_microusd == 1_500_000
    data = b"".join(
        [
            chunk
            async for chunk in service.artifacts.async_read_range(
                "videos", row.outputs[0]["artifact_id"], "video-1.mp4", 4, 7
            )
        ]
    )
    assert data == b"ftyp"


@pytest.mark.asyncio
async def test_terminal_evidence_cannot_regress(service):
    job = await service.create("owner@test", create_input())
    row = await service.store.get(job["job_id"])
    completed = VideoRemoteResult(handle="operations/completed-render", state="completed")
    await service.store.record_result(row.attempt_id, completed)
    await service.store.record_result(
        row.attempt_id, completed.model_copy(update={"state": "running"})
    )
    assert (await service.store.result(row.attempt_id)).state == "completed"


@pytest.mark.asyncio
async def test_transfer_is_scoped_expiring_and_cancellation_aware(service):
    import hashlib
    from datetime import UTC, datetime, timedelta

    from cognis.core.video_transfer import VideoTransfers
    from cognis.store.models import VideoTransferRow

    job = await service.create("owner@test", create_input())
    row = await service.store.get(job["job_id"])
    transfers = VideoTransfers(service)
    ticket = await transfers.issue(row)

    async def content():
        yield b"\x00\x00\x00\x18ftypmp42"
        yield b"video-content"

    received = await transfers.receive(ticket["token"], content())
    assert await transfers.receive(ticket["token"], content()) == received
    metadata = await transfers.staged(row, received["artifact_id"])
    assert metadata.content_type == "video/mp4"
    other = await service.create("owner@test", create_input())
    with pytest.raises(PermissionError):
        await transfers.staged(await service.store.get(other["job_id"]), received["artifact_id"])
    with pytest.raises(PermissionError):
        await transfers.authorize("not-a-valid-ticket", "output")
    async with service.sessions() as session:
        token = await session.get(
            VideoTransferRow, hashlib.sha256(ticket["token"].encode()).hexdigest()
        )
        token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    with pytest.raises(PermissionError):
        await transfers.authorize(ticket["token"], "output")
    ticket = await transfers.issue(row)
    await service.cancel(
        "owner@test",
        row.job_id,
        VideoMutation(
            expected_version=row.version,
            idempotency_key=uuid.uuid4().hex,
        ),
    )
    with pytest.raises(PermissionError):
        await transfers.receive(ticket["token"], content())


@pytest.mark.asyncio
async def test_mutation_replay_is_idempotent(service):
    from cognis.models.video import VideoRecovery

    job = await service.create("owner@test", create_input())
    await service.store.transition(await service.store.get(job["job_id"]), "blocked")
    job = await service.get("owner@test", job["job_id"])
    mutation = VideoRecovery(
        expected_version=job["version"],
        idempotency_key=uuid.uuid4().hex,
        action="abandon",
    )
    first = await service.recover("owner@test", job["job_id"], mutation)
    second = await service.recover("owner@test", job["job_id"], mutation)
    assert first == second
    assert first["status"] == "abandoned"


@pytest.mark.asyncio
async def test_executor_adapter_sends_metadata_and_collects_via_ticket(service):
    from cognis.core.video_transfer import VideoTransfers

    policy = service.policy.return_value
    service.connection.return_value[1]["runtime"] = "executor"
    result = VideoRemoteResult(
        handle="operations/remote-render",
        state="completed",
        outputs=[VideoOutput(locator="https://generativelanguage.googleapis.com/video")],
    )
    from cognis.providers.video import native_video_capabilities

    async def rpc(binding, params):
        assert "api_key" in params["connection"]  # transient dispatch only
        if params["operation"] == "capabilities":
            return native_video_capabilities("veo").model_dump()
        if params["operation"] == "submit":
            assert params["inputs"] == []
            return result.model_dump()
        assert params["operation"] == "collect"
        assert params["output_ticket"]["max_bytes"] == policy.max_output_bytes

        async def content():
            yield b"\x00\x00\x00\x18ftypmp42video-content"

        return await VideoTransfers(service).receive(params["output_ticket"]["token"], content())

    service.llm = SimpleNamespace(video_rpc=AsyncMock(side_effect=rpc))
    job = await service.create("owner@test", create_input())
    await step(service, job["job_id"])
    await step(service, job["job_id"])
    row = await step(service, job["job_id"])
    assert row.status == "succeeded"
    assert len(row.outputs) == 1
    assert "api_key" not in row.binding
