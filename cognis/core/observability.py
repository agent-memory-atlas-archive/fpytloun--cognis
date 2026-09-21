"""Application-side observability v2 snapshot service.

The service owns only aggregate, read-only application state.  Database and
executor reads happen on the refresh loop; Prometheus collection only reads an
immutable in-memory snapshot.
"""

from __future__ import annotations

import asyncio
import contextvars
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from time import monotonic
from typing import Any, Protocol

from prometheus_client import REGISTRY, Counter, Gauge, Histogram
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric

from cognis.store.coordination import DatabaseLeaseStore, Lease
from cognis.store.observability import (
    ObservabilitySnapshot,
    collect_observability_snapshot,
)

OBSERVABILITY_LEASE_KEY = "cognis:observability:v2"
OBSERVABILITY_REFRESH_SECONDS = 30.0
OBSERVABILITY_LEASE_TTL_SECONDS = 90.0
OBSERVABILITY_MAX_SNAPSHOT_AGE_SECONDS = 60.0
ATTRIBUTED_CARDINALITY_LIMIT = 5000

OBSERVABILITY_REFRESH_TOTAL = Counter(
    "cognis_observability_refresh_total",
    "Application observability refresh outcomes.",
    ("outcome",),
)
OBSERVABILITY_REFRESH_DURATION = Histogram(
    "cognis_observability_refresh_duration_seconds",
    "Application observability refresh duration.",
)
OBSERVABILITY_INVENTORY_OWNER = Gauge(
    "cognis_observability_inventory_owner",
    "Whether this controller owns the inventory refresh lease.",
)
OBSERVABILITY_SNAPSHOT_TIMESTAMP = Gauge(
    "cognis_observability_snapshot_timestamp_seconds",
    "Unix timestamp of the last successfully published inventory snapshot.",
)
OBSERVABILITY_CARDINALITY_LIMITED = Counter(
    "cognis_observability_cardinality_limited_events_total",
    "Metric families or tuples rejected at a cardinality limit.",
    ("family",),
)
OBSERVABILITY_CARDINALITY_OMITTED = Counter(
    "cognis_observability_cardinality_omitted_total",
    "Metric families omitted because a cardinality limit was reached.",
    ("family",),
)
OBSERVABILITY_CARDINALITY_LIMITED_CURRENT = Gauge(
    "cognis_observability_cardinality_limited",
    "Whether the current inventory snapshot omitted a metric family for cardinality.",
    ("family",),
)
OBSERVABILITY_ERRORS = Counter(
    "cognis_observability_errors_total",
    "Application observability refresh and collection errors.",
    ("stage",),
)
OBSERVABILITY_LABEL_ERRORS = Counter(
    "cognis_observability_label_errors_total",
    "Metric details omitted because a bounded label was invalid.",
    ("family", "label"),
)


def _metric_inc(metric: Any, *, amount: float = 1, **labels: str) -> None:
    try:
        (metric.labels(**labels) if labels else metric).inc(amount)
    except Exception:
        return


def _metric_set(metric: Any, value: float, **labels: str) -> None:
    try:
        (metric.labels(**labels) if labels else metric).set(value)
    except Exception:
        return


def _metric_observe(metric: Any, value: float, **labels: str) -> None:
    try:
        (metric.labels(**labels) if labels else metric).observe(value)
    except Exception:
        return


_SAFE_LABEL = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,95}$")
_UUID_LABEL = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _safe_slug(value: Any, *, fallback: str = "unknown") -> str:
    candidate = str(value).strip().lower() if value is not None else ""
    return (
        candidate
        if _SAFE_LABEL.fullmatch(candidate) and not _UUID_LABEL.fullmatch(candidate)
        else fallback
    )


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


@dataclass(frozen=True, slots=True)
class Attribution:
    user: str
    agent: str
    provider: str
    model: str
    profile: str
    origin: str
    status: str


_ATTRIBUTION: contextvars.ContextVar[Attribution | None] = contextvars.ContextVar(
    "cognis_observability_attribution", default=None
)


def set_attribution(value: Attribution | None) -> contextvars.Token[Attribution | None]:
    return _ATTRIBUTION.set(value)


