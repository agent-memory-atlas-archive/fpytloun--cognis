import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cognis.core.executor_policy import ExecutorPolicy
from cognis.core.executor_pool import resolve_executor_pool
from cognis.store.models import Base, ExecutorRow
from cognis.store.queries import list_executors


@pytest.mark.asyncio
async def test_explicit_pool_does_not_decode_unselected_or_unauthorized_inventory():
    decoded = []

    def decode(value):
        decoded.append(value)
        return json.loads(value)

    engine = create_async_engine("sqlite+aiosqlite://", json_deserializer=decode)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            for key, owner in [
                ("selected", "owner@test"),
                ("unselected", "owner@test"),
                ("shared", None),
                ("private", "other@test"),
            ]:
                session.add(
                    ExecutorRow(
                        executor_id=key,
                        name=key,
                        owner_email=owner,
                        executor_type="websocket",
                        labels={"location": key},
                        observed_tools=[{"name": key, "schema": key * 500}],
                    )
                )
            await session.commit()
        decoded.clear()
        pool = await resolve_executor_pool(
            session_factory=factory,
            agent_execution={
                "executor_id": "selected",
                "additional_executors": [
                    {"executor_id": "shared"},
                    {"executor_id": "private"},
                ],
            },
            user_email="owner@test",
            executor_owner_email="owner@test",
            policy=ExecutorPolicy(),
        )
        assert pool.primary[0].observed_tools[0]["name"] == "selected"
        assert [t.executor_id for t in pool.additional] == ["shared", "private"]
        assert not any("unselected" in value or "private" in value for value in decoded)
        decoded.clear()
        async with factory() as session:
            assert await list_executors(session, executor_ids=[]) == []
        assert not decoded
        pool = await resolve_executor_pool(
            session_factory=factory,
            agent_execution={"executor_selector": {"location": "unselected"}},
            user_email="owner@test",
            executor_owner_email="owner@test",
            policy=ExecutorPolicy(),
        )
        assert pool.primary[0].observed_tools[0]["name"] == "unselected"
    finally:
        await engine.dispose()
