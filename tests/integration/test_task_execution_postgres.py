from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import schema as sa_schema
from sqlalchemy.ext.asyncio import create_async_engine

from cognis.core.cluster_signals import AsyncpgClusterSignalTransport, ClusterSignalService
from cognis.core.events import Event, EventBus, EventType
from cognis.core.queue_wakeup import publish_queue_wakeup
from cognis.core.task_execution import TaskExecutionStore
from cognis.store.database import create_session_factory
from cognis.store.models import Base
from cognis.store.queries import create_agent, create_task, create_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("COGNIS_TEST_POSTGRES_URL"),
        reason="COGNIS_TEST_POSTGRES_URL is not configured",
    ),
]


def _asyncpg_url() -> str:
    url = os.environ["COGNIS_TEST_POSTGRES_URL"]
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if not url.startswith("postgresql+asyncpg://"):
        raise ValueError("COGNIS_TEST_POSTGRES_URL must use PostgreSQL with asyncpg")
    return url


@pytest.mark.asyncio
async def test_postgres_queue_hint_survives_listener_reconnect() -> None:
    class ReadyTransport(AsyncpgClusterSignalTransport):
        def __init__(self, url):
            super().__init__(url)
            self.ready = asyncio.Event()

        async def listen(self, channel, callback):
            connection = await super().listen(channel, callback)
            self.ready.set()
            return connection

    buses = [EventBus(), EventBus()]
    received = asyncio.Event()

    async def wake(event: Event) -> None:
        if event.data.get("kind") == "task_queue_changed":
            received.set()

    buses[1].subscribe(EventType.CLUSTER_SCOPE_INVALIDATED, wake)
    services = [
        ClusterSignalService(
            database_url=_asyncpg_url(),
            controller_id=uuid.uuid4().hex,
            session_factory=None,
            event_bus=bus,
            scope_provider=lambda: [],
            transport=ReadyTransport(_asyncpg_url()),
        )
        for bus in buses
    ]
    try:
        for service in services:
            await service.start()
        for service in services:
            await asyncio.wait_for(service._transport.ready.wait(), 5)
        await publish_queue_wakeup(buses[0], services[0])
        await asyncio.wait_for(received.wait(), 2)
        received.clear()
        services[1]._transport.ready.clear()
        old_connection = services[1]._transport._connection
        await old_connection.close()
        await asyncio.wait_for(services[1]._transport.ready.wait(), 10)
        await publish_queue_wakeup(buses[0], services[0])
        await asyncio.wait_for(received.wait(), 2)
    finally:
        for service in services:
            await service.stop()


@pytest.mark.asyncio
async def test_postgres_task_claim_and_capacity_are_atomic() -> None:
    url = _asyncpg_url()
    schema_name = f"cognis_task_execution_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(url)
    async with admin_engine.begin() as connection:
        await connection.execute(sa_schema.CreateSchema(schema_name))
    engine = create_async_engine(
        url,
        connect_args={"server_settings": {"search_path": f'"{schema_name}"'}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            await create_user(
                session,
                email="owner@example.com",
                name="Owner",
                password_hash="hash",
            )
            await create_agent(
                session,
                agent_id="agent-1",
                owner_email="owner@example.com",
                name="Agent",
                status="active",
            )
            for task_id in ("task-1", "task-2"):
                await create_task(
                    session,
                    task_id=task_id,
                    created_by="owner@example.com",
                    agent_id="agent-1",
                    title=task_id,
                    status="ready",
                )
            await session.commit()

        first_store = TaskExecutionStore(
            factory,
            owner_id="controller-a:boot-a",
            max_active_global=1,
            max_active_per_agent=1,
        )
        second_store = TaskExecutionStore(
            factory,
            owner_id="controller-b:boot-b",
            max_active_global=1,
            max_active_per_agent=1,
        )
        assert await first_store.next_scheduled_delay() is None
        first, second = await asyncio.gather(first_store.claim_ready(), second_store.claim_ready())
        assert sum(claim is not None for claim in (first, second)) == 1
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(sa_schema.DropSchema(schema_name, cascade=True))
        await admin_engine.dispose()
