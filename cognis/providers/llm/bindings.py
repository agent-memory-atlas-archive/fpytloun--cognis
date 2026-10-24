"""Durable LLM-session bindings; DB transactions never encompass provider I/O."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognis.providers.llm.recovery_policy import RouteTarget
from cognis.store.coordination import database_now, database_now_expression
from cognis.store.models import InferenceBinding


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


@dataclass(frozen=True, slots=True)
class BindingSnapshot:
    """Committed target and current reservation, never live ORM state."""

    key: str
    revision: int
    target: RouteTarget | None
    pending: RouteTarget | None
    claim_token: str | None
    claim_until: datetime | None
    observed_at: datetime

    @property
    def reserved(self) -> bool:
        return self.claim_until is not None and self.claim_until > self.observed_at


class InferenceBindings:
    """Atomic binding reservations shared by every controller replica."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    def key(owner: str, session_identity: str, reference: str) -> str:
        """Scope external affinity inputs without exposing them in storage keys."""
        return hashlib.sha256(
            json.dumps([owner, session_identity, reference], separators=(",", ":")).encode()
        ).hexdigest()

    async def get_or_create(
        self, *, owner: str, session_identity: str, reference: str
    ) -> BindingSnapshot:
        """Return the existing session binding or race-safe empty generation."""
        key = self.key(owner, session_identity, reference)
        async with self._sessions() as session:
            observed = (
                await session.execute(
                    select(InferenceBinding, database_now_expression(session)).where(
                        InferenceBinding.binding_key == key
                    )
                )
            ).one_or_none()
            if observed is not None:
                now = _utc(observed[1])
                if _utc(observed[0].expires_at) < now + timedelta(days=15):
                    await session.execute(
                        update(InferenceBinding)
                        .where(InferenceBinding.binding_key == key)
                        .values(expires_at=now + timedelta(days=30))
                    )
                    await session.commit()
                return self._snapshot(observed[0], _utc(observed[1]))
            # Opportunistic bounded retention on new sessions only. Existing
            # sessions renew at most twice a month, not on every inference call.
            now = await database_now(session)
            expired = (
                select(InferenceBinding.binding_key)
                .where(
                    InferenceBinding.expires_at <= now,
                    or_(
                        InferenceBinding.claim_until.is_(None), InferenceBinding.claim_until <= now
                    ),
                )
                .limit(100)
            )
            await session.execute(
                delete(InferenceBinding).where(InferenceBinding.binding_key.in_(expired))
            )
            row = InferenceBinding(
                binding_key=key,
                owner_email=owner,
                reference=reference,
                revision=0,
                expires_at=await database_now(session) + timedelta(days=30),
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.get(InferenceBinding, key)
                if existing is None:
                    raise
                row = existing
            return self._snapshot(row, await database_now(session))

    async def read(self, key: str) -> BindingSnapshot:
        """Read authoritative selection before dispatch or replacement."""
        async with self._sessions() as session:
            observed = (
                await session.execute(
                    select(InferenceBinding, database_now_expression(session)).where(
                        InferenceBinding.binding_key == key
                    )
                )
            ).one_or_none()
            if observed is None:
                raise RuntimeError("Inference binding no longer exists")
            return self._snapshot(observed[0], _utc(observed[1]))

    async def reserve(
        self, snapshot: BindingSnapshot, target: RouteTarget, *, lease_seconds: float
    ) -> BindingSnapshot | None:
        """Reserve one replacement before dispatch; a CAS loser must reread."""
        token = uuid.uuid4().hex
        async with self._sessions() as session:
            now = await database_now(session)
            result = await session.execute(
                update(InferenceBinding)
                .where(
                    InferenceBinding.binding_key == snapshot.key,
                    InferenceBinding.revision == snapshot.revision,
                    or_(
                        InferenceBinding.claim_token.is_(None),
                        InferenceBinding.claim_until <= now,
                    ),
                )
                .values(
                    revision=snapshot.revision + 1,
                    pending_target=target.model_dump(),
                    claim_token=token,
                    claim_until=now + timedelta(seconds=lease_seconds),
                    expires_at=now + timedelta(days=30),
                )
            )
            await session.commit()
            if cast(CursorResult[Any], result).rowcount != 1:
                return None
        return BindingSnapshot(
            snapshot.key,
            snapshot.revision + 1,
            snapshot.target,
            target,
            token,
            now + timedelta(seconds=lease_seconds),
            now,
        )

    async def commit(self, claim: BindingSnapshot) -> bool:
        """Promote at output commitment; interrupted output still owns affinity."""
        if claim.pending is None or not claim.claim_token:
            raise ValueError("A binding reservation is required")
        async with self._sessions() as session:
            result = await session.execute(
                update(InferenceBinding)
                .where(
                    InferenceBinding.binding_key == claim.key,
                    InferenceBinding.revision == claim.revision,
                    InferenceBinding.claim_token == claim.claim_token,
                    InferenceBinding.claim_until > database_now_expression(session),
                )
                .values(
                    target=claim.pending.model_dump(),
                    pending_target=None,
                    claim_token=None,
                    claim_until=None,
                )
            )
            await session.commit()
            return cast(CursorResult[Any], result).rowcount == 1

    async def release(self, claim: BindingSnapshot) -> None:
        """Release only the matching reservation; never undo a committed target."""
        if not claim.claim_token:
            return
        async with self._sessions() as session:
            await session.execute(
                update(InferenceBinding)
                .where(
                    InferenceBinding.binding_key == claim.key,
                    InferenceBinding.revision == claim.revision,
                    InferenceBinding.claim_token == claim.claim_token,
                )
                .values(pending_target=None, claim_token=None, claim_until=None)
            )
            await session.commit()

    @staticmethod
    def _snapshot(row: InferenceBinding, observed_at: datetime) -> BindingSnapshot:
        return BindingSnapshot(
            row.binding_key,
            row.revision,
            RouteTarget.model_validate(row.target) if row.target else None,
            RouteTarget.model_validate(row.pending_target) if row.pending_target else None,
            row.claim_token,
            _utc(row.claim_until) if row.claim_until else None,
            observed_at,
        )
