"""Application observability v2 contract tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from time import monotonic
from types import SimpleNamespace
from typing import Any

import pytest
from prometheus_client import CollectorRegistry, generate_latest
from sqlalchemy.ext.asyncio import async_sessionmaker

from cognis.api.middleware import PUBLIC_ROUTES
from cognis.core.observability import (
    OBSERVABILITY_MAX_SNAPSHOT_AGE_SECONDS,
    Attribution,
    BoundedAttributedCounterCollector,
    ObservabilityCollector,
    ObservabilityService,
    ObservabilityState,
    _lsp_families,
    current_attribution,
    record_attributed_llm_request,
    record_attributed_turn,
    reset_attribution,
    set_attribution,
)
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import (
    Agent,
    Base,
    ChannelAccountRow,
    ChannelDeliveryOutboxRow,
    Conversation,
    DirectTurnRequestRow,
    ExecutorRow,
    Session,
    StepRun,
    Task,
    User,
)
from cognis.store.observability import (
    collect_observability_snapshot,
    normalize_inherited,
    normalize_profile,
    normalize_slug,
)


@pytest.fixture
async def observability_db(tmp_path: Any) -> Any:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/observability.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        session.add_all(
            [
                User(email="alice@cognis.local", is_active=True),
                User(email="bob@cognis.local", is_active=False),
            ]
        )
        await session.commit()
        session.add(
            Agent(
                agent_id="agent-primary",
                owner_email="alice@cognis.local",
                name="Primary Agent",
                status="active",
            )
        )
        await session.commit()
        session.add_all(
            [
                Conversation(
                    conversation_id="conversation-open",
                    user_email="alice@cognis.local",
                    agent_id="agent-primary",
                    context_type="chat",
                    status="active",
                ),
                Conversation(
                    conversation_id="conversation-closed",
                    user_email="alice@cognis.local",
                    agent_id="agent-primary",
                    context_type="chat",
                    status="closed",
                ),
                Session(
                    session_id="session-running",
                    conversation_id="conversation-open",
                    user_email="alice@cognis.local",
                    agent_id="agent-primary",
                    status="active",
                    model_override_provider_id="openai",
                    model_override="gpt-5",
                    delegation_mode="direct",
                ),
                Session(
                    session_id="session-completed",
                    conversation_id="conversation-closed",
                    user_email="alice@cognis.local",
                    agent_id="agent-primary",
                    status="completed",
                ),
            ]
        )
        await session.commit()
        session.add_all(
            [
                DirectTurnRequestRow(
                    request_id="request-queued",
                    turn_id="turn-queued",
                    conversation_id="conversation-open",
                    agent_id="agent-primary",
                    user_id="alice@cognis.local",
                    idempotency_scope="scope-queued",
                    idempotency_key="key-queued",
                    admission_hash="hash-queued",
                    payload_hash="payload-queued",
                    payload={"content": "redacted"},
                    status="queued",
                ),
                DirectTurnRequestRow(
                    request_id="request-running",
                    turn_id="turn-running",
                    conversation_id="conversation-open",
                    agent_id="agent-primary",
                    user_id="alice@cognis.local",
                    idempotency_scope="scope-running",
                    idempotency_key="key-running",
                    admission_hash="hash-running",
                    payload_hash="payload-running",
                    payload={"content": "redacted"},
                    status="running",
                ),
            ]
        )
        await session.commit()
        session.add_all(
            [
                Task(
                    task_id="task-running",
                    title="Runtime task",
                    created_by="alice@cognis.local",
                    agent_id="agent-primary",
                    status="running",
                ),
            ]
        )
        await session.commit()
        session.add_all(
            [
                StepRun(
                    step_run_id="step-running",
                    task_id="task-running",
                    step_name="execute",
                    step_type="direct",
                    agent_id="agent-primary",
                    status="running",
                ),
                StepRun(
                    step_run_id="step-approved",
                    task_id="task-running",
                    step_name="done",
                    step_type="direct",
                    agent_id="agent-primary",
                    status="approved",
                ),
            ]
        )
        await session.commit()
        session.add_all(
            [
                ChannelAccountRow(
                    account_id="channel-account",
                    channel_type="signal",
                    display_name="Signal",
                    agent_id="agent-primary",
                    user_email="alice@cognis.local",
                    enabled=True,
                ),
                ChannelDeliveryOutboxRow(
                    delivery_id="delivery-pending",
                    user_email="alice@cognis.local",
                    conversation_id="conversation-open",
                    channel_type="signal",
                    account_id="channel-account",
                    chat_id="signal-chat",
                    source_type="follow_up",
                    status="pending",
                ),
                ExecutorRow(
                    executor_id="executor-local",
                    name="Local Executor",
                    executor_type="in_process",
                    status="active",
                    runtime_state="ready",
                ),
            ]
        )
        await session.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


def _family(snapshot: Any, name: str) -> list[dict[str, Any]]:
    for family_name, _documentation, _labels, rows in snapshot.metric_rows:
        if family_name == name:
            return [dict(labels) | {"value": value} for labels, value in rows]
    raise AssertionError(f"missing family {name}")


def test_metrics_endpoint_is_publicly_exempt_for_internal_pod_scraping() -> None:
    assert ("GET", "/api/metrics") in PUBLIC_ROUTES


@pytest.mark.asyncio
async def test_sql_aggregates_cover_active_windows_and_direct_turn_states(
    observability_db: async_sessionmaker[Any],
) -> None:
    async with observability_db() as session:
        snapshot = await collect_observability_snapshot(session)

    assert {row["status"] for row in _family(snapshot, "cognis_turn_requests")} == {
        "queued",
        "running",
    }
    conversations = _family(snapshot, "cognis_conversations")
    assert sum(row["value"] for row in conversations if row["status"] == "active") == 1
    users = _family(snapshot, "cognis_users")
    assert {row["status"]: row["value"] for row in users} == {
        "active": 1,
        "disabled": 1,
    }
    assert all("user" not in row for row in users)
    active_windows = _family(snapshot, "cognis_agents_active")
    assert len(active_windows) == 4
    assert active_windows[0]["agent"] == "agent-primary"
    assert sum(row["value"] for row in _family(snapshot, "cognis_executions_active")) == 1


def test_normalization_has_precise_missing_values_and_rejects_uuid_labels() -> None:
    assert normalize_inherited(None) == "inherit"
    assert normalize_profile(None) == "none"
    for value in (
        "00000000-0000-0000-0000-000000000000",
        "550e8400-e29b-41d4-a716-446655440000",
        "018f5f71-6a2f-7d8e-8abc-123456789abc",
        "550e8400-e29b-81d4-c716-446655440000",
    ):
        assert normalize_slug(value) == "unknown"
    assert normalize_slug("OpenAI Provider") == "unknown"


def test_metric_contract_exposes_no_identifier_or_content_labels() -> None:
    """Canonical email labels are valid only behind a private scrape boundary."""
    forbidden = {
        "agent_id",
        "conversation_id",
        "content",
        "prompt",
        "session_id",
        "tool_arguments",
        "user_id",
    }
    labels = {
        "user",
        "agent",
        "provider",
        "model",
        "profile",
        "origin",
        "status",
    }
    assert labels.isdisjoint(forbidden)


@pytest.mark.asyncio
async def test_full_family_cap_records_omission(observability_db: async_sessionmaker[Any]) -> None:
    async with observability_db() as session:
        snapshot = await collect_observability_snapshot(session, max_family_cardinality=1)

    assert len(_family(snapshot, "cognis_users")) == 0
    assert ("users", 1) in snapshot.cardinality_omitted


@pytest.mark.asyncio
async def test_rolling_window_families_share_one_cardinality_cap(
    observability_db: async_sessionmaker[Any],
) -> None:
    async with observability_db() as session:
        snapshot = await collect_observability_snapshot(session, max_family_cardinality=3)

    assert _family(snapshot, "cognis_users_active") == []
    assert _family(snapshot, "cognis_agents_active") == []
    assert ("users_active", 1) in snapshot.cardinality_omitted
    assert ("agents_active", 1) in snapshot.cardinality_omitted


@pytest.mark.asyncio
async def test_inventory_families_keep_detailed_owner_and_type_labels(
    observability_db: async_sessionmaker[Any],
) -> None:
    async with observability_db() as session:
        snapshot = await collect_observability_snapshot(session)

    assert _family(snapshot, "cognis_agents") == [
        {
            "user": "alice@cognis.local",
            "agent": "agent-primary",
            "type": "primary",
            "status": "active",
            "value": 1.0,
        }
    ]
    assert _family(snapshot, "cognis_conversations")[0].keys() == {
        "user",
        "agent",
        "profile",
        "origin",
        "status",
        "value",
    }


@pytest.mark.asyncio
async def test_executor_safe_names_are_unique_per_owner(
    observability_db: async_sessionmaker[Any],
) -> None:
    async with observability_db() as session:
        session.add(
            ExecutorRow(
                executor_id="executor-bob",
                name="MacBook",
                executor_type="websocket",
                status="active",
                runtime_state="ready",
                owner_email="bob@cognis.local",
            )
        )
        session.add(
            ExecutorRow(
                executor_id="executor-alice-macbook",
                name="MacBook",
                executor_type="websocket",
                status="active",
                runtime_state="ready",
                owner_email="alice@cognis.local",
            )
        )
        await session.commit()
        snapshot = await collect_observability_snapshot(session)

    assert dict(snapshot.executor_slugs) == {
        "executor-bob": ("macbook", "bob@cognis.local"),
        "executor-alice-macbook": ("macbook", "alice@cognis.local"),
    }


@pytest.mark.asyncio
async def test_lease_loss_and_stale_snapshot_suppress_business_series(
    observability_db: async_sessionmaker[Any],
) -> None:
    service = ObservabilityService(observability_db, owner_id="controller-local")
    lease = SimpleNamespace(
        resource_key="cognis:observability:v2",
        owner_id="controller-local",
        fencing_token=1,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=90),
    )

    class LeaseStore:
        async def acquire(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            return lease

        async def renew(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            return lease

        async def release(self, *args: Any, **kwargs: Any) -> bool:
            del args, kwargs
            return True

    service._lease_store = LeaseStore()  # type: ignore[assignment]
    assert await service.refresh_once() is True
    service._state = ObservabilityState(
        snapshot=service.state.snapshot,
        refreshed_at=service.state.refreshed_at - OBSERVABILITY_MAX_SNAPSHOT_AGE_SECONDS - 1,
        owner=True,
    )
    assert not any(
        metric.name == "cognis_users" for metric in ObservabilityCollector(service).collect()
    )

    async def lose_lease(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        return None

    service._lease_store.renew = lose_lease  # type: ignore[method-assign]
    assert await service.refresh_once() is False
    assert service.state.snapshot is None


@pytest.mark.asyncio
async def test_lsp_timeout_and_partial_results_are_bounded() -> None:
    class Provider:
        async def get_lsp_statuses(self, *, owner_email: str | None = None) -> list[Any]:
            del owner_email
            return [
                SimpleNamespace(
                    executor_id="executor-1",
                    executor_type="websocket",
                    state="ready",
                    totals=SimpleNamespace(
                        active_server_count=2,
                        files_tracked=3,
                        total_errors=1,
                    ),
                    spawning_count=4,
                ),
                SimpleNamespace(
                    executor_id="executor-1",
                    executor_type="websocket",
                    state="ready",
                ),
                SimpleNamespace(
                    executor_id="550e8400-e29b-41d4-a716-446655440000",
                    executor_type="websocket",
                    state="ready",
                ),
            ]

    service = ObservabilityService(
        lambda: None, owner_id="controller-local", lsp_provider=Provider()
    )
    service._state = ObservabilityState(
        snapshot=SimpleNamespace(
            executor_slugs={"executor-1": ("linux-builder", "alice@cognis.local")}
        ),
        refreshed_at=1.0,
        owner=True,
    )  # type: ignore[arg-type]
    rows = await service._collect_lsp()
    assert [row.executor for row in rows] == ["linux-builder"]
    assert rows[0].user == "alice@cognis.local"
    assert rows[0].spawns_pending == 4
    assert rows[0].diagnostics == (("error", 1), ("warning", 0))
    assert rows[0].snapshot_timestamp > 0

    class SlowProvider:
        async def get_lsp_statuses(self, *, owner_email: str | None = None) -> list[Any]:
            del owner_email
            await asyncio.sleep(5.1)
            return []

    slow = ObservabilityService(
        lambda: None,
        owner_id="controller-local",
        lsp_provider=SlowProvider(),
    )
    assert await slow._collect_lsp() == []


@pytest.mark.asyncio
async def test_lsp_diagnostics_family_cap_limits_observations() -> None:
    class Provider:
        async def get_lsp_statuses(self, *, owner_email: str | None = None) -> list[Any]:
            del owner_email
            return [
                SimpleNamespace(
                    executor_id=f"executor-{index}",
                    executor_type="websocket",
                    state="ready",
                    totals=SimpleNamespace(),
                    spawning_count=0,
                )
                for index in range(3)
            ]

    service = ObservabilityService(
        lambda: None, owner_id="controller-local", lsp_provider=Provider(), max_family_cardinality=3
    )
    service._state = ObservabilityState(
        snapshot=SimpleNamespace(
            executor_slugs={
                f"executor-{index}": (f"executor-{index}", "alice@cognis.local")
                for index in range(3)
            }
        ),
        refreshed_at=1.0,
        owner=True,
    )  # type: ignore[arg-type]
    rows = await service._collect_lsp()
    assert len(rows) == 1
    assert len(_lsp_families(tuple(rows))[3].samples) == 2


@pytest.mark.asyncio
async def test_lease_expiry_during_collection_drops_unpublished_snapshot(
    observability_db: async_sessionmaker[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ObservabilityService(observability_db, owner_id="controller-local")
    lease = SimpleNamespace(
        resource_key="cognis:observability:v2",
        owner_id="controller-local",
        fencing_token=7,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=90),
    )

    class ExpiringLeaseStore:
        async def acquire(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            return lease

        async def renew(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            return None

    async def slow_collect(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        await asyncio.sleep(0.01)
        return SimpleNamespace(
            collected_at=datetime.now(UTC),
            metric_rows=(),
            cardinality_omitted=(),
            executor_slugs={},
        )

    monkeypatch.setattr(
        "cognis.core.observability.collect_observability_snapshot",
        slow_collect,
    )
    service._lease_store = ExpiringLeaseStore()  # type: ignore[assignment]
    assert await service.refresh_once() is False
    assert service.state.snapshot is None
    assert service.state.owner is False


def test_collector_does_not_perform_scrape_io() -> None:
    def forbidden_session_factory() -> Any:
        raise AssertionError("scrape must not open a database session")

    service = ObservabilityService(forbidden_session_factory, owner_id="controller-local")
    service._state = ObservabilityState(refreshed_at=0.0, owner=False)
    assert list(ObservabilityCollector(service).collect()) == []


def test_attribution_context_is_scoped_and_labels_are_explicit() -> None:
    token = set_attribution(
        Attribution(
            user="alice@cognis.local",
            agent="primary-agent",
            provider="openai",
            model="gpt-5",
            profile="none",
            origin="direct",
            status="success",
        )
    )
    try:
        record_attributed_turn()
        record_attributed_llm_request()
    finally:
        reset_attribution(token)
    assert current_attribution() is None


def test_attributed_collectors_have_a_hard_tuple_cap() -> None:
    registry = CollectorRegistry()
    collector = BoundedAttributedCounterCollector(
        "cognis_test_attributed_total",
        "Bounded attributed test counter.",
    )
    registry.register(collector)
    for index in range(5001):
        collector.record(
            {
                "user": f"user-{index}@cognis.local",
                "agent": "agent-primary",
                "provider": "openai",
                "model": "gpt-5",
                "profile": "none",
                "origin": "direct",
                "status": "completed",
            }
        )
    exposition = generate_latest(registry).decode()
    assert exposition.count("cognis_test_attributed_total{") == 5000


@pytest.mark.asyncio
async def test_service_registers_and_unregisters_custom_collectors() -> None:
    registry = CollectorRegistry()
    service = ObservabilityService(
        lambda: None,
        owner_id="controller-local",
        registry=registry,
    )
    await service.start()
    exposition = generate_latest(registry).decode()
    assert "# TYPE cognis_turns_attributed_total counter" in exposition
    await service.stop()
    assert "cognis_turns_attributed_total" not in generate_latest(registry).decode()


@pytest.mark.asyncio
async def test_inventory_family_names_are_the_approved_contract(
    observability_db: async_sessionmaker[Any],
) -> None:
    expected = {
        "cognis_users",
        "cognis_users_active",
        "cognis_agents",
        "cognis_agents_active",
        "cognis_conversations",
        "cognis_sessions",
        "cognis_turn_requests",
        "cognis_turns_active",
        "cognis_tasks",
        "cognis_executions_active",
        "cognis_channel_accounts",
        "cognis_channel_deliveries",
        "cognis_executors",
        "cognis_executor_state",
    }
    async with observability_db() as session:
        snapshot = await collect_observability_snapshot(session)
    assert {name for name, _documentation, _labels, _rows in snapshot.metric_rows} == expected
    assert {name: labels for name, _documentation, labels, _rows in snapshot.metric_rows} == {
        "cognis_users": ("status",),
        "cognis_users_active": ("window", "user"),
        "cognis_agents": ("user", "agent", "type", "status"),
        "cognis_agents_active": ("window", "user", "agent", "type"),
        "cognis_conversations": ("user", "agent", "profile", "origin", "status"),
        "cognis_sessions": ("user", "agent", "provider", "model", "profile", "origin", "status"),
        "cognis_turn_requests": (
            "user",
            "agent",
            "provider",
            "model",
            "profile",
            "origin",
            "status",
        ),
        "cognis_turns_active": (
            "user",
            "agent",
            "provider",
            "model",
            "profile",
            "origin",
            "status",
        ),
        "cognis_tasks": ("user", "agent", "profile", "origin", "status"),
        "cognis_executions_active": (
            "user",
            "agent",
            "provider",
            "model",
            "profile",
            "origin",
            "type",
            "status",
        ),
        "cognis_channel_accounts": ("user", "agent", "profile", "channel", "status"),
        "cognis_channel_deliveries": ("user", "agent", "channel", "status"),
        "cognis_executors": ("user", "type", "status"),
        "cognis_executor_state": ("user", "executor", "type", "status"),
    }
    assert {
        family.name: tuple(sample.labels.keys())
        for family in _lsp_families(
            (
                SimpleNamespace(
                    user="alice@cognis.local",
                    executor="macbook",
                    executor_type="websocket",
                    state="ready",
                    servers=1,
                    files=1,
                    diagnostics=(("error", 0), ("warning", 0)),
                    spawns_pending=0,
                    snapshot_timestamp=1.0,
                ),
            )
        )
        for sample in family.samples[:1]
    } == {
        "cognis_lsp_state": ("user", "executor", "executor_type", "state"),
        "cognis_lsp_servers_active": ("user", "executor", "executor_type"),
        "cognis_lsp_files_tracked": ("user", "executor", "executor_type"),
        "cognis_lsp_diagnostics": ("user", "executor", "executor_type", "severity"),
        "cognis_lsp_spawns_pending": ("user", "executor", "executor_type"),
        "cognis_lsp_snapshot_timestamp_seconds": ("user", "executor", "executor_type"),
    }

    registry = CollectorRegistry()
    service = ObservabilityService(observability_db, owner_id="controller-local", registry=registry)
    service._state = ObservabilityState(
        snapshot=snapshot,
        refreshed_at=monotonic(),
        owner=True,
    )
    registry.register(service.collector)
    exposition = generate_latest(registry).decode()
    for name in expected:
        assert f"# HELP {name} " in exposition
        assert f"# TYPE {name} gauge" in exposition
    assert "cognis_observability_" not in exposition
    assert all(
        forbidden not in exposition
        for forbidden in ("agent_id", "conversation_id", "session_id", "content", "prompt")
    )
