"""Durable affinity reservations use the same CAS rules on SQLite and PostgreSQL."""

import asyncio
import importlib
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from cognis.providers.llm.bindings import InferenceBindings
from cognis.providers.llm.recovery_policy import NamedRouteConfig, RouteTarget
from cognis.providers.llm.route_store import InferenceRouteStore
from cognis.store.models import InferenceBinding, InferenceRoute, LLMProvider, ModelRouting


@pytest_asyncio.fixture(params=["sqlite", "postgresql"])
async def sessions(tmp_path, request):
    schema = None
    if request.param == "postgresql":
        url = os.environ.get("COGNIS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("Set COGNIS_TEST_POSTGRES_URL to an isolated PostgreSQL database")
        schema = f"inference_test_{uuid.uuid4().hex}"
        engine = create_async_engine(
            url, execution_options={"schema_translate_map": {None: schema}}
        )
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'routing.db'}")
    async with engine.begin() as connection:
        if schema:
            await connection.execute(CreateSchema(schema))
        for table in (
            LLMProvider.__table__,
            InferenceBinding.__table__,
            InferenceRoute.__table__,
            ModelRouting.__table__,
        ):
            await connection.run_sync(table.create)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


@pytest.mark.asyncio
async def test_first_selection_and_replacement_are_reserved_before_dispatch(sessions):
    a, b = InferenceBindings(sessions), InferenceBindings(sessions)
    first, second = await asyncio.gather(
        a.get_or_create(owner="alice", session_identity="session", reference="route"),
        b.get_or_create(owner="alice", session_identity="session", reference="route"),
    )
    target_a = RouteTarget(provider_id="provider-a", model="chat")
    target_b = RouteTarget(provider_id="provider-b", model="chat")
    claims = await asyncio.gather(
        a.reserve(first, target_a, lease_seconds=10),
        b.reserve(second, target_b, lease_seconds=10),
    )
    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    winner = winners[0]
    assert (await b.read(first.key)).reserved
    assert await a.commit(winner)
    assert (await b.read(first.key)).target == winner.pending
    assert not await b.commit(winner)
    await b.release(winner)
    assert (await a.read(first.key)).target == winner.pending


@pytest.mark.asyncio
async def test_expired_claim_cannot_overwrite_or_release_new_reservation(sessions):
    bindings = InferenceBindings(sessions)
    initial = await bindings.get_or_create(
        owner="alice", session_identity="session", reference="route"
    )
    stale = await bindings.reserve(
        initial, RouteTarget(provider_id="one", model="chat"), lease_seconds=10
    )
    async with sessions() as session:
        await session.execute(
            update(InferenceBinding)
            .where(InferenceBinding.binding_key == initial.key)
            .values(claim_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    current = await bindings.reserve(
        await bindings.read(initial.key),
        RouteTarget(provider_id="two", model="chat"),
        lease_seconds=10,
    )
    assert current is not None and stale is not None
    assert not await bindings.commit(stale)
    await bindings.release(stale)
    assert (await bindings.read(initial.key)).claim_token == current.claim_token
    assert await bindings.commit(current)


@pytest.mark.asyncio
async def test_binding_key_separates_owner_session_and_route(sessions):
    bindings = InferenceBindings(sessions)
    pairs = [
        ("alice", "one", "route"),
        ("bob", "one", "route"),
        ("alice", "two", "route"),
        ("alice", "one", "other-route"),
    ]
    snapshots = [
        await bindings.get_or_create(owner=owner, session_identity=identity, reference=reference)
        for owner, identity, reference in pairs
    ]
    assert len({snapshot.key for snapshot in snapshots}) == len(pairs)


@pytest.mark.asyncio
async def test_route_revision_and_owner_checks(sessions):
    store = InferenceRouteStore(sessions)
    config = NamedRouteConfig(name="chat", targets=[{"provider_id": "provider-a", "model": "chat"}])
    route = await store.save(config, owner="alice")
    assert (await store.get("cognis/chat", "alice")).route_id == route.route_id
    with pytest.raises(ValueError, match="Unknown"):
        await store.get("cognis/chat", "bob")
    with pytest.raises(ValueError, match="not owned"):
        await store.save(config, owner="bob", route_id=route.route_id, expected_revision=1)
    await store.save(config, owner="alice", route_id=route.route_id, expected_revision=1)
    with pytest.raises(ValueError, match="changed"):
        await store.save(config, owner="alice", route_id=route.route_id, expected_revision=1)


@pytest.mark.asyncio
async def test_migration_matches_orm_schema(sessions):
    engine = sessions.kw["bind"]
    migration = importlib.import_module("cognis.store.migrations.versions.161_inference_routes")

    def verify(connection):
        schema = connection.get_execution_options().get("schema_translate_map", {}).get(None)
        tables = (InferenceBinding.__table__, InferenceRoute.__table__)

        def snapshot():
            inspector = inspect(connection)
            return {
                table.name: {
                    "columns": [
                        (column["name"], str(column["type"]), column["nullable"])
                        for column in inspector.get_columns(table.name, schema=schema)
                    ],
                    "indexes": inspector.get_indexes(table.name, schema=schema),
                    "unique": inspector.get_unique_constraints(table.name, schema=schema),
                }
                for table in tables
            }

        expected = snapshot()
        for table in tables:
            table.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert snapshot() == expected
        # Existing bootstrap paths may use checkfirst after migrations.
        for table in tables:
            table.create(connection, checkfirst=True)
        assert snapshot() == expected
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

    async with engine.begin() as connection:
        await connection.run_sync(verify)
