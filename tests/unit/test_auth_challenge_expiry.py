from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import schema as sa_schema
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cognis.api.app import create_app
from cognis.core.agent_loop import PauseWaiter
from cognis.core.notifications import (
    NotificationService,
    _notification_expiry,
    _notification_payload_expires_at,
)
from cognis.core.tool_router import ToolRouter
from cognis.models.tool import ToolCall
from cognis.store.models import Base, Conversation, NotificationRow
from cognis.store.notification_expiry import notification_is_expired
from cognis.store.queries import create_agent, create_user


@pytest.mark.parametrize(
    ("payload", "seconds"),
    [
        ({}, 180),
        ({"timeout_seconds": 30}, 30),
        ({"timeout_seconds": 10000}, 600),
        ({"timeout_seconds": 0}, 1),
        ({"timeout_seconds": "bad"}, 180),
        ({"timeout_seconds": float("nan")}, 180),
        ({"timeout_seconds": float("inf")}, 180),
        ({"expires_at": "bad", "timeout_seconds": 45}, 45),
    ],
)
def test_auth_expiry_matches_bounded_wait_for_new_and_legacy_rows(
    payload: dict, seconds: int
) -> None:
    created = datetime(2026, 6, 8, tzinfo=UTC)
    expected = created + timedelta(seconds=seconds)
    assert (
        _notification_payload_expires_at("auth_challenge", payload, created_at=created) == expected
    )
    row = SimpleNamespace(
        notification_type="auth_challenge",
        payload=payload,
        expires_at=None,
        created_at=created.replace(tzinfo=None),
        status="pending",
    )
    assert _notification_expiry(row) == expected
    assert not notification_is_expired(row, now=expected - timedelta(microseconds=1))
    assert notification_is_expired(row, now=expected)


def test_auth_explicit_deadline_and_other_long_lived_requests_are_preserved() -> None:
    created = datetime(2026, 6, 8, tzinfo=UTC)
    deadline = created + timedelta(minutes=5)
    for payload in (
        {"expires_at": deadline.isoformat()},
        {"metadata": {"expires_at": deadline.isoformat()}},
    ):
        assert (
            _notification_payload_expires_at("auth_challenge", payload, created_at=created)
            == deadline
        )
    assert _notification_payload_expires_at("step_question", {}, created_at=created) is None
    assert _notification_payload_expires_at("credential_request", {}, created_at=created) is None


