"""Shared project management operations for REST and native tools.

Grant transitions and inbox entries commit together under the resource share
lock. Post-commit publication is only a hint; retries never duplicate a grant or
notification. Avatar sources remain private; projects receive their own snapshot.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognis.core.artifact_access import artifact_authorized_for_conversation
from cognis.core.deliverable_media import _image_dimensions
from cognis.core.inbox import stage_share_notification
from cognis.core.project_access import normalize_project_role, resolve_project_role, role_satisfies
from cognis.store.models import User
from cognis.store.project_queries import list_active_project_grants, update_project_grant_permission
from cognis.store.queries import (
    create_project_grant,
    get_active_project_grant,
    get_artifact_record,
    get_project,
    get_project_grant,
    get_user,
    list_project_grants,
    lock_resource_share_transition,
    revoke_project_grant,
)


class ProjectManagementError(ValueError):
    """A safe, transport-independent project operation error."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status
        self.code = {
            403: "forbidden",
            404: "not_found",
            409: "conflict",
        }.get(status, "validation_error")


async def require_project(session: AsyncSession, project_id: str, actor: str, required: str) -> Any:
    """Resolve project access without an admin bypass."""
    project = await get_project(session, project_id)
    role = (await resolve_project_role(session, project, actor)).role
    if role is None:
        raise ProjectManagementError("Project not found", 404)
    if not role_satisfies(role, required):
        raise ProjectManagementError("Project permission is insufficient", 403)
    if required in {"manage", "share"}:
        user = await get_user(session, actor)
        if user is None or not user.is_active or user.role == "viewer":
            raise ProjectManagementError("User may not manage projects", 403)
    return project


