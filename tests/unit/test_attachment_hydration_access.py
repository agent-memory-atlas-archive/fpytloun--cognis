"""Real SQL coverage for batched attachment ACLs and transaction-local JIT control."""

from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, text, update
from sqlalchemy.ext.asyncio import create_async_engine

from cognis.core.attachment_utils import hydrate_attachment_ref_groups
from cognis.store.database import create_session_factory
from cognis.store.models import Agent, ArtifactGrantRow, ArtifactRecordRow, Base, User
from cognis.store.queries import create_artifact_record, create_conversation, create_session


@pytest_asyncio.fixture(params=["sqlite", "postgresql"])
async def hydration_db(tmp_path, request):
    admin = None
    schema = "attachment_hydration_" + uuid.uuid4().hex
    if request.param == "postgresql":
        url = os.getenv("COGNIS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("COGNIS_TEST_POSTGRES_URL is not configured")
        admin = create_async_engine(url)
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            url,
            connect_args={"server_settings": {"search_path": schema, "jit": "on"}},
            pool_size=1,
            max_overflow=0,
        )
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hydration.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        owner = f"owner-{uuid.uuid4().hex}@test.local"
        agent_id = f"agent_{uuid.uuid4().hex}"
        async with factory() as session:
            session.add(User(email=owner, name="Owner"))
            await session.flush()
            session.add(Agent(agent_id=agent_id, owner_email=owner, name="Agent"))
            await session.flush()
            conversation = await create_conversation(session, owner, agent_id, "web")
            source = await create_session(session, conversation.conversation_id, owner, agent_id)
            ref = f"att_{uuid.uuid4().hex}"
            await create_artifact_record(
                session,
                artifact_id=ref,
                namespace="attachments",
                object_id=ref,
                filename="report.txt",
                owner_email=owner,
                conversation_id=conversation.conversation_id,
                session_id=source.session_id,
                purpose="chat_input",
                kind="file",
                mime_type="text/plain",
                size_bytes=10,
                status="attached",
            )
            await session.commit()
        yield SimpleNamespace(
            factory=factory,
            engine=engine,
            owner=owner,
            conversation_id=conversation.conversation_id,
            session_id=source.session_id,
            ref=ref,
        )
    finally:
        await engine.dispose()
        if admin is not None:
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()


async def _hydrate(db, store, count=40):
    return await hydrate_attachment_ref_groups(
        db.factory,
        store,
        [[{"artifact_id": db.ref}] for _ in range(count)],
        owner_email=db.owner,
        conversation_id=db.conversation_id,
        session_id=db.session_id,
    )


@pytest.mark.parametrize("legacy", [False, True])
async def test_batch_authorizes_once_and_rechecks_revocation(hydration_db, legacy):
    db = hydration_db
    if legacy:
        async with db.factory() as session:
            # Legacy records predate both ownership and entitlement registration.
            await session.execute(
                update(ArtifactRecordRow)
                .where(ArtifactRecordRow.artifact_id == db.ref)
                .values(owner_agent_id=None)
            )
            await session.execute(
                delete(ArtifactGrantRow).where(ArtifactGrantRow.content_ref == db.ref)
            )
            await session.commit()
            assert (await session.get(ArtifactRecordRow, db.ref)).owner_agent_id is None
    statements = []

    @event.listens_for(db.engine.sync_engine, "before_cursor_execute")
    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    async def public_url(*_args):
        # A size-one pool makes a leaked hydration transaction block this lookup.
        async with db.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return "https://files.test/report.txt"

    store = SimpleNamespace(async_get_public_url=AsyncMock(side_effect=public_url))
    groups = await asyncio.wait_for(_hydrate(db, store), timeout=10)
    assert len(groups) == 40
    assert all(group == groups[0] and group[0]["url"] for group in groups)
    assert store.async_get_public_url.await_count == 1
    artifact_queries = [
        statement
        for statement in statements
        if "FROM artifacts" in statement and not statement.startswith("SET")
    ]
    assert len(artifact_queries) == (3 if legacy else 2), statements
    assert any("content_work_scope" in statement for statement in artifact_queries) == legacy
    if db.engine.dialect.name == "postgresql":
        assert statements[0] == "SET LOCAL jit = off"
        async with db.engine.connect() as connection:
            assert await connection.scalar(text("SHOW jit")) == "on"

    # Reusing the same immutable refs must never cache an ACL or leak its old URL.
    async with db.factory() as session:
        row = await session.get(ArtifactRecordRow, db.ref)
        row.owner_email = None
        await session.commit()
    assert await _hydrate(db, store) == [[] for _ in range(40)]
    assert store.async_get_public_url.await_count == 1


@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_hydration_transaction_restores_settings_on_failure(
    hydration_db, monkeypatch, failure
):
    from cognis.core import artifact_access

    db = hydration_db
    entered = asyncio.Event()

    async def blocked(*_args, **_kwargs):
        entered.set()
        if failure == "error":
            raise RuntimeError("authorization query failed")
        await asyncio.Future()

    monkeypatch.setattr(artifact_access, "readable_artifact_ids", blocked)
    store = SimpleNamespace(async_get_public_url=AsyncMock())
    task = asyncio.create_task(_hydrate(db, store))
    await asyncio.wait_for(entered.wait(), timeout=5)
    if failure == "cancel":
        task.cancel()
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
        await task
    async with db.engine.connect() as connection:
        assert await connection.scalar(text("SELECT 1")) == 1
        if db.engine.dialect.name == "postgresql":
            assert await connection.scalar(text("SHOW jit")) == "on"
    store.async_get_public_url.assert_not_awaited()