def test_legacy_auth_challenges_disappear_from_all_projections_and_reconcile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COGNIS_HOST", "127.0.0.1")
    now = datetime.now(UTC)
    with TestClient(create_app()) as client:

        async def seed() -> None:
            async with client.app.state.session_factory() as db:
                await create_user(
                    db, email="owner@example.com", name="Owner", password_hash="unused"
                )
                await create_agent(
                    db, agent_id="owner", owner_email="owner@example.com", name="Owner"
                )
                for cid in ("stale", "live", "unread"):
                    db.add(
                        Conversation(
                            conversation_id=cid,
                            user_email="owner@example.com",
                            agent_id="owner",
                            context_type="web",
                            last_message_at=now - timedelta(days=1),
                            last_read_at=None if cid == "unread" else now,
                        )
                    )
                await db.flush()
                for index in range(3):
                    db.add(
                        NotificationRow(
                            notification_id=f"legacy-auth-{index}",
                            conversation_id="stale",
                            user_email="owner@example.com",
                            notification_type="auth_challenge",
                            status="pending",
                            created_at=now - timedelta(days=120),
                            expires_at=None,
                            payload={},
                        )
                    )
                db.add(
                    NotificationRow(
                        notification_id="live-auth",
                        conversation_id="live",
                        user_email="owner@example.com",
                        notification_type="auth_challenge",
                        status="pending",
                        created_at=now,
                        expires_at=now + timedelta(minutes=5),
                        payload={"required_fields": ["code"]},
                    )
                )
                await db.commit()

        client.portal.call(seed)
        token = client.app.state.auth_provider.sign_access_token(
            "owner@example.com", "Owner", "admin"
        )
        headers = {"Authorization": f"Bearer {token}"}
        # Raw pending rows have not been cleaned; read projections must already agree.
        summary = client.get("/api/v1/dashboard/navigation-summary", headers=headers).json()
        assert (
            sum(
                group["count"]
                for group in summary["chat_groups"]
                if "auth_challenge" in group["pending_notification_types"]
            )
            == 1
        )
        sidebar = client.get("/api/v1/conversations/sidebar", headers=headers).json()
        items = {item["conversation_id"]: item for item in sidebar["conversations"]["items"]}
        assert items["stale"]["pending_notification_types"] == []
        assert items["live"]["pending_notification_types"] == ["auth_challenge"]
        waiting = client.get("/api/v1/conversations/waiting", headers=headers).json()
        candidates = {item["conversation_id"]: item for item in waiting["conversations"]["items"]}
        assert candidates["stale"]["pending_notification_types"] == []
        assert candidates["unread"]["has_unread"]
        assert candidates["live"]["pending_notification_types"] == ["auth_challenge"]
        rejected = client.post(
            "/api/v1/notifications/legacy-auth-0/resolve",
            headers=headers,
            json={"decision": "approve", "code": "123456"},
        )
        assert rejected.status_code != 200

        async def reconcile() -> None:
            service = client.app.state.notification_service
            # Assert lifecycle rejection directly, not merely HTTP body validation.
            assert not await service.resolve(
                "legacy-auth-0",
                "approve",
                {"code": "123456"},
                user_email="owner@example.com",
            )
            await service.reconcile_pending()
            await service.reconcile_pending()
            async with client.app.state.session_factory() as db:
                for index in range(3):
                    row = await db.get(NotificationRow, f"legacy-auth-{index}")
                    assert row.status == "resolved"
                    assert row.resolution == {"decision": "cancel", "reason": "expired"}
                    assert row.revision == 2
                assert (await db.get(NotificationRow, "live-auth")).status == "pending"
            created = await service.create(
                notification_type="auth_challenge",
                user_email="owner@example.com",
                conversation_id="live",
                payload={"timeout_seconds": 45},
            )
            assert created.expires_at is not None
            assert (created.expires_at - created.created_at).total_seconds() == 45

        client.portal.call(reconcile)


@pytest.mark.asyncio
async def test_cancelling_auth_value_wait_retires_notification_without_delivery() -> None:
    notifications = SimpleNamespace(
        create=AsyncMock(),
        wait_for_resolution=AsyncMock(side_effect=asyncio.CancelledError()),
        mark_orphaned=AsyncMock(return_value=True),
    )
    router = ToolRouter(guardrails=SimpleNamespace(), non_bypassable_patterns=[])
    router.notification_service = notifications
    router.pause_waiter = SimpleNamespace()
    with pytest.raises(asyncio.CancelledError):
        await router._resolve_auth_challenge_value_ref(
            "$auth_challenge:sign-in.code",
            session=SimpleNamespace(
                user_email="owner@example.com", conversation_id="live", session_id="session-live"
            ),
            agent=SimpleNamespace(),
            tool_call=ToolCall(call_id="request-code", name="browser_fill", arguments={}),
            challenge_payload={"kind": "otp_code"},
        )
    created_id = notifications.create.call_args.kwargs["notification_id"]
    notifications.mark_orphaned.assert_awaited_once_with(
        created_id, reason="cancelled", include_resolving=True
    )


