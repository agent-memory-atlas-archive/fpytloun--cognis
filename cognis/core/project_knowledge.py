"""Authoritative project/KB sharing rules used by transport adapters."""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from cognis.core.project_access import resolve_project_role_by_id
from cognis.models.knowledgebase import KnowledgebaseModel
from cognis.store.models import KnowledgebaseRow, ProjectKnowledgebaseRow
from cognis.store.queries import get_user, lock_resource_share_transition


def project_knowledgebase_metadata(row: KnowledgebaseRow, actor_email: str) -> KnowledgebaseModel:
    """Shared metadata projection for project REST and native discovery."""
    return KnowledgebaseModel(
        knowledgebase_id=row.knowledgebase_id,
        owner_email=row.owner_email,
        access_level="owner" if row.owner_email == actor_email else "shared",
        name=row.name,
        description=row.description,
        status=row.status,
        metadata_schema=row.metadata_schema or {},
        settings=row.settings or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


async def set_project_knowledgebase(
    session: AsyncSession,
    *,
    project_id: str,
    knowledgebase_id: str,
    actor_email: str,
    assigned: bool,
) -> None:
    """Attach an owned KB as project manager; either owner may revoke access."""
    user = await get_user(session, actor_email)
    if user is None or not user.is_active or user.role == "viewer":
        raise PermissionError("User may not manage project knowledgebase assignments")
    await lock_resource_share_transition(session, resource_type="project", resource_id=project_id)
    project, role = await resolve_project_role_by_id(session, project_id, actor_email)
    kb = await session.get(KnowledgebaseRow, knowledgebase_id)
    if project is None or kb is None or kb.status == "deleted":
        raise ValueError("Project or knowledgebase not found")
    manager = role.role in ("owner", "manager")
    owner = kb.owner_email == actor_email
    if assigned and (
        not manager or not owner or project.status != "active" or kb.status != "active"
    ):
        raise PermissionError(
            "Assigning requires knowledgebase ownership and project manager access"
        )
    if not assigned and not (manager or owner):
        raise PermissionError("Removing requires knowledgebase ownership or project manager access")
    existing = await session.get(ProjectKnowledgebaseRow, (project_id, knowledgebase_id))
    if assigned and existing is None:
        session.add(
            ProjectKnowledgebaseRow(
                project_id=project_id, knowledgebase_id=knowledgebase_id, assigned_by=actor_email
            )
        )
    elif not assigned:
        await session.execute(
            delete(ProjectKnowledgebaseRow).where(
                ProjectKnowledgebaseRow.project_id == project_id,
                ProjectKnowledgebaseRow.knowledgebase_id == knowledgebase_id,
            )
        )
    await session.flush()
