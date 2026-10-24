from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from cognis.api import executor_monitor
from cognis.api.websocket import AuthenticatedWebSocket, WebSocketConnectionManager
from cognis.core.cluster_signals import ClusterSignalKind
from cognis.core.events import Event, EventType
from cognis.ownership import SYSTEM_USER_EMAIL


def _app() -> SimpleNamespace:
    session = AsyncMock()
    factory = Mock(return_value=SimpleNamespace())
    factory.return_value = session
    return SimpleNamespace(
        state=SimpleNamespace(
            session_factory=factory,
            event_bus=SimpleNamespace(publish=AsyncMock()),
            cluster_signals=SimpleNamespace(publish=AsyncMock()),
        )
    )


def _viewer(email: str, *, monitoring: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        user_email=email,
        executor_monitoring=monitoring,
        send_scope_invalidation_nowait=Mock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["owner@example.com", SYSTEM_USER_EMAIL, None])
async def test_monitor_fanout_reauthorizes_and_excludes_inactive_viewers(
    monkeypatch: pytest.MonkeyPatch, owner: str | None
) -> None:
    now = datetime.now(UTC)
    row = SimpleNamespace(
        owner_email=owner,
        status="active",
        runtime_state="active",
        desired_config_version=2,
        applied_config_version=2,
        last_observed_at=now,
        runtime_metadata={
            "monitor_runtime_revision": "mcp-state-1",
            "resource_snapshot": {
                "schema_version": 1,
                "observed_at": now.isoformat(),
                "cpu": {"utilization_percent": 37},
            },
            "resource_snapshot_received_at": now.isoformat(),
            "secrets": {"must_not": "escape"},
        },
    )
    lookup = AsyncMock(return_value=row)
    monkeypatch.setattr(executor_monitor, "get_executor_row", lookup)
    owner_view = _viewer("owner@example.com")
    other_view = _viewer("other@example.com")
    inactive_view = _viewer("owner@example.com", monitoring=False)
    app = _app()
    # Exercise the real cluster -> WebSocket adapter boundary.
    manager = object.__new__(WebSocketConnectionManager)
    manager.app = app
    manager._connections = {"owner": owner_view, "other": other_view, "inactive": inactive_view}
    await manager._handle_cluster_scope_invalidated(
        Event(
            type=EventType.CLUSTER_SCOPE_INVALIDATED,
            data={
                "kind": ClusterSignalKind.EXECUTOR_MONITOR_CHANGED,
                "scope": {"executor_id": "host-linux"},
                "revision": now.isoformat(),
            },
        )
    )
    lookup.assert_awaited_once()
    payload = owner_view.send_scope_invalidation_nowait.call_args.args[0]
    assert payload["resource_snapshot"]["cpu"]["utilization_percent"] == 37
    assert payload["resource_snapshot"]["freshness"]["stale"] is False
    assert payload["details_revision"] == "mcp-state-1"
    assert set(payload) == {
        "type",
        "executor_id",
        "details_revision",
        "status",
        "runtime_state",
        "desired_config_version",
        "applied_config_version",
        "last_observed_at",
        "resource_snapshot",
    }
    assert other_view.send_scope_invalidation_nowait.call_count == (
        0 if owner == "owner@example.com" else 1
    )
    inactive_view.send_scope_invalidation_nowait.assert_not_called()


@pytest.mark.asyncio
async def test_monitor_does_not_read_inventory_without_viewers() -> None:
    app = _app()
    await executor_monitor.send_executor_monitor_update(
        app, [_viewer("owner@example.com", monitoring=False)], "host-linux"
    )
    app.state.session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_monitor_publishes_only_an_identity_pointer_locally_and_across_replicas() -> None:
    app = _app()
    await executor_monitor.publish_executor_monitor_change(app, "host-linux")
    event = app.state.event_bus.publish.call_args.args[0]
    assert event.type == EventType.CLUSTER_SCOPE_INVALIDATED
    assert event.data["scope"] == {"executor_id": "host-linux"}
    app.state.cluster_signals.publish.assert_awaited_once()


def test_monitor_frames_coalesce_per_executor_not_globally() -> None:
    assert AuthenticatedWebSocket._scope_invalidation_key(
        {"type": "executor_monitor_update", "executor_id": "host-linux"}
    ) != AuthenticatedWebSocket._scope_invalidation_key(
        {"type": "executor_monitor_update", "executor_id": "host-macos"}
    )
