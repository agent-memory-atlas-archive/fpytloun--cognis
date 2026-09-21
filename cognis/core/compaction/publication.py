"""Ownership guard for publishing a compaction.

A compaction publishes twice: a ``compaction_summary`` event into the source
Intaris session and a session rotation in the database. Both must be gated by
the owner's leases so a controller that lost its direct-turn fence (or lost the
per-session compaction lease) cannot publish a second compaction after another
controller already did. ``_auto_compact`` installs the guard in a contextvar so
the compaction strategy can re-check ownership immediately before the Intaris
append without threading the leases through every summariser signature.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass


class CompactionOwnershipLost(RuntimeError):
    """Raised when a compaction owner lost its lease before publication."""


def compaction_lease_key(session_id: str) -> str:
    return f"compaction:session:{session_id}"


@dataclass(frozen=True)
class CompactionPublicationGuard:
    """Ownership evidence for one compaction attempt.

    ``token`` is folded into the Intaris idempotency key so retries by the same
    owner converge while a different owner can never replay the same key.
    ``check`` raises :class:`CompactionOwnershipLost` when either lease is gone.
    """

    token: str
    check: Callable[[], Awaitable[None]]


compaction_publication_guard: ContextVar[CompactionPublicationGuard | None] = ContextVar(
    "compaction_publication_guard", default=None
)