def reset_attribution(token: contextvars.Token[Attribution | None]) -> None:
    _ATTRIBUTION.reset(token)


def current_attribution() -> Attribution | None:
    return _ATTRIBUTION.get()


class BoundedAttributedCounterCollector:
    """Thread-safe fixed-cardinality counter collector."""

    def __init__(self, name: str, documentation: str) -> None:
        self.name = name
        self.documentation = documentation
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = RLock()

    def record(self, labels: Mapping[str, str]) -> None:
        try:
            key = tuple(labels[label] for label in ATTRIBUTED_LABELS)
        except (KeyError, TypeError):
            return
        with self._lock:
            if key not in self._values and len(self._values) >= ATTRIBUTED_CARDINALITY_LIMIT:
                _metric_inc(OBSERVABILITY_CARDINALITY_LIMITED, family=self.name)
                _metric_inc(OBSERVABILITY_CARDINALITY_OMITTED, family=self.name)
                return
            self._values[key] = self._values.get(key, 0.0) + 1.0

    def collect(self) -> Iterator[Metric]:
        family = CounterMetricFamily(
            self.name,
            self.documentation,
            labels=ATTRIBUTED_LABELS,
        )
        with self._lock:
            values = tuple(self._values.items())
        for key, value in values:
            family.add_metric(list(key), value)
        yield family


ATTRIBUTED_LABELS = (
    "user",
    "agent",
    "provider",
    "model",
    "profile",
    "origin",
    "status",
)
TURN_ATTRIBUTED = BoundedAttributedCounterCollector(
    "cognis_turns_attributed_total",
    "Chat turns attributed to a canonical user, agent, and model lifecycle.",
)
LLM_REQUEST_ATTRIBUTED = BoundedAttributedCounterCollector(
    "cognis_llm_requests_attributed_total",
    "LLM requests attributed to a canonical lifecycle.",
)


def _attributed_labels(
    value: Attribution | None,
    *,
    provider_id: str | None = None,
    model: str | None = None,
    status: str | None = None,
) -> dict[str, str] | None:
    if value is None:
        return None
    user = value.user.strip().lower()
    if not re.fullmatch(r"[^@\s]{1,128}@[^\s@]{1,255}", user):
        return None
    return {
        "user": user,
        "agent": _safe_slug(value.agent),
        "provider": _safe_slug(provider_id if provider_id is not None else value.provider),
        "model": _safe_slug(model if model is not None else value.model),
        "profile": _safe_slug(value.profile, fallback="unknown"),
        "origin": _safe_slug(value.origin, fallback="unknown"),
        "status": _safe_slug(status if status is not None else value.status, fallback="unknown"),
    }


def record_attributed_turn(*, status: str | None = None) -> None:
    labels = _attributed_labels(current_attribution(), status=status)
    if labels is not None:
        TURN_ATTRIBUTED.record(labels)


def record_attributed_llm_request(
    *,
    status: str | None = None,
    provider_id: str | None = None,
    model: str | None = None,
) -> None:
    labels = _attributed_labels(
        current_attribution(),
        provider_id=provider_id,
        model=model,
        status=status,
    )
    if labels is not None:
        LLM_REQUEST_ATTRIBUTED.record(labels)


class LSPProvider(Protocol):
    async def get_lsp_statuses(self, *, owner_email: str | None = None) -> list[Any]: ...


@dataclass(frozen=True, slots=True)
class LSPObservation:
    user: str
    executor: str
    executor_type: str
    state: str
    servers: int
    files: int
    diagnostics: tuple[tuple[str, int], ...]
    spawns_pending: int
    snapshot_timestamp: float


@dataclass(frozen=True, slots=True)
class ObservabilityState:
    snapshot: ObservabilitySnapshot | None = None
    lsp: tuple[LSPObservation, ...] = ()
    refreshed_at: float = 0.0
    owner: bool = False


class ObservabilityCollector:
    """Custom collector that never performs I/O during scrape."""

    def __init__(self, service: ObservabilityService) -> None:
        self._service = service

    def collect(self) -> Iterator[Metric]:
        state = self._service.state
        age = monotonic() - state.refreshed_at if state.refreshed_at else float("inf")
        if (
            state.snapshot is None
            or not state.owner
            or age > OBSERVABILITY_MAX_SNAPSHOT_AGE_SECONDS
        ):
            return
        try:
            yield from _snapshot_families(state.snapshot)
            yield from _lsp_families(state.lsp)
        except Exception:
            _metric_inc(OBSERVABILITY_ERRORS, stage="collection")
            return