class ProjectManagementService:
    """Own project sharing, source validation, and recipient discovery."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        inbox_service: Any | None = None,
        artifact_store: Any | None = None,
        workflow_registry: Any | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.inbox_service = inbox_service
        self.artifact_store = artifact_store
        self.workflow_registry = workflow_registry

    async def list_grants(self, project_id: str, actor: str) -> list[Any]:
        """Owners see grant history; other readers see active membership."""
        async with self.session_factory() as session:
            project = await require_project(session, project_id, actor, "view")
            return (
                await list_project_grants(session, project_id)
                if project.owner_email == actor
                else await list_active_project_grants(session, project_id)
            )

    async def leave(
        self, project_id: str, actor: str, *, make_private: bool = False
    ) -> dict[str, Any]:
        """Leave a shared project atomically, optionally privatizing authored work."""
        from cognis.store.project_queries import (
            make_author_project_resources_private,
            revoke_active_project_grants_for_user,
        )

        async with self.session_factory() as session:
            await lock_resource_share_transition(
                session, resource_type="project", resource_id=project_id
            )
            project = await require_project(session, project_id, actor, "view")
            if project.owner_email == actor:
                raise ProjectManagementError("The project owner cannot leave the project", 409)
            made_private = (
                await make_author_project_resources_private(session, project_id, actor)
                if make_private
                else 0
            )
            revoked = await revoke_active_project_grants_for_user(session, project_id, actor)
            await session.commit()
        return {"ok": revoked > 0, "made_private": made_private}

    async def find_recipients(
        self, project_id: str, actor: str, query: str
    ) -> list[dict[str, Any]]:
        """Return bounded active recipient identities, not an admin directory."""
        query = query.strip()
        if not 3 <= len(query) <= 254:
            raise ProjectManagementError("Recipient query must contain 3..254 characters")
        async with self.session_factory() as session:
            await require_project(session, project_id, actor, "share")
            rows = (
                await session.execute(
                    select(User.email, User.name)
                    .where(
                        User.is_active.is_(True),
                        User.role != "system",
                        User.email != actor,
                        or_(
                            func.lower(User.email) == query.lower(),
                            func.lower(User.name).contains(query.lower(), autoescape=True),
                        ),
                    )
                    .order_by(User.email)
                    .limit(20)
                )
            ).all()
        return [{"email": row.email, "name": row.name} for row in rows]

    async def change_grant(
        self,
        project_id: str,
        actor: str,
        *,
        grantee_email: str | None = None,
        grant_id: str | None = None,
        permission: str | None = None,
        note: str | None = None,
        revoke: bool = False,
        conflict_on_existing: bool = False,
    ) -> Any:
        """Create, update, or revoke sharing with retry-safe notifications."""
        role = normalize_project_role(permission)
        if not revoke and role not in {"viewer", "member", "manager"}:
            raise ProjectManagementError("Permission must be viewer, member, or manager")
        notice = None
        change: Literal["shared", "updated", "revoked"] | None
        async with self.session_factory() as session:
            if not await lock_resource_share_transition(
                session, resource_type="project", resource_id=project_id
            ):
                raise ProjectManagementError("Project not found", 404)
            project = await require_project(session, project_id, actor, "share")
            if grant_id is not None:
                grant = await get_project_grant(session, grant_id)
                if grant is None or grant.project_id != project_id:
                    raise ProjectManagementError("Project grant not found", 404)
                if revoke:
                    change = "revoked" if grant.revoked_at is None else None
                    if change:
                        await revoke_project_grant(session, grant_id)
                else:
                    if grant.revoked_at is not None:
                        raise ProjectManagementError("Project grant not found", 404)
                    change = "updated" if normalize_project_role(grant.permission) != role else None
                    if change:
                        await update_project_grant_permission(session, grant_id, str(role))
            else:
                email = (grantee_email or "").strip().lower()
                user = await get_user(session, email)
                if user is None or not user.is_active or user.role == "system":
                    raise ProjectManagementError("Share recipient is unavailable")
                if email == project.owner_email:
                    raise ProjectManagementError("The project owner already has access")
                grant = await get_active_project_grant(session, project_id, email)
                if grant is not None:
                    if conflict_on_existing:
                        raise ProjectManagementError("User already has access to this project", 409)
                    if normalize_project_role(grant.permission) != role:
                        raise ProjectManagementError(
                            "Recipient already has access; update the existing grant explicitly",
                            409,
                        )
                    change = None
                else:
                    grant = await create_project_grant(
                        session,
                        project_id=project_id,
                        granted_by=actor,
                        grantee_user_email=email,
                        permission=str(role),
                        note=note,
                    )
                    change = "shared"
            if change:
                notice = stage_share_notification(
                    session,
                    recipient=grant.grantee_user_email,
                    actor=actor,
                    resource_type="project",
                    resource_id=project_id,
                    resource_name=project.name,
                    change=change,
                )
            await session.commit()
            await session.refresh(grant)
        if self.inbox_service is not None:
            await self.inbox_service.publish(notice)
        return grant

    async def require_workflow(self, workflow_id: str, project_id: str | None, actor: str) -> None:
        """Use the same workflow ownership rule for every project transport."""
        if self.workflow_registry is None:
            raise ProjectManagementError("Workflow registry is unavailable")
        workflow = await self.workflow_registry.get(
            workflow_id, owner_email=actor, project_id=project_id
        )
        if workflow is None or (
            not getattr(workflow, "is_system", False)
            and getattr(workflow, "owner_email", None) != actor
        ):
            raise ProjectManagementError("Workflow not found", 404)

    async def avatar_snapshot(
        self,
        content_ref: str,
        *,
        actor: str,
        project_owner: str,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Validate authorized image bytes and create a project-owned snapshot."""
        store = self.artifact_store
        if store is None:
            raise ProjectManagementError("Artifact store is unavailable")
        async with self.session_factory() as session:
            row = await get_artifact_record(session, content_ref)
            if runtime_metadata is not None:
                allowed = await artifact_authorized_for_conversation(
                    session,
                    artifact=row,
                    owner_email=actor,
                    conversation_id=runtime_metadata.get("conversation_id"),
                    agent_id=runtime_metadata.get("agent_id"),
                    session_id=runtime_metadata.get("session_id"),
                )
            else:
                allowed = (
                    row is not None
                    and row.owner_email == actor
                    and row.status != "deleted"
                    and row.deleted_at is None
                    and (
                        row.expires_at is None
                        or row.expires_at.replace(tzinfo=row.expires_at.tzinfo or UTC)
                        > datetime.now(UTC)
                    )
                )
            if row is not None:
                if not allowed:
                    raise ProjectManagementError("Image not found", 404)
                location = (row.namespace, row.object_id, row.filename)
            else:
                location = None
        if location is None:
            # Existing uploaded/generated REST avatars predate artifact records.
            # Tools may not use this owner-only path to bypass agent content scope.
            if runtime_metadata is not None:
                raise ProjectManagementError("Image not found", 404)
            for namespace in ("avatars", "images"):
                meta = await store.async_load_metadata(namespace, content_ref, "image")
                if meta is not None and meta.owner_email == actor:
                    location = (namespace, content_ref, "image")
                    break
            if location is None:
                raise ProjectManagementError("Image not found", 404)
        try:
            content, mime_type = await store.async_load(*location)
        except FileNotFoundError as exc:
            raise ProjectManagementError("Image not found", 404) from exc
        if not 0 < len(content) <= 20 * 1024 * 1024 or mime_type not in (
            "image/png",
            "image/jpeg",
            "image/webp",
        ):
            raise ProjectManagementError("Avatar must be a PNG, JPEG, or WebP image up to 20 MB")
        dimensions = await asyncio.to_thread(_image_dimensions, content, mime_type)
        if dimensions is None or dimensions[0] * dimensions[1] > 16_777_216:
            raise ProjectManagementError("Avatar image is invalid or exceeds the pixel limit")
        image_id = store.generate_id("img")
        await store.async_save(
            "avatars", image_id, "image", content, mime_type, owner_email=project_owner
        )
        return str(image_id)
