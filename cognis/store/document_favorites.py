"""Personal document bookmarks with idempotent writes and lineage identity."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cognis.store.models import DocumentFavorite


def favorite_expression(user_email: str, kind: str, lineage_id: Any) -> Any:
    """Correlate personal state only after the caller has applied content access."""
    return sa.exists().where(
        DocumentFavorite.user_email == user_email,
        DocumentFavorite.kind == kind,
        DocumentFavorite.lineage_id == lineage_id,
    )


async def set_favorite(
    session: AsyncSession, user_email: str, kind: str, lineage_id: str, favorite: bool
) -> None:
    """Set, rather than toggle, state so concurrent retries cannot duplicate bookmarks."""
    if favorite:
        insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
        await session.execute(
            insert(DocumentFavorite)
            .values(user_email=user_email, kind=kind, lineage_id=lineage_id)
            .on_conflict_do_nothing()
        )
    else:
        await session.execute(
            sa.delete(DocumentFavorite).where(
                DocumentFavorite.user_email == user_email,
                DocumentFavorite.kind == kind,
                DocumentFavorite.lineage_id == lineage_id,
            )
        )
    await session.flush()
