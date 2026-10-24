"""Read-only avatar references authorized by the owning agent's use policy."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from cognis.core.project_access import resolve_agent_use_grant
from cognis.store.models import Agent, User


@dataclass(frozen=True)
class AgentAvatarReference:
    artifact_id: str
    owner_email: str
    mime_type: str
    size_bytes: int
    namespace: str = "avatars"
    filename: str = "image"
    kind: str = "image"

    @property
    def object_id(self) -> str:
        return self.artifact_id


async def resolve_agent_avatar_reference(
    session: Any, artifact_store: Any, image_id: str, acting_user_email: str | None
) -> AgentAvatarReference | None:
    """Require a current agent link, use access, and matching storage ownership.

    Both primary and secondary agents live in Agent. Project avatars deliberately
    do not qualify; they have a different access policy.
    """
    if not acting_user_email or not image_id.startswith("img_"):
        return None
    user = await session.get(User, acting_user_email)
    if user is None or not user.is_active:
        return None
    avatar = await get_current_agent_avatar_reference(session, artifact_store, image_id)
    if avatar is None:
        return None
    agents = (
        (
            await session.execute(
                select(Agent).where(
                    Agent.avatar_image_id == image_id, Agent.owner_email == avatar.owner_email
                )
            )
        )
        .scalars()
        .all()
    )
    for agent in agents:
        if agent.owner_email != acting_user_email:
            grant = await resolve_agent_use_grant(
                session, agent_id=agent.agent_id, user_email=acting_user_email, project_id=None
            )
            if grant is None:
                continue
        return avatar
    return None


async def get_current_agent_avatar_reference(
    session: Any, artifact_store: Any, image_id: str
) -> AgentAvatarReference | None:
    """Resolve storage identity only, NOT access.

    Used after caller authorization above, or after validating a bearer URL's
    signature in the content-serving endpoint. Never an authorization fallback.
    """
    if not image_id.startswith("img_"):
        return None
    owners = set(
        (
            await session.execute(
                select(Agent.owner_email).where(Agent.avatar_image_id == image_id)
            )
        ).scalars()
    )
    if not owners:
        return None
    meta = await artifact_store.async_load_metadata("avatars", image_id, "image")
    if meta is None or meta.owner_email not in owners:
        return None
    if not await artifact_store.async_exists("avatars", image_id, "image"):
        return None
    if meta.content_type not in {"image/png", "image/jpeg", "image/webp"}:
        return None
    return AgentAvatarReference(
        artifact_id=image_id,
        owner_email=meta.owner_email,
        mime_type=meta.content_type,
        size_bytes=meta.size,
    )
