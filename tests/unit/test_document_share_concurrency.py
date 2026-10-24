"""Real PostgreSQL locking evidence for grants spanning immutable revisions."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cognis.artifacts.store import ArtifactStore, ArtifactStoreConfig
from cognis.core.document_sharing import owned_document, replace_explicit_shares
from cognis.store.models import ArtifactGrantRow, Base
from cognis.store.queries import (
    create_agent,
    create_artifact_record,
    create_conversation,
    create_deliverable,
    create_user,
    lock_artifact_revision_target,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("COGNIS_TEST_POSTGRES_URL"), reason="requires disposable PostgreSQL"
)


@pytest.mark.parametrize("kind", ["artifact", "deliverable"])
@pytest.mark.parametrize("first", ["writer", "revoker"])
async def test_old_revision_revocation_serializes_with_new_revision(tmp_path, kind, first):
    url = os.environ["COGNIS_TEST_POSTGRES_URL"].replace("postgresql://", "postgresql+asyncpg://")
    schema = "authoring_race_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = ArtifactStore(ArtifactStoreConfig(path=str(tmp_path / "payloads")))
    owner = "authoring-race@cognis.test"

    async def write(session, previous=None):
        if kind == "deliverable":
            row = await create_deliverable(
                session,
                conversation_id="race-conversation",
                content="# Revision",
                published_owner_email=owner,
                supersedes_deliverable_id=previous,
                artifact_store=store,
            )
            row.status = "delivered"
            return row
        lineage = await lock_artifact_revision_target(session, previous) if previous else None
        return await create_artifact_record(
            session,
            artifact_id="art_" + uuid.uuid4().hex,
            namespace="artifacts",
            object_id=uuid.uuid4().hex,
            filename="race.txt",
            owner_email=owner,
            owner_agent_id="race-agent",
            purpose="artifact_write",
            kind="file",
            mime_type="text/plain",
            size_bytes=0,
            status="attached",
            lineage_id=lineage.lineage_id if lineage else None,
            revision=lineage.revision if lineage else 1,
            supersedes_artifact_id=previous,
        )

    def ref(row):
        return row.artifact_id if kind == "artifact" else row.deliverable_id

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            await create_user(session, owner, name="Race owner", password_hash="test-password-hash")
            await create_agent(
                session, agent_id="race-agent", owner_email=owner, name="Race", status="active"
            )
            await create_conversation(
                session,
                conversation_id="race-conversation",
                user_email=owner,
                agent_id="race-agent",
                context_type="web",
            )
            root = await write(session)
            head = await write(session, ref(root))
            await replace_explicit_shares(session, head, owner, ["race-agent"])
            await session.commit()

        async def revoke():
            async with factory() as session:
                old = await owned_document(session, kind, ref(root), owner, lock=True)
                await replace_explicit_shares(session, old, owner, [])
                await session.commit()

        async def revise():
            async with factory() as session:
                row = await write(session, ref(head))
                await session.commit()
                return ref(row)

        async with factory() as holding:
            if first == "writer":
                await write(holding, ref(head))
                blocked = asyncio.create_task(revoke())
            else:
                old = await owned_document(holding, kind, ref(root), owner, lock=True)
                await replace_explicit_shares(holding, old, owner, [])
                blocked = asyncio.create_task(revise())
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(blocked), timeout=0.15)
            await holding.commit()
            await asyncio.wait_for(blocked, timeout=10)
        async with factory() as session:
            explicit = list(
                await session.scalars(
                    sa.select(ArtifactGrantRow).where(
                        ArtifactGrantRow.owner_email == owner, ArtifactGrantRow.source == "explicit"
                    )
                )
            )
            assert explicit == []
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
