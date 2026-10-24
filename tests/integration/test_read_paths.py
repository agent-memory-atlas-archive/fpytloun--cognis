"""Local, opt-in PostgreSQL and SQLite read-path boundary regressions."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cognis.core.agent_registry import SYSTEM_AGENTS, AgentRegistry
from cognis.store.models import Agent, AgentGrantRow, Base, User
from cognis.store.queries import (
    list_active_agents_summary,
    list_agent_readiness_snapshots,
    list_visible_agents,
    upsert_system_agent_override,
)


@pytest.fixture(params=["sqlite", "postgresql"])
async def read_db(request, tmp_path):
    url = (
        f"sqlite+aiosqlite:///{tmp_path}/reads.db"
        if request.param == "sqlite"
        else os.environ.get("COGNIS_READ_PATH_TEST_DATABASE_URL")
    )
    if not url:
        pytest.skip("requires isolated COGNIS_READ_PATH_TEST_DATABASE_URL")
    engine = create_async_engine(url)
    schema = f"read_paths_{uuid.uuid4().hex}" if request.param == "postgresql" else None
    if schema:
        async with engine.begin() as conn:
            await conn.execute(sa.schema.CreateSchema(schema))
        engine = engine.execution_options(schema_translate_map={None: schema})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        for owner in ("reads-owner@local.test", "reads-other@local.test"):
            db.add(User(email=owner, name=owner))
        await db.flush()
        for agent_id, owner in [
            ("reads-owned", "reads-owner@local.test"),
            ("reads-shared", "reads-other@local.test"),
            ("reads-private", "reads-other@local.test"),
        ]:
            db.add(
                Agent(
                    agent_id=agent_id,
                    owner_email=owner,
                    name=agent_id,
                    status="active",
                    agent_type="primary",
                    system_prompt="p" * 100_000,
                    tools={"catalog": "t" * 100_000},
                )
            )
        await db.flush()
        db.add(
            AgentGrantRow(
                grant_id="reads-grant",
                agent_id="reads-shared",
                grantee_type="user",
                grantee_user_email="reads-owner@local.test",
                granted_by="reads-other@local.test",
                permission="use",
                executor_scope="owner_executor",
            )
        )
        await db.commit()
    yield factory
    if schema:
        async with engine.begin() as conn:
            await conn.execute(sa.schema.DropSchema(schema, cascade=True))
    await engine.dispose()


async def test_narrow_queries_and_live_revocation_across_independent_sessions(read_db):
    statements = []
    engine = read_db.kw["bind"]

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with read_db() as db:
            summary = await list_active_agents_summary(db, "reads-owner@local.test")
            assert {row["agent_id"] for row in summary} == {"reads-owned", "reads-shared"}
            assert not db.identity_map
        assert len(statements) == 1
        assert "agents.system_prompt" not in statements[0]
        assert "agents.tools" not in statements[0]
        statements.clear()
        async with read_db() as db:
            snapshots = await list_agent_readiness_snapshots(db, "reads-owner@local.test")
            assert [row.name for row in snapshots] == ["reads-owned"]
            assert not db.identity_map
        assert len(statements) == 1
        assert "agents.system_prompt" not in statements[0]
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", capture)

    async def visible(owner):
        async with read_db() as db:
            return [
                (row.agent_id, grant is not None)
                for row, grant in await list_visible_agents(db, owner)
            ]

    owner, other = await asyncio.gather(
        visible("reads-owner@local.test"), visible("reads-other@local.test")
    )
    assert owner[0] == ("reads-owned", False)
    assert set(owner) == {("reads-owned", False), ("reads-shared", True)}
    assert set(other) == {("reads-shared", False), ("reads-private", False)}
    async with read_db() as db:
        await db.execute(
            sa.update(AgentGrantRow)
            .where(AgentGrantRow.grant_id == "reads-grant")
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
    assert await visible("reads-owner@local.test") == [("reads-owned", False)]
    async with read_db() as db:
        assert [
            row["agent_id"]
            for row in await list_active_agents_summary(db, "reads-owner@local.test")
        ] == ["reads-owned"]


async def test_registry_batches_overrides_without_mutating_full_definitions(read_db):
    registry = AgentRegistry(read_db)
    base = next(agent for agent in SYSTEM_AGENTS.values() if agent.allow_user_override)
    original = base.model_dump(mode="json")
    async with read_db() as db:
        await upsert_system_agent_override(
            db,
            owner_email="reads-owner@local.test",
            agent_id=base.agent_id,
            disabled=True,
            tools_override={"allowed": ["read"]},
            llm_config_override={"model": "read-paths-fixture"},
        )
        await upsert_system_agent_override(
            db,
            owner_email="reads-other@local.test",
            agent_id=base.agent_id,
            tools_override={"allowed": ["write"]},
        )
        await db.commit()
    engine = read_db.kw["bind"]
    statements = []

    def capture(conn, cursor, sql, parameters, context, many):
        statements.append(sql)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        agents = await registry.list_all(owner_email="reads-owner@local.test")
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", capture)
    # PostgreSQL fixtures qualify names with their isolated schema.
    assert sum("system_agent_overrides" in sql for sql in statements) <= 1
    assert len(statements) == 3  # One override batch, owned definitions, shared definitions.
    assert sum("JOIN" in sql and "agent_grants" in sql for sql in statements) == 1
    owned = next(agent for agent in agents if agent.agent_id == "reads-owned")
    assert owned.system_prompt == "p" * 100_000
    assert owned.tools == {"catalog": "t" * 100_000}
    assert base.agent_id not in {agent.agent_id for agent in agents}
    disabled = next(
        agent
        for agent in await registry.list_all(
            owner_email="reads-owner@local.test",
            include_disabled=True,
        )
        if agent.agent_id == base.agent_id
    )
    assert disabled.disabled
    assert disabled.status == "disabled"
    assert disabled.tools == {"allowed": ["read"]}
    assert disabled.llm_config.model == "read-paths-fixture"
    foreign = next(
        agent
        for agent in await registry.list_all(
            owner_email="reads-other@local.test",
        )
        if agent.agent_id == base.agent_id
    )
    assert not foreign.disabled
    assert foreign.tools == {"allowed": ["write"]}
    assert base.model_dump(mode="json") == original
