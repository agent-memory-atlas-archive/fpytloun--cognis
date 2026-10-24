from __future__ import annotations

import importlib
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, schema, select
from sqlalchemy.ext.asyncio import create_async_engine

from cognis.bootstrap import run_schema_bootstrap
from cognis.core.executor_pin_notice_dispatch import ExecutorPinNoticeDispatcher
from cognis.core.executor_recovery import begin_executor_recovery, clear_executor_recovery
from cognis.store.coordination import DatabaseLeaseStore
from cognis.store.database import create_engine, create_session_factory
from cognis.store.direct_turns import DirectTurnStore, conversation_lease_key
from cognis.store.models import Conversation, ExecutorRecoveryNoticeRow
from cognis.store.queries import create_agent, create_conversation, create_session, create_user


@pytest.mark.asyncio
@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
async def test_recovery_schema_and_fenced_claim(tmp_path, dialect):
    url = os.environ.get("COGNIS_TEST_POSTGRES_URL")
    if dialect == "postgres" and not url:
        pytest.skip("COGNIS_TEST_POSTGRES_URL is not configured")
    if dialect == "sqlite":
        url = f"sqlite+aiosqlite:///{tmp_path}/recovery.db"
    else:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    admin = create_engine(url)
    schema_name = f"executor_recovery_{uuid.uuid4().hex}"
    if dialect == "postgres":
        async with admin.begin() as conn:
            await conn.execute(schema.CreateSchema(schema_name))
        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": f'"{schema_name}"'}}
        )
    else:
        engine = admin
    migration = importlib.import_module(
        "cognis.store.migrations.versions.165_executor_recovery_notices"
    )

    def migrate(conn, action):
        with Operations.context(MigrationContext.configure(conn)):
            getattr(migration, action)()

    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: migrate(sync, "upgrade"))
            assert await conn.run_sync(
                lambda sync: inspect(sync).has_table("executor_recovery_notices")
            )
            await conn.run_sync(lambda sync: migrate(sync, "downgrade"))
            assert not await conn.run_sync(
                lambda sync: inspect(sync).has_table("executor_recovery_notices")
            )
        # Old-schema startup must create the new table, idempotently.
        await run_schema_bootstrap(engine)
        await run_schema_bootstrap(engine)
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: migrate(sync, "upgrade"))
            assert "ix_executor_recovery_notices_pending" in await conn.run_sync(
                lambda sync: {
                    index["name"]
                    for index in inspect(sync).get_indexes("executor_recovery_notices")
                }
            )
        factory = create_session_factory(engine)
        async with factory() as session:
            await create_user(session, email="u@example.com", name="U", password_hash="hash")
            await create_agent(
                session, agent_id="a", owner_email="u@example.com", name="A", status="active"
            )
            conversation = await create_conversation(
                session,
                conversation_id="c",
                user_email="u@example.com",
                agent_id="a",
                context_type="web",
            )
            conversation.active_executor_id = "maitrea_riker"
            conversation.active_executor_unavailable_since = datetime.now(UTC) - timedelta(hours=1)
            active = await create_session(session, "c", "u@example.com", "a")
            conversation.active_session_id = active.session_id
            await session.commit()
            assert list((await session.scalars(select(ExecutorRecoveryNoticeRow))).all()) == []
        store = DirectTurnStore(factory)
        admitted = await store.admit(
            conversation_id="c",
            session_id=None,
            agent_id="a",
            user_id="u@example.com",
            idempotency_scope="recovery-test",
            idempotency_key="first",
            payload={"schema_version": 1, "content": "Retry", "attachments": []},
        )
        lease = await DatabaseLeaseStore(factory).acquire(
            conversation_lease_key("c"), "controller:boot", ttl_seconds=60
        )
        assert lease is not None
        assert await store.claim(
            admitted.request.request_id,
            lease=lease,
            controller_id="controller",
            incarnation_id="boot",
        )
        async with factory() as session:
            conversation = await session.get(Conversation, "c")
            assert conversation.active_executor_unavailable_since is None
        dispatcher = ExecutorPinNoticeDispatcher(
            session_factory=factory,
            guardrails=SimpleNamespace(
                record_events=AsyncMock(return_value=SimpleNamespace(ok=False))
            ),
        )
        recovery_args = {
            "conversation_id": "c",
            "task_id": None,
            "executor_id": "maitrea_riker",
            "notice_dispatcher": dispatcher,
        }
        await begin_executor_recovery(factory, **recovery_args)
        await begin_executor_recovery(factory, **recovery_args)
        await clear_executor_recovery(factory, **recovery_args)
        async with factory() as session:
            notices = list((await session.scalars(select(ExecutorRecoveryNoticeRow))).all())
            assert len(notices) == 2
            assert all(row.delivered_at is None for row in notices)
        dispatcher.guardrails.record_events.return_value = SimpleNamespace(ok=True, count=0)
        assert await dispatcher.dispatch_recovery_pending() == 2
        assert await dispatcher.dispatch_recovery_pending() == 0
    finally:
        await engine.dispose()
        if dialect == "postgres":
            async with admin.begin() as conn:
                await conn.execute(schema.DropSchema(schema_name, cascade=True))
            await admin.dispose()
