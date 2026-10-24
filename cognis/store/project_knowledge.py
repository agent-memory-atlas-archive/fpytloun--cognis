"""Project knowledgebase assignments confer read/query access, never writes."""

from __future__ import annotations

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cognis.store.models import (
    KnowledgebaseRow,
    ProjectGrantRow,
    ProjectKnowledgebaseRow,
    ProjectRow,
)


def readable_project_knowledge_ids(user_email: str) -> Select[tuple[str]]:
    """Select KB IDs whose active project is currently readable by the user."""
    grants = select(ProjectGrantRow.project_id).where(
        ProjectGrantRow.grantee_type == "user",
        ProjectGrantRow.grantee_user_email == user_email,
        ProjectGrantRow.permission.in_(("viewer", "member", "manager", "use")),
        ProjectGrantRow.revoked_at.is_(None),
    )
    return (
        select(ProjectKnowledgebaseRow.knowledgebase_id)
        .join(ProjectRow, ProjectRow.project_id == ProjectKnowledgebaseRow.project_id)
        .where(
            ProjectRow.status == "active",
            or_(ProjectRow.owner_email == user_email, ProjectRow.project_id.in_(grants)),
        )
    )


async def list_project_knowledgebases(
    session: AsyncSession, *, user_email: str, project_id: str | None = None
) -> list[KnowledgebaseRow]:
    """List active project assignments visible to the user."""
    ids = readable_project_knowledge_ids(user_email)
    if project_id:
        ids = ids.where(ProjectKnowledgebaseRow.project_id == project_id)
    return list(
        (
            await session.scalars(
                select(KnowledgebaseRow)
                .where(
                    KnowledgebaseRow.knowledgebase_id.in_(ids), KnowledgebaseRow.status != "deleted"
                )
                .order_by(KnowledgebaseRow.name, KnowledgebaseRow.knowledgebase_id)
            )
        ).all()
    )
