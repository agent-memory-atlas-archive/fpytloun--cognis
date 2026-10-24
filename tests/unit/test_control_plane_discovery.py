"""Discovery must remain commit-aware without reading durable payloads."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, inspect, literal, update
from sqlalchemy import schema as sa_schema
from sqlalchemy.ext.asyncio import create_async_engine

from cognis.core.direct_turn_runtime import DurableDirectTurnRuntime
from cognis.store import direct_turns
from cognis.store.database import create_session_factory
from cognis.store.direct_turns import DirectTurnStore
from cognis.store.models import Base, DirectTurnRequestRow
from cognis.store.queries import create_agent, create_conversation, create_user
from tests.unit.test_direct_turn_store import _admit, _harness


@pytest.fixture(params=["sqlite", "postgres"])
async def discovery_harness(request, tmp_path):
    if request.param == "sqlite":
        harness = await _harness(tmp_path)
        try:
            yield harness
        finally:
            await harness.engine.dispose()
        return
    url = os.environ.get("COGNIS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL URL not configured")
    schema = f"control_plane_{uuid.uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(sa_schema.CreateSchema(schema))
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": f'"{schema}"'}}
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            await create_user(session, email="user@example.com", name="User", password_hash="")
            await create_agent(
                session, agent_id="agent-1", owner_email="user@example.com", name="Agent"
            )
            await create_conversation(
                session,
                user_email="user@example.com",
                agent_id="agent-1",
                context_type="web",
                conversation_id="conv-a",
            )
            await session.commit()
        yield SimpleNamespace(
            engine=engine, session_factory=factory, store=DirectTurnStore(factory)
        )
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(sa_schema.DropSchema(schema, cascade=True))
        await admin.dispose()


@pytest.mark.asyncio
async def test_failure_visibility_filters_before_limit_without_loading_payload(discovery_harness):
    harness = discovery_harness
    try:
        outcomes = [
            None,
            {},
            [],
            "permanent_payload_visibility_pending",
            {"phase": None},
            {"phase": "permanent_payload_visibility_complete"},
            {"phase": "permanent_payload_visibility_pending"},
        ]
        rows = [
            (await _admit(harness, key=f"failure-{index}", content="history")).request
            for index in range(len(outcomes))
        ]
        async with harness.session_factory() as session:
            for index, row in enumerate(rows):
                await session.execute(
                    update(DirectTurnRequestRow)
                    .where(DirectTurnRequestRow.request_id == row.request_id)
                    .values(
                        status="failed",
                        outcome=outcomes[index],
                    )
                )
            await session.commit()
        pending = await harness.store.list_pending_failure_visibility(limit=1)
        assert [row.request_id for row in pending] == [rows[-1].request_id]
        assert "payload" in inspect(pending[0]).unloaded
        hydrated = await harness.store.get(pending[0].request_id)
        assert hydrated.payload["content"] == "history"
    finally:
        await harness.engine.dispose()


@pytest.mark.asyncio
async def test_candidate_discovery_one_statement_preserves_fifo_and_retry_deadline(
    discovery_harness,
):
    harness = discovery_harness
    try:
        first = (await _admit(harness, key="head", content="head")).request
        await _admit(harness, key="tail", content="tail")
        async with harness.session_factory() as session:
            await session.execute(
                update(DirectTurnRequestRow)
                .where(DirectTurnRequestRow.request_id == first.request_id)
                .values(next_attempt_at=datetime.now(UTC) + timedelta(days=1))
            )
            await session.commit()
        statements = []

        def record(_connection, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(harness.engine.sync_engine, "before_cursor_execute", record)
        assert await harness.store.list_claimable_heads() == []
        assert len(statements) == 1
        event.remove(harness.engine.sync_engine, "before_cursor_execute", record)
        async with harness.session_factory() as session:
            await session.execute(
                update(DirectTurnRequestRow)
                .where(DirectTurnRequestRow.request_id == first.request_id)
                .values(next_attempt_at=datetime.now(UTC) - timedelta(days=1))
            )
            await session.commit()
        assert [row.request_id for row in await harness.store.list_claimable_heads()] == [
            first.request_id
        ]
    finally:
        await harness.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [False, True])
async def test_second_controller_discovers_only_committed_admission(discovery_harness, commit):
    harness = discovery_harness
    entered, release = asyncio.Event(), asyncio.Event()
    other = DirectTurnStore(harness.session_factory)

    async def participant(_session, _row, _created):
        entered.set()
        await release.wait()
        if not commit:
            raise RuntimeError("rollback admission")

    admission = asyncio.create_task(
        harness.store.admit(
            conversation_id="conv-a",
            session_id=None,
            agent_id="agent-1",
            user_id="user@example.com",
            idempotency_scope="commit-test",
            idempotency_key="head",
            payload={"schema_version": 1, "content": "committed", "attachments": []},
            transaction_participant=participant,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert await other.list_claimable_heads() == []
        release.set()
        if commit:
            admitted = await admission
            # No wake is delivered: a fresh controller's recovery sweep sees durable work.
            restarted = DirectTurnStore(harness.session_factory)
            assert [row.request_id for row in await restarted.list_claimable_heads()] == [
                admitted.request.request_id
            ]
        else:
            with pytest.raises(RuntimeError, match="rollback admission"):
                await admission
            assert await other.list_claimable_heads() == []
    finally:
        release.set()
        await asyncio.gather(admission, return_exceptions=True)


@pytest.mark.asyncio
async def test_failure_visibility_hydrates_payload_before_callback(discovery_harness):
    harness = discovery_harness
    row = (await _admit(harness, key="failed", content="needed history")).request
    async with harness.session_factory() as session:
        await session.execute(
            update(DirectTurnRequestRow)
            .where(DirectTurnRequestRow.request_id == row.request_id)
            .values(status="failed", outcome={"phase": "permanent_payload_visibility_pending"})
        )
        await session.commit()
    callback = AsyncMock()
    runtime = DurableDirectTurnRuntime(
        store=harness.store,
        lease_store=None,
        controller_id="controller-a",
        incarnation_id="boot-a",
        artifact_store=None,
        execute_claimed_turn=AsyncMock(),
        on_permanent_failure=callback,
        simple_mode=True,
    )
    await runtime._recover_failure_visibility()
    callback.assert_awaited_once()
    assert callback.call_args.args[0].payload["content"] == "needed history"
    assert await harness.store.list_pending_failure_visibility() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deleted", "settled", "cancelled"])
async def test_failure_visibility_skips_candidate_changed_before_hydration(change):
    candidate = SimpleNamespace(request_id="pending-failure")
    current = {
        "deleted": None,
        "settled": SimpleNamespace(status="failed", outcome={"phase": "completed"}),
        "cancelled": SimpleNamespace(
            status="cancelled", outcome={"phase": "permanent_payload_visibility_pending"}
        ),
    }[change]
    store = SimpleNamespace(
        list_pending_failure_visibility=AsyncMock(return_value=[candidate]),
        get=AsyncMock(return_value=current),
        complete_failure_visibility=AsyncMock(),
    )
    callback = AsyncMock()
    runtime = DurableDirectTurnRuntime(
        store=store,
        lease_store=None,
        controller_id="controller-a",
        incarnation_id="boot-a",
        artifact_store=None,
        execute_claimed_turn=AsyncMock(),
        on_permanent_failure=callback,
        simple_mode=True,
    )
    await runtime._recover_failure_visibility()
    store.get.assert_awaited_once_with(candidate.request_id)
    callback.assert_not_awaited()
    store.complete_failure_visibility.assert_not_awaited()


@pytest.mark.asyncio
async def test_sqlite_exact_second_retry_deadline_is_inclusive(tmp_path, monkeypatch):
    harness = await _harness(tmp_path)
    try:
        row = (await _admit(harness, key="deadline", content="ready")).request
        deadline = datetime(2026, 1, 1, tzinfo=UTC)
        async with harness.session_factory() as session:
            await session.execute(
                update(DirectTurnRequestRow)
                .where(DirectTurnRequestRow.request_id == row.request_id)
                .values(next_attempt_at=deadline)
            )
            await session.commit()
        monkeypatch.setattr(
            direct_turns,
            "database_now_expression",
            lambda _session: literal("2026-01-01 00:00:00"),
        )
        assert [
            candidate.request_id for candidate in await harness.store.list_claimable_heads()
        ] == [row.request_id]
    finally:
        await harness.engine.dispose()
