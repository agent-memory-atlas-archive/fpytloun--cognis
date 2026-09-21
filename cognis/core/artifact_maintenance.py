"""Periodic maintenance for uploaded artifacts."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa

from cognis.core.maintenance_lease import run_periodic_maintenance
from cognis.logging import get_logger
from cognis.store.coordination import DatabaseLeaseStore
from cognis.store.models import ArtifactRecordRow, TtsCacheRow
from cognis.store.queries import (
    claim_artifact_cleanup,
    delete_artifact_record,
    get_setting_value,
    list_expired_temporary_artifacts,
    list_orphaned_attached_artifacts,
)

logger = get_logger(__name__)


_DEFAULT_TTS_TTL_DAYS = 30


class ArtifactMaintenanceService:
    """Background cleanup for temporary and orphaned artifacts."""

    def __init__(
        self,
        *,
        session_factory: Any,
        artifact_store: Any,
        interval_seconds: int = 300,
        lease_store: DatabaseLeaseStore | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._artifact_store = artifact_store
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._lease_store = lease_store

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="artifact-maintenance")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def run_once(self) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            expired = await list_expired_temporary_artifacts(session, now=now)
            orphaned = await list_orphaned_attached_artifacts(session)
            for row in [*expired, *orphaned]:
                await claim_artifact_cleanup(session, row, now=now)

            # Tombstone physical generations; cache entries remain readable only
            # while their artifact is live. New syntheses use new object IDs.
            ttl_days = await _resolve_tts_ttl_days(session)
            tts_cutoff = now - timedelta(days=ttl_days)
            tts_ids = list(
                (
                    await session.scalars(
                        sa.select(TtsCacheRow.artifact_id)
                        .where(TtsCacheRow.created_at < tts_cutoff)
                        .limit(200)
                    )
                ).all()
            )
            if tts_ids:
                await session.execute(
                    sa.update(ArtifactRecordRow)
                    .where(
                        ArtifactRecordRow.artifact_id.in_(tts_ids),
                        ArtifactRecordRow.namespace == "tts",
                    )
                    .values(status="deleted", deleted_at=now, updated_at=now)
                )
            # A replaced cache entry can leave its old immutable generation.
            # Retire such objects after the same TTL, without another sweeper.
            orphan_tts = (
                sa.select(ArtifactRecordRow.artifact_id)
                .where(
                    ArtifactRecordRow.namespace == "tts",
                    ArtifactRecordRow.status != "deleted",
                    ArtifactRecordRow.updated_at < tts_cutoff,
                    ~sa.exists(
                        sa.select(TtsCacheRow.artifact_id).where(
                            TtsCacheRow.artifact_id == ArtifactRecordRow.artifact_id
                        )
                    ),
                )
                .limit(200)
            )
            await session.execute(
                sa.update(ArtifactRecordRow)
                .where(ArtifactRecordRow.artifact_id.in_(orphan_tts))
                .values(status="deleted", deleted_at=now, updated_at=now)
                .execution_options(synchronize_session=False)
            )
            await session.commit()
            pending = list(
                (
                    await session.scalars(
                        sa.select(ArtifactRecordRow)
                        .where(ArtifactRecordRow.status == "deleted")
                        .order_by(ArtifactRecordRow.updated_at)
                        .limit(600)
                    )
                ).all()
            )
        deleted = 0
        for row in pending:
            try:
                await self._artifact_store.async_delete_object(row.namespace, row.object_id)
            except Exception:
                logger.warning(
                    "Artifact storage cleanup failed",
                    extra={"artifact_id": row.artifact_id},
                    exc_info=True,
                )
                continue
            async with self._session_factory() as session:
                await session.execute(
                    sa.delete(TtsCacheRow).where(TtsCacheRow.artifact_id == row.artifact_id)
                )
                await delete_artifact_record(session, row.artifact_id)
                await session.commit()
            deleted += 1
        if deleted:
            logger.info(
                "artifact maintenance completed",
                extra={
                    "extra_data": {
                        "expired_deleted": len(expired),
                        "orphan_candidates": len(orphaned),
                        "deleted": deleted,
                    }
                },
            )

    async def _run_loop(self) -> None:
        await run_periodic_maintenance(
            self.run_once,
            stop=self._stop,
            interval_seconds=self._interval_seconds,
            resource_key="maintenance:artifacts",
            lease_store=self._lease_store,
        )


async def _resolve_tts_ttl_days(session: Any) -> int:
    """Read ``tts.cache_ttl_days`` setting with sane defaults."""
    raw = await get_setting_value(session, "tts.cache_ttl_days", _DEFAULT_TTS_TTL_DAYS)
    try:
        if raw is None:
            days = _DEFAULT_TTS_TTL_DAYS
        elif isinstance(raw, (str, int)):
            days = int(raw)
        else:
            return _DEFAULT_TTS_TTL_DAYS
    except (TypeError, ValueError):
        return _DEFAULT_TTS_TTL_DAYS
    return max(1, days)