def _family(
    name: str,
    documentation: str,
    labels: tuple[str, ...],
    rows: list[tuple[Mapping[str, str], float]],
) -> GaugeMetricFamily:
    result = GaugeMetricFamily(name, documentation, labels=labels)
    for label_values, value in rows:
        result.add_metric([label_values[label] for label in labels], value)
    return result


def _snapshot_families(snapshot: ObservabilitySnapshot) -> list[Metric]:
    families: list[Metric] = []
    for name, documentation, labels, rows in snapshot.metric_rows:
        families.append(_family(name, documentation, labels, list(rows)))
    return families


def _lsp_families(rows: tuple[LSPObservation, ...]) -> list[Metric]:
    families: list[Metric] = [
        _family(
            "cognis_lsp_state",
            "Safe executor-level LSP state.",
            ("user", "executor", "executor_type", "state"),
            [
                (
                    {
                        "user": row.user,
                        "executor": row.executor,
                        "executor_type": row.executor_type,
                        "state": row.state,
                    },
                    1.0,
                )
                for row in rows
            ],
        ),
        _family(
            "cognis_lsp_servers_active",
            "Active LSP servers by executor.",
            ("user", "executor", "executor_type"),
            [
                (
                    {
                        "user": row.user,
                        "executor": row.executor,
                        "executor_type": row.executor_type,
                    },
                    row.servers,
                )
                for row in rows
            ],
        ),
        _family(
            "cognis_lsp_files_tracked",
            "LSP-tracked files by executor.",
            ("user", "executor", "executor_type"),
            [
                (
                    {
                        "user": row.user,
                        "executor": row.executor,
                        "executor_type": row.executor_type,
                    },
                    row.files,
                )
                for row in rows
            ],
        ),
        _family(
            "cognis_lsp_diagnostics",
            "LSP diagnostics by severity and executor.",
            ("user", "executor", "executor_type", "severity"),
            [
                (
                    {
                        "user": row.user,
                        "executor": row.executor,
                        "executor_type": row.executor_type,
                        "severity": severity,
                    },
                    count,
                )
                for row in rows
                for severity, count in row.diagnostics
            ],
        ),
        _family(
            "cognis_lsp_spawns_pending",
            "Pending LSP server spawns by executor.",
            ("user", "executor", "executor_type"),
            [
                (
                    {
                        "user": row.user,
                        "executor": row.executor,
                        "executor_type": row.executor_type,
                    },
                    row.spawns_pending,
                )
                for row in rows
            ],
        ),
        _family(
            "cognis_lsp_snapshot_timestamp_seconds",
            "Wall-clock time at which executor LSP state was collected.",
            ("user", "executor", "executor_type"),
            [
                (
                    {
                        "user": row.user,
                        "executor": row.executor,
                        "executor_type": row.executor_type,
                    },
                    row.snapshot_timestamp,
                )
                for row in rows
            ],
        ),
    ]
    return families