@asynccontextmanager
async def _auth_test_service(tmp_path: Path, *, postgres: bool = False):
    admin = None
    schema = None
    app_name = f"auth-expiry-{uuid4().hex}"
    if postgres:
        url = os.getenv("COGNIS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("COGNIS_TEST_POSTGRES_URL is not configured")
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        schema = f"auth_expiry_{uuid4().hex}"
        admin = create_async_engine(url)
        async with admin.begin() as connection:
            await connection.execute(sa_schema.CreateSchema(schema))
        engine = create_async_engine(
            url,
            connect_args={
                "server_settings": {"search_path": schema, "application_name": app_name},
            },
        )
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    waiter = PauseWaiter()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            await create_user(db, email="owner@example.com", name="Owner", password_hash="unused")
            await create_agent(db, agent_id="owner", owner_email="owner@example.com", name="Owner")
            db.add(
                Conversation(
                    conversation_id="live",
                    user_email="owner@example.com",
                    agent_id="owner",
                    context_type="web",
                )
            )
            await db.commit()
        service = NotificationService(
            sessions, waiter, SimpleNamespace(publish=AsyncMock()), SimpleNamespace()
        )
        row = await service.create(
            notification_id="challenge-live",
            notification_type="auth_challenge",
            user_email="owner@example.com",
            conversation_id="live",
            payload={"timeout_seconds": 600},
        )
        yield service, sessions, engine, app_name, row
    finally:
        await engine.dispose()
        if admin is not None:
            async with admin.begin() as connection:
                await connection.execute(sa_schema.DropSchema(schema, cascade=True))
            await admin.dispose()


@pytest.mark.asyncio
async def test_cancelled_auth_wait_fences_a_real_inflight_resolution_factory(
    tmp_path: Path,
) -> None:
    async with _auth_test_service(tmp_path) as (service, sessions, _, _, _row):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def factory():
            entered.set()
            await release.wait()
            return {"fields": {"code": "123456"}}

        adapter = SimpleNamespace(
            create=AsyncMock(),
            mark_orphaned=service.mark_orphaned,
            wait_for_resolution=AsyncMock(),
        )
        created_id = None

        async def capture_wait(notification_id, *, timeout):
            nonlocal created_id
            created_id = notification_id
            await asyncio.Event().wait()

        adapter.wait_for_resolution.side_effect = capture_wait
        router = ToolRouter(guardrails=SimpleNamespace(), non_bypassable_patterns=[])
        router.notification_service = adapter
        router.pause_waiter = SimpleNamespace()
        waiting = asyncio.create_task(
            router._resolve_auth_challenge_value_ref(
                "$auth_challenge:live.code",
                session=SimpleNamespace(
                    user_email="owner@example.com",
                    conversation_id="live",
                    session_id="session-live",
                ),
                agent=SimpleNamespace(),
                tool_call=ToolCall(call_id="waiting", name="browser_fill", arguments={}),
                challenge_payload={"kind": "otp_code"},
            )
        )
        while created_id is None:
            await asyncio.sleep(0)
        # The router owns this notification; rename the seeded row to its real ID.
        async with sessions() as db:
            await db.execute(
                update(NotificationRow)
                .where(NotificationRow.notification_id == "challenge-live")
                .values(notification_id=created_id)
            )
            await db.commit()
        resolution = asyncio.create_task(
            service.resolve(
                created_id, "approve", {}, user_email="owner@example.com", data_factory=factory
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        release.set()
        assert not await asyncio.wait_for(resolution, timeout=5)
        async with sessions() as db:
            row = await db.get(NotificationRow, created_id)
            assert row.status == "resolved"
            assert row.resolution == {"decision": "cancel", "reason": "cancelled"}
            assert row.revision == 3


@pytest.mark.asyncio
async def test_auth_claim_waiting_on_postgres_lock_cannot_outlive_deadline(tmp_path: Path) -> None:
    async with _auth_test_service(tmp_path, postgres=True) as (
        service,
        sessions,
        engine,
        app_name,
        _row,
    ):
        deadline = datetime.now(UTC) + timedelta(seconds=2)
        async with sessions() as db:
            await db.execute(
                update(NotificationRow)
                .where(NotificationRow.notification_id == "challenge-live")
                .values(expires_at=deadline)
            )
            await db.commit()
        factory = AsyncMock(return_value={"fields": {"code": "123456"}})
        async with sessions() as locker:
            await locker.execute(
                select(NotificationRow)
                .where(NotificationRow.notification_id == "challenge-live")
                .with_for_update()
            )
            task = asyncio.create_task(
                service.resolve(
                    "challenge-live",
                    "approve",
                    {},
                    user_email="owner@example.com",
                    data_factory=factory,
                )
            )
            try:
                async with asyncio.timeout(5):
                    while True:
                        async with engine.connect() as observer:
                            blocked = await observer.scalar(
                                text(
                                    "SELECT count(*) FROM pg_stat_activity "
                                    "WHERE application_name=:name AND wait_event_type='Lock'"
                                ),
                                {"name": app_name},
                            )
                        if blocked:
                            break
                        await asyncio.sleep(0.02)
                await asyncio.sleep(max(0, (deadline - datetime.now(UTC)).total_seconds()) + 0.1)
                await locker.commit()
                assert not await asyncio.wait_for(task, timeout=5)
                factory.assert_not_awaited()
            finally:
                if not task.done():
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
