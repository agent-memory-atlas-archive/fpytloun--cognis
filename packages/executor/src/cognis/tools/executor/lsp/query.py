"""Per-server outcome types for explicit LSP queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class QueryStatus(StrEnum):
    """Outcome of one LSP request against one server."""

    OK = "ok"
    """Server supports the method and returned at least one item."""

    EMPTY = "empty"
    """Server supports the method and returned no items."""

    UNSUPPORTED = "unsupported"
    """Server did not negotiate the method (statically or dynamically)."""

    TIMEOUT = "timeout"
    """Server did not answer within the query timeout."""

    FAILED = "failed"
    """Server returned a JSON-RPC error, died, or the client raised."""

    PARTIAL = "partial"
    """A bounded traversal stopped before completion (limit, time, restart)."""


@dataclass(slots=True)
class QueryOutcome:
    """Result of one query method on one language server."""

    server_id: str
    status: QueryStatus
    items: list[Any] = field(default_factory=list)
    duration_ms: int = 0
    message: str | None = None
    """Bounded, code-free explanation for non-OK statuses."""

    @property
    def is_ok(self) -> bool:
        return self.status in (QueryStatus.OK, QueryStatus.EMPTY, QueryStatus.PARTIAL)


def aggregate_status(outcomes: list[QueryOutcome]) -> QueryStatus:
    """Collapse per-server outcomes into one status for reporting.

    Any result wins over no result.  Without results, the most informative
    failure state is reported: partial, then unsupported, then timeout, then
    failed.  ``EMPTY`` means every capable server answered with nothing.
    """
    if not outcomes:
        return QueryStatus.UNSUPPORTED
    statuses = {outcome.status for outcome in outcomes}
    has_items = any(outcome.items for outcome in outcomes)
    if has_items:
        if QueryStatus.PARTIAL in statuses or statuses & {
            QueryStatus.TIMEOUT,
            QueryStatus.FAILED,
        }:
            return QueryStatus.PARTIAL
        return QueryStatus.OK
    if QueryStatus.PARTIAL in statuses:
        return QueryStatus.PARTIAL
    if QueryStatus.EMPTY in statuses:
        return QueryStatus.EMPTY
    if statuses == {QueryStatus.UNSUPPORTED}:
        return QueryStatus.UNSUPPORTED
    if QueryStatus.TIMEOUT in statuses:
        return QueryStatus.TIMEOUT
    return QueryStatus.FAILED
