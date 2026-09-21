from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from cognis.core.artifact_maintenance import ArtifactMaintenanceService
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import Base
from cognis.store.queries import (
    claim_artifact_cleanup,
    create_artifact_record,
    get_artifact_record,
    mark_artifacts_attached,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("attach_first", [True, False])
async def test_attachment_and_cleanup_have_only_one_winner(tmp_path, attach_first):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/claim.db")
    async with engine.begin() as db:
        await db.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    now = datetime.now(UTC)
    try:
        async with factory() as db:
            candidate = await create_artifact_record(
                db,
                artifact_id="art-cleanup",
                namespace="uploads",
                object_id="art-cleanup",
                filename="file.txt",
                owner_email=None,
                purpose="attachment",
                kind="file",
                mime_type="text/plain",
                size_bytes=10,
                expires_at=now - timedelta(seconds=1),
            )
            await db.commit()

        async def attach():
            async with factory() as db:
                count = await mark_artifacts_attached(
                    db,
                    ["art-cleanup"],
                    conversation_id="conversation-1",
                    session_id="session-1",
                    message_role="user",
                )
                await db.commit()
                return count

        async def cleanup():
            async with factory() as db:
                claimed = await claim_artifact_cleanup(db, candidate, now=now)
                await db.commit()
                return claimed

        if attach_first:
            assert await attach() == 1
            assert not await cleanup()
        else:
            assert await cleanup()
            assert await attach() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_storage_failure_preserves_tombstone_for_retry_without_transaction(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/retry.db")
    async with engine.begin() as db:
        await db.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as db:
            await create_artifact_record(
                db,
                artifact_id="art-retry",
                namespace="uploads",
                object_id="art-retry",
                filename="file.txt",
                owner_email=None,
                purpose="attachment",
                kind="file",
                mime_type="text/plain",
                size_bytes=10,
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
            await db.commit()
        calls = 0

        async def delete(namespace, object_id):
            nonlocal calls
            calls += 1
            # A second connection sees the committed tombstone during storage I/O.
            async with factory() as db:
                row = await get_artifact_record(db, object_id)
                assert row is not None and row.status == "deleted"
            if calls == 1:
                raise OSError("storage offline")

        store = AsyncMock()
        store.async_delete_object.side_effect = delete
        service = ArtifactMaintenanceService(session_factory=factory, artifact_store=store)
        await service.run_once()
        await service.run_once()
        assert calls == 2
        async with factory() as db:
            assert await get_artifact_record(db, "art-retry") is None
    finally:
        await engine.dispose()
