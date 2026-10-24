"""Fail-open, fixed-cardinality timings across durable turn admission."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal, get_args

from prometheus_client import Histogram

logger = logging.getLogger(__name__)
Phase = Literal[
    "request_prepare",
    "submit_to_admission",
    "admission_to_receipt",
    "submit_total",
    "first_claim_wait",
    "claim_notification",
]
_PHASES = frozenset(get_args(Phase))
LATENCY = Histogram(
    "cognis_turn_admission_phase_seconds",
    "Turn admission/claim phase latency; first_claim_wait includes intentional queuing.",
    ["phase", "outcome"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 300),
)


def observe(phase: Phase, seconds: float, outcome: str = "success") -> None:
    """Record durations only, never content or unbounded identifiers."""
    try:
        if phase not in _PHASES or outcome not in {"success", "error", "cancelled"}:
            return
        LATENCY.labels(phase=phase, outcome=outcome).observe(max(0.0, seconds))
    except Exception:
        logger.debug("Failed to record turn phase latency", exc_info=True)


def observe_first_claim(
    created_at: datetime, claimed_at: datetime | None, attempt_count: int
) -> None:
    """Measure the first queue wait using persisted UTC clocks on either SQL backend."""
    try:
        if attempt_count != 1 or claimed_at is None:
            return
        # SQLite may return naive persisted UTC values while the fresh claim
        # retains an aware database timestamp. Metrics must never break dispatch.
        created = created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at
        claimed = claimed_at.replace(tzinfo=UTC) if claimed_at.tzinfo is None else claimed_at
        observe("first_claim_wait", (claimed - created).total_seconds())
    except Exception:
        logger.debug("Failed to measure first claim wait", exc_info=True)


@contextmanager
def measure(phase: Phase) -> Iterator[None]:
    """Measure an awaited phase without changing its cancellation/error behavior."""
    started = perf_counter()
    outcome = "success"
    try:
        yield
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except BaseException:
        outcome = "error"
        raise
    finally:
        observe(phase, perf_counter() - started, outcome)
