"""Recipient policy for successful project task channel notifications."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognis.core.project_access import agent_usable_in_project, can_read_task
from cognis.models.task import TaskModel
from cognis.store.models import ChannelDeliveryOutboxRow, Task
from cognis.store.project_queries import get_project_agent
from cognis.store.queries import (
    get_agent,
    get_conversation,
    get_conversation_channel_route,
    get_latest_active_conversation_for_channel_account,
    get_preferred_channel_account_for_agent,
    get_project,
    get_task,
    list_project_grants,
)

logger = logging.getLogger(__name__)


def project_result_is_shareable(task: Task) -> bool:
    """Exclude private, silent, unsuccessful, and non-final task notifications."""
    return bool(
        task.project_id
        and task.visibility == "project"
        and task.status == "completed"
        and task.delivery_mode == "preferred_channel"
        and task.applied_completion_mode != "silent"
    )


async def project_result_recipient_allowed(
    session: AsyncSession, task_id: str, user_email: str
) -> bool:
    """Recheck both task readability and agent access, including on outbox retries."""
    row = await get_task(session, task_id)
    if row is None:
        return False
    if not project_result_is_shareable(row) or row.created_by == user_email:
        return False
    if not await can_read_task(session, row, user_email):
        return False
    agent = await get_agent(session, row.agent_id)
    if agent is None:
        return False
    if await agent_usable_in_project(
        session, agent=agent, user_email=user_email, project_id=row.project_id
    ):
        return True
    # Receiving an informational result does not require permission to run the agent.
    return (
        row.project_id is not None
        and await get_project_agent(session, row.project_id, row.agent_id) is not None
    )


async def preferred_project_result_targets(session: AsyncSession, task: TaskModel) -> list[str]:
    """Resolve each eligible non-owner's own active preferred-channel conversation."""
    row = await get_task(session, task.task_id)
    if row is None or not row.project_id or not project_result_is_shareable(row):
        return []
    project = await get_project(session, row.project_id)
    if project is None or project.status == "deleted":
        return []
    recipients = {project.owner_email}
    recipients.update(
        grant.grantee_user_email
        for grant in await list_project_grants(session, project.project_id)
        if grant.revoked_at is None
        and grant.grantee_type == "user"
        and grant.grantee_user_email is not None
    )
    recipients.discard(task.created_by)
    targets: list[str] = []
    for user_email in sorted(recipients):
        if not await project_result_recipient_allowed(session, task.task_id, user_email):
            continue
        target = await preferred_channel_target(
            session, user_email=user_email, agent_id=task.agent_id
        )
        if target is not None:
            targets.append(target)
    return targets


async def preferred_channel_target(
    session: AsyncSession, *, user_email: str, agent_id: str
) -> str | None:
    """Resolve an active conversation belonging to this user and preferred account."""
    account = await get_preferred_channel_account_for_agent(
        session, user_email=user_email, agent_id=agent_id
    )
    if account is None:
        return None
    conversation = (
        await get_conversation(session, account.default_conversation_id)
        if account.default_conversation_id
        else None
    )
    candidates = [conversation]
    candidates.append(
        await get_latest_active_conversation_for_channel_account(
            session,
            user_email=user_email,
            agent_id=agent_id,
            account_id=account.account_id,
            prefer_unthreaded=True,
        )
    )
    for candidate in candidates:
        if (
            candidate is None
            or candidate.status != "active"
            or candidate.user_email != user_email
            or candidate.agent_id != agent_id
        ):
            continue
        route = await get_conversation_channel_route(session, candidate.conversation_id)
        if route is not None and route[1] == account.account_id and route[4] == user_email:
            return candidate.conversation_id
    return None


async def project_result_route_allowed(
    session: AsyncSession, row: ChannelDeliveryOutboxRow
) -> bool:
    """Fence delayed delivery against revoked access and changed channel routes."""
    if not row.source_id or not await project_result_recipient_allowed(
        session, row.source_id, row.user_email
    ):
        return False
    task = await get_task(session, row.source_id)
    conversation = await get_conversation(session, row.conversation_id)
    if (
        task is None
        or conversation is None
        or conversation.status != "active"
        or conversation.user_email != row.user_email
        or conversation.agent_id != task.agent_id
    ):
        return False
    account = await get_preferred_channel_account_for_agent(
        session, user_email=row.user_email, agent_id=task.agent_id
    )
    route = await get_conversation_channel_route(session, row.conversation_id)
    return (
        account is not None
        and account.account_id == row.account_id
        and route == (row.channel_type, row.account_id, row.chat_id, row.thread_id, row.user_email)
        and await preferred_channel_target(
            session, user_email=row.user_email, agent_id=task.agent_id
        )
        == row.conversation_id
    )


async def fan_out_project_result(
    task: TaskModel,
    session_factory: async_sessionmaker[AsyncSession],
    channel_delivery: Any,
) -> None:
    """Distribute the final result without invoking recipient agents or task controls."""
    if (
        channel_delivery is None
        or not task.project_id
        or task.status != "completed"
        or task.delivery.mode != "preferred_channel"
        or task.applied_completion_mode == "silent"
    ):
        return
    try:
        async with session_factory() as session:
            targets = await preferred_project_result_targets(session, task)
    except Exception:
        logger.warning(
            "Project result recipient resolution failed",
            extra={"extra_data": {"task_id": task.task_id}},
        )
        return
    data = task.result_data or {}
    content = data.get("final_channel_content")
    if not isinstance(content, str) or not content.strip():
        content = data.get("final_content") if data.get("final_format") != "html" else None
    if not isinstance(content, str) or not content.strip():
        content = task.result_summary or ""
    message = f'Task "{task.title}" completed.\n\n{content}'.strip()
    for conversation_id in targets:
        try:
            await channel_delivery.deliver_task_to_conversation(
                conversation_id,
                task_id=task.task_id,
                content=message,
                project_result=True,
            )
        except Exception:
            # A recipient's unavailable route must not break the owner's delivery.
            logger.warning(
                "Project result recipient delivery failed",
                extra={"extra_data": {"task_id": task.task_id, "conversation_id": conversation_id}},
            )
