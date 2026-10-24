"""Hook admission checks against canonical attached-work lifecycle sources."""

from typing import Any

from cognis.store.queries import (
    list_active_delegation_sessions,
    list_active_tasks_by_source_conversation,
    list_open_managed_conversation_links,
    list_pending_notification_types_by_conversation,
)


async def has_attached_work(factory: Any, scheduler: Any, conversation: Any) -> bool:
    """Like recap, do not mistake an idle parent for settled background work."""
    cid = conversation.conversation_id
    owner = conversation.user_email
    async with factory() as db:
        if await list_pending_notification_types_by_conversation(db, owner, [cid]):
            return True
        if await list_active_delegation_sessions(
            db,
            user_email=owner,
            controller_conversation_id=cid,
            limit=1,
        ) or await list_active_tasks_by_source_conversation(
            db,
            created_by=owner,
            controller_conversation_id=cid,
            limit=1,
        ):
            return True
        links = await list_open_managed_conversation_links(
            db,
            user_email=owner,
            controller_conversation_id=cid,
            limit=501,
        )
    if len(links) == 501:
        return True
    for link in links:
        if (
            link.turn_state in {"queued", "running"}
            or await scheduler.durable_running_turn_state(link.target_conversation_id) is not None
            or await scheduler.get_queued_messages(link.target_conversation_id)
        ):
            return True
    return False
