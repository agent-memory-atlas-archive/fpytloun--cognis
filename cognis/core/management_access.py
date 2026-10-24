"""Trusted actor and concurrency contracts for system management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cognis.api.common import api_exception
from cognis.ownership import SYSTEM_USER_EMAIL


@dataclass(frozen=True)
class ManagementActor:
    """An authenticated principal, never constructed from tool arguments."""

    email: str
    role: str

    def require_admin(self) -> None:
        """Enforce system-resource authorization."""
        if self.role != "admin":
            raise api_exception(403, "forbidden", "Admin access required")

    def require_mutation(self) -> None:
        """Viewer identities cannot mutate configuration."""
        if self.role == "viewer":
            raise api_exception(403, "forbidden", "Viewer accounts are read-only")

    def require_owner(self, owner: str | None) -> None:
        """Administrators manage shared resources, not another user's resources."""
        self.require_mutation()
        if not owner or owner == SYSTEM_USER_EMAIL:
            self.require_admin()
        elif owner != self.email:
            raise api_exception(404, "not_found", "Resource not found")


def updated_at_matches(current: datetime | None, expected: str | None) -> bool:
    if current is None or expected is None:
        return current is None and expected is None
    try:
        parsed = datetime.fromisoformat(expected)
    except ValueError:
        return False
    # Pydantic uses Z for UTC, datetime.isoformat uses +00:00, and SQLite
    # returns UTC without tzinfo. Compare instants, never their spellings.
    return current.replace(tzinfo=current.tzinfo or UTC) == parsed.replace(
        tzinfo=parsed.tzinfo or UTC
    )


def check_updated_at(row: Any, expected: str | None) -> None:
    """Check a caller precondition while holding the resource's write guard."""
    if expected is not None and not updated_at_matches(row.updated_at, expected):
        raise api_exception(409, "configuration_conflict", "Configuration changed; read it again")
