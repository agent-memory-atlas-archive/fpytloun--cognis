from __future__ import annotations

import importlib
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cognis.core.artifact_access import artifact_authorized_for_conversation
from cognis.store.artifact_access_schema import ensure_artifact_access_schema
from cognis.store.models import Agent, ArtifactGrantRow, ArtifactRecordRow, Base, User
from cognis.store.queries import create_artifact_record, create_conversation, create_session


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize("upgrade_path", ["bootstrap", "alembic"])
async def test_legacy_agent_ownership_upgrade(tmp_path, backend, upgrade_path):
    url = os.environ.get("COGNIS_TEST_POSTGRES_URL")
    if backend == "postgres" and not url:
        pytest.skip("requires disposable COGNIS_TEST_POSTGRES_URL")
    schema = f"artifact_access_{uuid.uuid4().hex}"
    admin = None
    if backend == "postgres":
        admin = create_async_engine(url)
        async with admin.begin() as connection:
            await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/migration.db")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        owner = "owner@example.com"
        async with factory() as db:
            db.add(User(email=owner, name="Owner"))
            await db.flush()
            db.add_all(
                [
                    Agent(agent_id="owner-agent", owner_email=owner, name="Owner"),
                    Agent(agent_id="reader-agent", owner_email=owner, name="Reader"),
                ]
            )
            await db.flush()
            await create_conversation(
                db, owner, "reader-agent", "agent_direct", conversation_id="reader"
            )
            parent = await create_session(db, "reader", owner, "reader-agent")
            await create_conversation(
                db, owner, "owner-agent", "agent_direct", conversation_id="source"
            )
            source = await create_session(
                db, "source", owner, "owner-agent", parent_session_id=parent.session_id
            )
            artifact = await create_artifact_record(
                db,
                artifact_id=f"art_{uuid.uuid4().hex}",
                namespace="artifacts",
                object_id=uuid.uuid4().hex,
                filename="report.txt",
                owner_email=owner,
                conversation_id="source",
                session_id=source.session_id,
                purpose="artifact_publish",
                kind="file",
                mime_type="text/plain",
                size_bytes=1,
                status="attached",
            )
            ref = artifact.artifact_id
            await db.execute(
                sa.insert(ArtifactRecordRow),
                [
                    dict(
                        artifact_id=f"bulk_{index}",
                        namespace="artifacts",
                        object_id=f"bulk_{index}",
                        filename="report.txt",
                        owner_email=owner,
                        conversation_id="source",
                        session_id=source.session_id,
                        purpose="artifact_publish",
                        kind="file",
                        mime_type="text/plain",
                        size_bytes=1,
                        status="attached",
                    )
                    for index in range(250)
                ],
            )
            await db.commit()
        async with engine.begin() as connection:
            # Reconstruct the pre-157 ownership schema while retaining real source data.
            await connection.execute(sa.text("DROP TABLE artifact_grants"))
            for table in ("artifacts", "deliverables"):
                await connection.execute(sa.text(f"DROP INDEX ix_{table}_agent_owner"))
                await connection.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN owner_agent_id"))
            await connection.execute(sa.text("ALTER TABLE deliverables DROP COLUMN owner_email"))
            await connection.execute(sa.text("ALTER TABLE sessions DROP COLUMN artifact_scope_id"))

            def upgrade(sync):
                operations = Operations(MigrationContext.configure(sync))
                keys = [
                    fk
                    for fk in sa.inspect(sync).get_foreign_keys("deliverables")
                    if fk["constrained_columns"]
                    in (["conversation_id"], ["session_id"], ["step_run_id"])
                ]
                with operations.batch_alter_table(
                    "deliverables",
                    naming_convention={
                        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
                    },
                ) as batch:
                    for fk in keys:
                        name = (
                            fk["name"]
                            or f"fk_deliverables_{fk['constrained_columns'][0]}_{fk['referred_table']}"
                        )
                        batch.drop_constraint(name, type_="foreignkey")
                        batch.create_foreign_key(
                            name,
                            fk["referred_table"],
                            fk["constrained_columns"],
                            fk["referred_columns"],
                            ondelete="CASCADE",
                        )
                if upgrade_path == "bootstrap":
                    ensure_artifact_access_schema(sync)
                else:
                    module = importlib.import_module(
                        "cognis.store.migrations.versions.157_artifact_agent_access"
                    )
                    with Operations.context(MigrationContext.configure(sync)):
                        module.upgrade()
                ensure_artifact_access_schema(sync)
                keys = sa.inspect(sync).get_foreign_keys("deliverables")
                assert all(
                    fk["options"].get("ondelete") == "SET NULL"
                    for fk in keys
                    if fk["constrained_columns"]
                    in (["conversation_id"], ["session_id"], ["step_run_id"])
                )

            statements = []

            def capture(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            sa.event.listen(engine.sync_engine, "before_cursor_execute", capture)
            try:
                await connection.run_sync(upgrade)
            finally:
                sa.event.remove(engine.sync_engine, "before_cursor_execute", capture)
            assert not any("WITH RECURSIVE content_managed_lineage" in sql for sql in statements)
            assert sum("INSERT INTO artifact_grants" in sql for sql in statements) < 20
        async with factory() as db:
            artifact = await db.get(ArtifactRecordRow, ref)
            assert artifact.owner_agent_id == "owner-agent"
            assert await artifact_authorized_for_conversation(
                db,
                artifact=artifact,
                owner_email=owner,
                conversation_id="source",
                agent_id="owner-agent",
                session_id=source.session_id,
            )
            assert not await artifact_authorized_for_conversation(
                db,
                artifact=artifact,
                owner_email="other@example.com",
                conversation_id="source",
                agent_id="owner-agent",
            )
            grants = set(
                (
                    await db.execute(
                        sa.select(ArtifactGrantRow.content_ref, ArtifactGrantRow.agent_id).where(
                            ArtifactGrantRow.source == "output"
                        )
                    )
                ).tuples()
            )
            for content_ref in [ref, *(f"bulk_{index}" for index in range(250))]:
                assert (content_ref, "owner-agent") in grants
                assert (content_ref, "reader-agent") in grants
                assert (content_ref, f"scope:{parent.session_id}") in grants
                assert (content_ref, f"scope:{source.session_id}") in grants
    finally:
        await engine.dispose()
        if admin is not None:
            async with admin.begin() as connection:
                await connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()
