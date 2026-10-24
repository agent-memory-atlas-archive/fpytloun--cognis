"""Explicit content grants. Read access never implies permission to reshare."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from cognis.store.models import Agent, ArtifactGrantRow, ArtifactRecordRow, DeliverableRow


async def grant_referenced_inputs(
    session: AsyncSession,
    *,
    owner_email: str,
    source_agent_id: str,
    target_session_id: str,
    text: str,
    source_session_id: str | None = None,
    source_conversation_id: str | None = None,
) -> None:
    """Grant only exact authorized refs explicitly handed to a worker."""
    import re

    from cognis.core.artifact_access import content_read_predicate
    from cognis.core.artifact_entitlements import add_grant
    from cognis.store.models import Session

    refs = set(re.findall(r"\b(?:art|att|doc|img|dlv)_[0-9a-f]{32}\b", text))
    if not refs:
        return
    target = await session.get(Session, target_session_id)
    if target is None or target.user_email != owner_email:
        raise ValueError("Artifact input recipient is unavailable")
    recipient = (
        f"scope:{target.artifact_scope_id or target.session_id}"
        if target.agent_id.startswith("system:")
        else target.agent_id
    )
    for model, ref_col in (
        (ArtifactRecordRow, ArtifactRecordRow.artifact_id),
        (DeliverableRow, DeliverableRow.deliverable_id),
    ):
        predicate = await content_read_predicate(
            session,
            owner_email=owner_email,
            agent_id=source_agent_id,
            conversation_id=source_conversation_id,
            session_id=source_session_id,
            model=model,
        )
        for ref in await session.scalars(sa.select(ref_col).where(ref_col.in_(refs), predicate)):
            await session.run_sync(add_grant, owner_email, ref, recipient, "input")


async def grant_artifact_inputs(
    session: AsyncSession,
    *,
    owner_email: str,
    agent_id: str,
    content_refs: list[str],
) -> None:
    """Persist only already-authorized input refs at the trusted admission boundary."""
    for content_ref in set(content_refs):
        key = dict(
            owner_email=owner_email, content_ref=content_ref, agent_id=agent_id, source="input"
        )
        if await session.get(ArtifactGrantRow, key) is None:
            session.add(ArtifactGrantRow(**key))


async def set_artifact_share(
    session: AsyncSession,
    *,
    owner_email: str,
    owner_agent_id: str | None,
    content_ref: str,
    grantee_agent_id: str,
    revoke: bool = False,
) -> None:
    """Grant/revoke read access as the owning agent or authenticated human owner."""
    row: DeliverableRow | ArtifactRecordRow | None
    if content_ref.startswith("dlv_"):
        row = await session.get(DeliverableRow, content_ref)
    else:
        row = await session.get(ArtifactRecordRow, content_ref)
    grantee = await session.get(Agent, grantee_agent_id)
    if (
        row is None
        or row.owner_email != owner_email
        or (owner_agent_id is not None and row.owner_agent_id != owner_agent_id)
        or grantee is None
        or grantee.owner_email != owner_email
        or grantee.status != "active"
        or grantee_agent_id.startswith("system:")
        or row.status == "deleted"
    ):
        raise ValueError("Content reference or recipient is unavailable.")
    key = dict(
        owner_email=owner_email,
        content_ref=content_ref,
        agent_id=grantee_agent_id,
        source="explicit",
    )
    if revoke:
        await session.execute(sa.delete(ArtifactGrantRow).filter_by(**key))
    elif await session.get(ArtifactGrantRow, key) is None:
        await session.merge(ArtifactGrantRow(**key))