class ObservabilityService:
    """Serialized lease owner, refresher, and snapshot collector."""

    def __init__(
        self,
        session_factory: Any,
        *,
        owner_id: str,
        lsp_provider: LSPProvider | None = None,
        refresh_seconds: float = OBSERVABILITY_REFRESH_SECONDS,
        lease_ttl_seconds: float = OBSERVABILITY_LEASE_TTL_SECONDS,
        max_family_cardinality: int = 1000,
        registry: Any = REGISTRY,
    ) -> None:
        self._session_factory = session_factory
        self._owner_id = owner_id
        self._lsp_provider = lsp_provider
        self._refresh_seconds = refresh_seconds
        self._lease_ttl_seconds = lease_ttl_seconds
        self._max_family_cardinality = max_family_cardinality
        self._registry = registry
        self._lease_store = DatabaseLeaseStore(session_factory)
        self._lease: Lease | None = None
        self._state = ObservabilityState()
        self._task: asyncio.Task[None] | None = None
        self._collector = ObservabilityCollector(self)
        self._registered: list[Any] = []
        self._limited_families: set[str] = set()
        self._refresh_lock = asyncio.Lock()

    @property
    def state(self) -> ObservabilityState:
        return self._state

    @property
    def collector(self) -> ObservabilityCollector:
        return self._collector

    async def start(self) -> None:
        if not self._registered:
            for collector in (self._collector, TURN_ATTRIBUTED, LLM_REQUEST_ATTRIBUTED):
                try:
                    self._registry.register(collector)
                except Exception:
                    _metric_inc(OBSERVABILITY_ERRORS, stage="registration")
                else:
                    self._registered.append(collector)
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="cognis-observability-refresh")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self._lease is not None:
            try:
                await self._lease_store.release(self._lease)
            except Exception:
                _metric_inc(OBSERVABILITY_ERRORS, stage="release")
            self._lease = None
        _metric_set(OBSERVABILITY_INVENTORY_OWNER, 0)
        self._state = ObservabilityState()
        for collector in self._registered:
            try:
                self._registry.unregister(collector)
            except Exception:
                _metric_inc(OBSERVABILITY_ERRORS, stage="unregistration")
        self._registered.clear()

    async def refresh_once(self) -> bool:
        async with self._refresh_lock:
            return await self._refresh_once()

    async def _refresh_once(self) -> bool:
        started = monotonic()
        lease_deadline = started + min(self._lease_ttl_seconds / 3.0, 10.0)
        lease = self._lease
        try:
            if lease is None:
                if monotonic() >= lease_deadline:
                    raise TimeoutError
                lease = await asyncio.wait_for(
                    self._lease_store.acquire(
                        OBSERVABILITY_LEASE_KEY,
                        self._owner_id,
                        ttl_seconds=self._lease_ttl_seconds,
                    ),
                    timeout=max(0.0, lease_deadline - monotonic()),
                )
            else:
                if monotonic() >= lease_deadline:
                    raise TimeoutError
                lease = await asyncio.wait_for(
                    self._lease_store.renew(lease, ttl_seconds=self._lease_ttl_seconds),
                    timeout=max(0.0, lease_deadline - monotonic()),
                )
        except Exception:
            self._clear_ownership()
            _metric_inc(OBSERVABILITY_ERRORS, stage="lease")
            return False
        if lease is None:
            self._clear_ownership()
            _metric_inc(OBSERVABILITY_REFRESH_TOTAL, outcome="not_owner")
            return False
        self._lease = lease
        _metric_set(OBSERVABILITY_INVENTORY_OWNER, 1)
        try:
            async with self._session_factory() as session:
                snapshot = await collect_observability_snapshot(
                    session,
                    max_family_cardinality=self._max_family_cardinality,
                )
            lsp = await self._collect_lsp(snapshot)
            pre_renew = monotonic()
            renew_deadline = pre_renew + min(self._lease_ttl_seconds / 3.0, 10.0)
            if pre_renew >= renew_deadline:
                raise TimeoutError
            renewed = await asyncio.wait_for(
                self._lease_store.renew(lease, ttl_seconds=self._lease_ttl_seconds),
                timeout=max(0.0, renew_deadline - monotonic()),
            )
            if (
                renewed is None
                or renewed.resource_key != lease.resource_key
                or renewed.owner_id != lease.owner_id
                or renewed.fencing_token != lease.fencing_token
            ):
                self._clear_ownership()
                _metric_inc(OBSERVABILITY_ERRORS, stage="lease")
                _metric_inc(OBSERVABILITY_REFRESH_TOTAL, outcome="not_owner")
                return False
            self._lease = renewed
            refreshed_at = monotonic()
            self._state = ObservabilityState(
                snapshot=snapshot,
                lsp=tuple(lsp),
                refreshed_at=refreshed_at,
                owner=True,
            )
            for family, omitted in snapshot.cardinality_omitted:
                _metric_inc(OBSERVABILITY_CARDINALITY_LIMITED, family=family)
                _metric_inc(
                    OBSERVABILITY_CARDINALITY_OMITTED,
                    amount=omitted,
                    family=family,
                )
            current_limited = {family for family, _omitted in snapshot.cardinality_omitted}
            for family in self._limited_families - current_limited:
                _metric_set(OBSERVABILITY_CARDINALITY_LIMITED_CURRENT, 0, family=family)
            for family in current_limited:
                _metric_set(OBSERVABILITY_CARDINALITY_LIMITED_CURRENT, 1, family=family)
            self._limited_families = current_limited
            _metric_set(OBSERVABILITY_SNAPSHOT_TIMESTAMP, snapshot.collected_at.timestamp())
            _metric_inc(OBSERVABILITY_REFRESH_TOTAL, outcome="success")
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            self._clear_ownership()
            _metric_inc(OBSERVABILITY_ERRORS, stage="refresh")
            _metric_inc(OBSERVABILITY_REFRESH_TOTAL, outcome="error")
            return False
        finally:
            _metric_observe(OBSERVABILITY_REFRESH_DURATION, monotonic() - started)

    def _clear_ownership(self) -> None:
        self._lease = None
        self._state = ObservabilityState()
        for family in self._limited_families:
            _metric_set(OBSERVABILITY_CARDINALITY_LIMITED_CURRENT, 0, family=family)
        self._limited_families.clear()
        _metric_set(OBSERVABILITY_INVENTORY_OWNER, 0)

    async def _collect_lsp(
        self, snapshot: ObservabilitySnapshot | None = None
    ) -> list[LSPObservation]:
        if self._lsp_provider is None:
            return []
        try:
            reports = await asyncio.wait_for(self._lsp_provider.get_lsp_statuses(), timeout=5.0)
        except TimeoutError:
            _metric_inc(OBSERVABILITY_ERRORS, stage="lsp")
            return []
        except Exception:
            _metric_inc(OBSERVABILITY_ERRORS, stage="lsp")
            return []
        observations: list[LSPObservation] = []
        seen: set[tuple[str, str]] = set()
        max_observations = self._max_family_cardinality // 2
        observed_at = datetime.now(UTC).timestamp()
        for report in reports:
            try:
                executor_type = _safe_slug(
                    getattr(report, "executor_type", None),
                    fallback="unknown",
                )
                snapshot = snapshot or self.state.snapshot
                configured = (
                    snapshot.executor_slugs.get(str(getattr(report, "executor_id", "")), "")
                    if snapshot is not None
                    else ""
                )
                if not isinstance(configured, tuple) or len(configured) != 2 or configured in seen:
                    _metric_inc(OBSERVABILITY_LABEL_ERRORS, family="lsp", label="executor")
                    continue
                configured_slug, owner = configured
                seen.add(configured)
                if len(observations) >= max_observations:
                    _metric_inc(OBSERVABILITY_CARDINALITY_LIMITED, family="lsp")
                    _metric_inc(OBSERVABILITY_CARDINALITY_OMITTED, family="lsp")
                    continue
                totals = getattr(report, "totals", None)
                observations.append(
                    LSPObservation(
                        user=owner,
                        executor=configured_slug,
                        executor_type=executor_type,
                        state=_safe_slug(getattr(report, "state", None)),
                        servers=_nonnegative_int(getattr(totals, "active_server_count", 0)),
                        files=_nonnegative_int(getattr(totals, "files_tracked", 0)),
                        diagnostics=(
                            ("error", _nonnegative_int(getattr(totals, "total_errors", 0))),
                            ("warning", _nonnegative_int(getattr(totals, "total_warnings", 0))),
                        ),
                        spawns_pending=_nonnegative_int(getattr(report, "spawning_count", 0)),
                        snapshot_timestamp=observed_at,
                    )
                )
            except Exception:
                _metric_inc(OBSERVABILITY_ERRORS, stage="lsp")
        return observations

    async def _run(self) -> None:
        while True:
            await self.refresh_once()
            await asyncio.sleep(self._refresh_seconds)


__all__ = [
    "Attribution",
    "ATTRIBUTED_CARDINALITY_LIMIT",
    "BoundedAttributedCounterCollector",
    "LLM_REQUEST_ATTRIBUTED",
    "ObservabilityCollector",
    "ObservabilityService",
    "TURN_ATTRIBUTED",
    "current_attribution",
    "record_attributed_llm_request",
    "record_attributed_turn",
    "reset_attribution",
    "set_attribution",
]
