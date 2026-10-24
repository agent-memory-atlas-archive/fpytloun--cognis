"""Project result fan-out through real recipient policy and durable channel outbox."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from cognis.channels.delivery import ChannelDeliveryService
from cognis.core.events import EventBus
from cognis.core.project_task_delivery import fan_out_project_result
from cognis.core.workflow_engine import WorkflowEngine
from cognis.models.channel import ChannelCapabilities
from cognis.models.task import TaskDelivery, TaskModel
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import Base, ChannelDeliveryOutboxRow
from cognis.store.project_queries import remove_project_agent, upsert_project_agent
from cognis.store.queries import (
    create_agent,
    create_channel_account,
    create_conversation,
    create_project,
    create_project_grant,
    create_task,
    create_user,
    get_channel_account,
    get_conversation,
    get_task,
)


@pytest.fixture
async def setup(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'project-delivery.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        for email in ("owner@test.com", "member@test.com", "viewer@test.com", "outsider@test.com"):
            await create_user(session, email=email, name=email, password_hash="hash", role="user")
        agent = await create_agent(
            session, agent_id="project-agent", owner_email="owner@test.com", name="Project agent"
        )
        project = await create_project(session, owner_email="owner@test.com", name="Project")
        await upsert_project_agent(
            session,
            project_id=project.project_id,
            agent_id=agent.agent_id,
            added_by="owner@test.com",
        )
        grants = {}
        conversations = {}
        for email, role in (("member@test.com", "member"), ("viewer@test.com", "viewer")):
            grants[email] = await create_project_grant(
                session,
                project_id=project.project_id,
                granted_by="owner@test.com",
                grantee_user_email=email,
                permission=role,
            )
        for email in ("owner@test.com", "member@test.com", "viewer@test.com", "outsider@test.com"):
            account = await create_channel_account(
                session,
                channel_type="matrix",
                display_name=email,
                agent_id=agent.agent_id,
                user_email=email,
                preferred_for_task_delivery=True,
            )
            conversation = await create_conversation(
                session,
                user_email=email,
                agent_id=agent.agent_id,
                context_type="matrix",
                context_data={
                    "channel_type": "matrix",
                    "account_id": account.account_id,
                    "chat_id": email,
                },
            )
            account.default_conversation_id = conversation.conversation_id
            conversations[email] = conversation.conversation_id
        row = await create_task(
            session,
            created_by="owner@test.com",
            agent_id=agent.agent_id,
            title="Shared result",
            status="completed",
            project_id=project.project_id,
        )
        row.result_summary = "Final result"
        await session.commit()
    task = TaskModel(
        task_id=row.task_id,
        title=row.title,
        created_by=row.created_by,
        agent_id=row.agent_id,
        project_id=row.project_id,
        status="completed",
        result_summary=row.result_summary,
    )
    try:
        yield factory, task, grants, conversations
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_success_fanout_is_recipient_scoped_and_idempotent(setup):
    factory, task, _, conversations = setup
    adapter = SimpleNamespace(
        capabilities=ChannelCapabilities(supports_idempotent_send=True),
        send_message=AsyncMock(return_value="receipt"),
    )
    manager = SimpleNamespace(find_adapter_for_channel=lambda *args: (adapter, object()))
    bus = EventBus()
    events = []
    bus.subscribe_all(lambda event: events.append(event))
    service = ChannelDeliveryService(
        session_factory=factory, event_bus=bus, channel_manager_ref=lambda: manager
    )
    await fan_out_project_result(task, factory, service)
    await service.recover_pending_deliveries()
    await fan_out_project_result(task, factory, service)
    await service.recover_pending_deliveries()
    assert adapter.send_message.await_count == 2
    assert {call.args[0].chat_id for call in adapter.send_message.await_args_list} == {
        "member@test.com",
        "viewer@test.com",
    }
    assert not events  # No lifecycle events or follow-up agent turns for recipients.
    async with factory() as session:
        rows = list(await session.scalars(select(ChannelDeliveryOutboxRow)))
    assert {row.conversation_id for row in rows} == {
        conversations["member@test.com"],
        conversations["viewer@test.com"],
    }
    assert all(row.status == "sent" and row.source_type == "project_task_result" for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "failed"),
        ("status", "cancelled"),
        ("status", "paused"),
        ("status", "running"),
        ("visibility", "private"),
        ("delivery_mode", "same_conversation"),
        ("delivery_mode", "specific_conversation"),
        ("delivery_mode", "latest_active_for_agent"),
        ("delivery_mode", "silent"),
        ("applied_completion_mode", "silent"),
        ("project_id", None),
    ],
)
async def test_non_final_private_and_other_modes_do_not_fanout(setup, field, value):
    factory, task, _, _ = setup
    async with factory() as session:
        row = await get_task(session, task.task_id)
        setattr(row, field, value)
        await session.commit()
    delivery = SimpleNamespace(deliver_task_to_conversation=AsyncMock())
    await fan_out_project_result(task, factory, delivery)
    delivery.deliver_task_to_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoked_membership_and_unavailable_agent_are_excluded(setup):
    factory, task, grants, _ = setup
    async with factory() as session:
        grant = await session.merge(grants["member@test.com"])
        grant.revoked_at = datetime.now(UTC)
        await remove_project_agent(session, project_id=task.project_id, agent_id=task.agent_id)
        await session.commit()
    delivery = SimpleNamespace(deliver_task_to_conversation=AsyncMock())
    await fan_out_project_result(task, factory, delivery)
    delivery.deliver_task_to_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_delivery_rechecks_membership_before_retry(setup):
    factory, task, grants, _ = setup
    adapter = SimpleNamespace(
        capabilities=ChannelCapabilities(supports_idempotent_send=True),
        send_message=AsyncMock(side_effect=RuntimeError("temporarily unavailable")),
    )
    manager = SimpleNamespace(find_adapter_for_channel=lambda *args: (adapter, object()))
    service = ChannelDeliveryService(
        session_factory=factory, event_bus=EventBus(), channel_manager_ref=lambda: manager
    )
    await fan_out_project_result(task, factory, service)
    await service.recover_pending_deliveries()
    async with factory() as session:
        for detached in grants.values():
            grant = await session.merge(detached)
            grant.revoked_at = datetime.now(UTC)
        rows = list(await session.scalars(select(ChannelDeliveryOutboxRow)))
        await session.commit()
    adapter.send_message.reset_mock()
    for row in rows:
        await service._deliver_outbox(
            delivery_id=row.delivery_id,
            final_content=None,
            fallback_text=None,
            attachments=None,
            deliverable_id=None,
            ignore_next_attempt=True,
        )
    adapter.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_engine_keeps_owner_followup_and_fans_out_scheduled_success(setup, monkeypatch):
    factory, task, _, _ = setup
    task.source_type = "scheduler"
    task.delivery = TaskDelivery(mode="preferred_channel")
    engine = object.__new__(WorkflowEngine)
    engine._session_factory = factory
    engine._channel_delivery = SimpleNamespace(deliver_task_to_conversation=AsyncMock())
    engine._resolve_task_delivery_conversation = AsyncMock(return_value="owner-conversation")
    engine._deliver_task_result_default = AsyncMock()
    monkeypatch.setattr("cognis.core.workflow_engine.assert_task_execution_fence", AsyncMock())
    await engine._deliver_task_result(task)
    engine._deliver_task_result_default.assert_awaited_once_with(task, "owner-conversation")
    assert engine._channel_delivery.deliver_task_to_conversation.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["archived", "preference", "route", "agent", "private", "failed"]
)
async def test_pending_delivery_suppresses_stale_destinations(setup, change):
    factory, task, _, conversations = setup
    adapter = SimpleNamespace(
        capabilities=ChannelCapabilities(supports_idempotent_send=True),
        send_message=AsyncMock(return_value="receipt"),
    )
    manager = SimpleNamespace(find_adapter_for_channel=lambda *args: (adapter, object()))
    service = ChannelDeliveryService(
        session_factory=factory, event_bus=EventBus(), channel_manager_ref=lambda: manager
    )
    await fan_out_project_result(task, factory, service)
    async with factory() as session:
        for email in ("member@test.com", "viewer@test.com"):
            conversation = await get_conversation(session, conversations[email])
            if change == "archived":
                conversation.status = "archived"
            elif change == "preference":
                account = await get_channel_account(
                    session, conversation.context_data["account_id"]
                )
                account.preferred_for_task_delivery = False
            elif change == "route":
                conversation.context_data = {**conversation.context_data, "chat_id": "new-room"}
        if change == "agent":
            await remove_project_agent(session, task.project_id, task.agent_id)
        elif change == "private":
            row = await get_task(session, task.task_id)
            row.visibility = "private"
        elif change == "failed":
            row = await get_task(session, task.task_id)
            row.status = "failed"
        await session.commit()
    await service.recover_pending_deliveries()
    adapter.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_preference_change_does_not_duplicate_recipient_result(setup):
    factory, task, _, conversations = setup
    adapter = SimpleNamespace(
        capabilities=ChannelCapabilities(supports_idempotent_send=True),
        send_message=AsyncMock(return_value="receipt"),
    )
    manager = SimpleNamespace(find_adapter_for_channel=lambda *args: (adapter, object()))
    service = ChannelDeliveryService(
        session_factory=factory, event_bus=EventBus(), channel_manager_ref=lambda: manager
    )
    await fan_out_project_result(task, factory, service)
    await service.recover_pending_deliveries()
    async with factory() as session:
        old = await get_conversation(session, conversations["member@test.com"])
        account = await get_channel_account(session, old.context_data["account_id"])
        new = await create_conversation(
            session,
            user_email="member@test.com",
            agent_id=task.agent_id,
            context_type="matrix",
            context_data={**old.context_data, "chat_id": "new-room"},
        )
        account.default_conversation_id = new.conversation_id
        await session.commit()
    await fan_out_project_result(task, factory, service)
    await service.recover_pending_deliveries()
    assert adapter.send_message.await_count == 2
    async with factory() as session:
        rows = list(await session.scalars(select(ChannelDeliveryOutboxRow)))
        assert len(rows) == 2
