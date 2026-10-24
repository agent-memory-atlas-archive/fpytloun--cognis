"""Common lock order for revision creation and lineage-wide explicit grants."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_document_lineages(session: AsyncSession, model: Any, lineage_ids: list[str]) -> None:
    """Lock immutable root rows before revision rows, until the caller commits."""
    key = model.deliverable_id if hasattr(model, "deliverable_id") else model.artifact_id
    if lineage_ids:
        await session.execute(
            sa.select(key).where(key.in_(sorted(set(lineage_ids)))).order_by(key).with_for_update()
        )
