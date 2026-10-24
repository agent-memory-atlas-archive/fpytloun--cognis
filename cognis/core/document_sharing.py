"""Human-owned document sharing. Explicit grants are independent of inherited access."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast

import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cognis.store.models import (
    Agent,
    ArtifactGrantRow,
    ArtifactRecordRow,
    DeliverableRow,
    ProjectAgentRow,
)


class AgentAccess(BaseModel):
    agent_id: str
    name: str
    explicit: bool
    inherited: bool
    avatar_url: str | None = None


class DocumentAccess(BaseModel):
    agents: list[AgentAccess]
    project_id: str | None
    owner_agent_id: str | None


class AgentSharesRequest(BaseModel):
    agent_ids: list[str] = Field(max_length=100)


class PublicLink(BaseModel):
    url: str
    expires_at: datetime
    mode: Literal["view", "download"]


async def public_link(
    session_factory: Any,
    artifact_store: Any,
    owner: str,
    kind: str,
    ref: str,
    *,
    mode: Literal["view", "download"] | None,
    ttl_seconds: int,
    base_url: str,
) -> PublicLink:
    """Mint owner-controlled, mode-bound, exact-revision links using existing signers."""
    from cognis.artifacts.preview import supports_artifact_view
    from cognis.core.deliverable_links import signed_deliverable_view_link

    async with session_factory() as session:
        row = await owned_document(session, kind, ref, owner)
    if isinstance(row, DeliverableRow):
        effective = mode or "view"
        link = signed_deliverable_view_link(
            artifact_store, ref, base_url=base_url, ttl_seconds=ttl_seconds
        )
        token = link.url.rsplit("/", 1)[1]
        public_base = link.url.rsplit("/api/v1/deliverables/s/", 1)[0]
        url = (
            link.url
            if effective == "view"
            else (
                f"{public_base}/api/v1/deliverables/share/{token}"
                + ("/download.md" if row.format == "markdown" else "/download.html")
            )
        )
        return PublicLink(url=url, expires_at=link.expires_at, mode=effective)
    previewable = supports_artifact_view(row.filename, row.mime_type)
    effective = mode or ("view" if previewable else "download")
    if effective == "view" and not previewable:
        raise ValueError("This format cannot be viewed in the browser. Select Download file.")
    if row.expires_at:
        remaining = int((row.expires_at.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds())
        if remaining < 60:
            raise ValueError("This artifact expires in less than one minute.")
        ttl_seconds = min(ttl_seconds, remaining)
    url = await artifact_store.async_get_public_url(
        row.namespace,
        row.object_id,
        row.filename,
        ttl_seconds=ttl_seconds,
        mode=effective,
    )
    from datetime import timedelta

    return PublicLink(
        url=url, mode=effective, expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    )


async def validate_recipients(session: AsyncSession, owner: str, agent_ids: list[str]) -> None:
    """Allow only the person's active primary agents as explicit recipients."""
    allowed = set(
        await session.scalars(
            sa.select(Agent.agent_id).where(
                Agent.owner_email == owner,
                Agent.status == "active",
                ~Agent.agent_id.startswith("system:"),
                Agent.agent_id.in_(agent_ids),
            )
        )
    )
    if set(agent_ids) != allowed:
        raise ValueError("A selected agent is unavailable.")


async def owned_document(
    session: AsyncSession, kind: str, ref: str, owner: str, *, lock: bool = False
) -> ArtifactRecordRow | DeliverableRow:
    """Resolve owner-only controls without granting project readers mutation rights."""
    from datetime import UTC, datetime

    model = DeliverableRow if kind == "deliverable" else ArtifactRecordRow
    key = DeliverableRow.deliverable_id if kind == "deliverable" else ArtifactRecordRow.artifact_id
    query = sa.select(model).where(
        key == ref, model.owner_email == owner, model.status != "deleted"
    )
    row = cast(ArtifactRecordRow | DeliverableRow | None, await session.scalar(query))
    if row is None:
        raise LookupError("Document not found.")
    if lock:
        from cognis.store.document_locks import lock_document_lineages

        await lock_document_lineages(session, model, [row.lineage_id or ref])
        row = cast(
            ArtifactRecordRow | DeliverableRow | None,
            await session.scalar(query.with_for_update().execution_options(populate_existing=True)),
        )
        if row is None:
            raise LookupError("Document not found.")
    if isinstance(row, ArtifactRecordRow) and (
        row.deleted_at
        or row.purpose == "conversation_deliverable"
        or (row.expires_at and row.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC))
    ):
        raise LookupError("Document not found.")
    return row


async def document_access(
    session: AsyncSession, row: ArtifactRecordRow | DeliverableRow, owner: str
) -> DocumentAccess:
    """Describe selectable agents plus persisted inherited access on this revision."""
    ref = row.deliverable_id if isinstance(row, DeliverableRow) else row.artifact_id
    grants: dict[str, set[str]] = {}
    for recipient, source in (
        await session.execute(
            sa.select(ArtifactGrantRow.agent_id, ArtifactGrantRow.source).where(
                ArtifactGrantRow.owner_email == owner, ArtifactGrantRow.content_ref == ref
            )
        )
    ).all():
        grants.setdefault(recipient, set()).add(source)
    agents = (
        await session.scalars(
            sa.select(Agent)
            .where(
                Agent.owner_email == owner,
                Agent.status == "active",
                ~Agent.agent_id.startswith("system:"),
            )
            .order_by(Agent.name, Agent.agent_id)
        )
    ).all()
    project_agents = (
        set(
            await session.scalars(
                sa.select(ProjectAgentRow.agent_id).where(
                    ProjectAgentRow.project_id == row.project_id
                )
            )
        )
        if row.project_id
        else set()
    )
    return DocumentAccess(
        agents=[
            AgentAccess(
                agent_id=a.agent_id,
                name=a.display_name or a.name,
                avatar_url=f"/api/v1/images/{a.avatar_image_id}"
                if a.avatar_image_id
                else a.avatar_url,
                explicit="explicit" in grants.get(a.agent_id, set()),
                inherited=bool(grants.get(a.agent_id, set()) - {"explicit"})
                or a.agent_id == row.owner_agent_id
                or a.agent_id in project_agents,
            )
            for a in agents
        ],
        project_id=row.project_id,
        owner_agent_id=row.owner_agent_id,
    )


async def replace_explicit_shares(
    session: AsyncSession, row: ArtifactRecordRow | DeliverableRow, owner: str, agent_ids: list[str]
) -> DocumentAccess:
    """Apply explicit access to existing revisions; future revisions inherit it."""
    await validate_recipients(session, owner, agent_ids)
    model = type(row)
    key = (
        DeliverableRow.deliverable_id
        if isinstance(row, DeliverableRow)
        else ArtifactRecordRow.artifact_id
    )
    refs = list(
        await session.scalars(
            sa.select(key).where(
                model.owner_email == owner,
                model.lineage_id == row.lineage_id,
                model.status != "deleted",
            )
        )
    )
    await session.execute(
        sa.delete(ArtifactGrantRow).where(
            ArtifactGrantRow.owner_email == owner,
            ArtifactGrantRow.content_ref.in_(refs),
            ArtifactGrantRow.source == "explicit",
        )
    )
    session.add_all(
        [
            ArtifactGrantRow(
                owner_email=owner, content_ref=ref, agent_id=recipient, source="explicit"
            )
            for ref in refs
            for recipient in set(agent_ids)
        ]
    )
    await session.flush()
    return await document_access(session, row, owner)
