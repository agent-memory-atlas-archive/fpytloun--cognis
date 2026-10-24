"""Retry-safe native project sharing on SQLite and PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import schema as sa_schema
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.requests import Request

from cognis.api.authentication import AuthenticatedUser
from cognis.api.routes.projects import assign_project_knowledgebase, unassign_project_knowledgebase
from cognis.core.project_management import ProjectManagementService
from cognis.store.database import create_session_factory
from cognis.store.models import Base, InboxNotificationRow, ProjectGrantRow, ProjectKnowledgebaseRow
from cognis.store.queries import create_knowledgebase, create_project, create_user
from cognis.tools.builtin.projects import build_project_tool_handlers
from cognis.tools.registry import ToolExecutionContext


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.asyncio
async def test_concurrent_native_sharing_emits_one_transition(tmp_path: Path, backend: str) -> None:
    schema_name = f"cognis_project_sharing_{uuid.uuid4().hex}"
    admin_engine = None
    if backend == "postgres":
        url = os.environ.get("COGNIS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("COGNIS_TEST_POSTGRES_URL is not configured")
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        admin_engine = create_async_engine(url)
        async with admin_engine.begin() as connection:
            await connection.execute(sa_schema.CreateSchema(schema_name))
        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": f'"{schema_name}"'}}
        )
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sharing.db")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            await create_user(
                session, email="owner@example.com", name="Owner", password_hash="test"
            )
            await create_user(
                session, email="recipient@example.com", name="Recipient", password_hash="test"
            )
            await create_project(
                session, project_id="proj_shared", owner_email="owner@example.com", name="Home"
            )
            await session.commit()
        service = ProjectManagementService(factory)
        grants = await asyncio.gather(
            *[
                service.change_grant(
                    "proj_shared",
                    "owner@example.com",
                    grantee_email="recipient@example.com",
                    permission="member",
                )
                for _ in range(2)
            ]
        )
        assert grants[0].grant_id == grants[1].grant_id
        for operation in ("update", "revoke"):
            await asyncio.gather(
                *[
                    service.change_grant(
                        "proj_shared",
                        "owner@example.com",
                        grant_id=grants[0].grant_id,
                        permission="viewer",
                        revoke=operation == "revoke",
                    )
                    for _ in range(2)
                ]
            )
        async with factory() as session:
            notifications = (await session.scalars(select(InboxNotificationRow))).all()
            persisted = (await session.scalars(select(ProjectGrantRow))).all()
        assert len(persisted) == 1 and persisted[0].revoked_at is not None
        assert {row.kind for row in notifications} == {
            "sharing.project.shared",
            "sharing.project.updated",
            "sharing.project.revoked",
        }
        assert len(notifications) == 3
        async with factory() as session:
            kb = await create_knowledgebase(session, owner_email="owner@example.com", name="Egypt")
            await session.commit()
            kb_id = kb.knowledgebase_id
        handlers = build_project_tool_handlers(factory)
        context = ToolExecutionContext(
            executor_handle=None,  # type: ignore[arg-type]
            runtime_metadata={"user_email": "owner@example.com"},
        )
        args = {"project_id": "proj_shared", "knowledgebase_id": kb_id}
        for assigned, name in (
            (True, "assign_knowledgebase_to_project"),
            (False, "unassign_knowledgebase_from_project"),
        ):
            results = await asyncio.gather(*[handlers[name](args, context) for _ in range(2)])
            assert results == [{**args, "assigned": assigned}] * 2
            async with factory() as session:
                assignments = (await session.scalars(select(ProjectKnowledgebaseRow))).all()
                assert len(assignments) == (1 if assigned else 0)
        request = Request(
            {
                "type": "http",
                "app": SimpleNamespace(state=SimpleNamespace(session_factory=factory)),
                "state": {"user": AuthenticatedUser(email="owner@example.com", role="user")},
            }
        )
        for assigned, native, rest in (
            (True, "assign_knowledgebase_to_project", assign_project_knowledgebase),
            (False, "unassign_knowledgebase_from_project", unassign_project_knowledgebase),
        ):
            await asyncio.gather(
                handlers[native](args, context),
                rest(request, "proj_shared", kb_id),
            )
            async with factory() as session:
                assignments = (await session.scalars(select(ProjectKnowledgebaseRow))).all()
                assert len(assignments) == (1 if assigned else 0)
        # Opposing operations allow either serial ordering, never duplicates,
        # uniqueness conflicts, or partial transactions.
        await asyncio.gather(
            handlers["assign_knowledgebase_to_project"](args, context),
            unassign_project_knowledgebase(request, "proj_shared", kb_id),
        )
        async with factory() as session:
            assignments = (await session.scalars(select(ProjectKnowledgebaseRow))).all()
            assert len(assignments) in (0, 1)
        await asyncio.gather(
            handlers["unassign_knowledgebase_from_project"](args, context),
            assign_project_knowledgebase(request, "proj_shared", kb_id),
        )
        async with factory() as session:
            assignments = (await session.scalars(select(ProjectKnowledgebaseRow))).all()
            assert len(assignments) in (0, 1)
    finally:
        await engine.dispose()
        if admin_engine is not None:
            async with admin_engine.begin() as connection:
                await connection.execute(sa_schema.DropSchema(schema_name, cascade=True))
            await admin_engine.dispose()
