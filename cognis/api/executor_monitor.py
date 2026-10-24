"""Page-scoped executor telemetry fanout; no tool inventory or secrets on the wire."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cognis.api.models import WebSocketExecutorMonitorUpdate
from cognis.core.cluster_signals import ClusterSignalKind, ClusterSignalScope
from cognis.core.events import Event, EventType
from cognis.models.executor_resources import normalize_executor_resource_snapshot
from cognis.ownership import is_shared_owner_email
from cognis.store.queries import get_executor_row


async def publish_executor_monitor_change(app: Any, executor_id: str) -> None:
    """Notify local and remote viewers only after the runtime transaction commits."""
    revision = datetime.now(UTC).isoformat()
    scope = ClusterSignalScope(executor_id=executor_id)
    event_bus = getattr(app.state, "event_bus", None)
    if event_bus is not None:
        await event_bus.publish(
            Event(
                type=EventType.CLUSTER_SCOPE_INVALIDATED,
                data={
                    "kind": ClusterSignalKind.EXECUTOR_MONITOR_CHANGED,
                    "scope": scope.model_dump(exclude_none=True),
                    "revision": revision,
                },
            )
        )
    signals = getattr(app.state, "cluster_signals", None)
    if signals is not None:
        await signals.publish(
            ClusterSignalKind.EXECUTOR_MONITOR_CHANGED, scope=scope, revision=revision
        )


async def send_executor_monitor_update(app: Any, connections: list[Any], executor_id: str) -> None:
    """Read once per replica and authorize every subscriber against the current row."""
    viewers = [connection for connection in connections if connection.executor_monitoring]
    if not viewers:
        return
    async with app.state.session_factory() as session:
        row = await get_executor_row(session, executor_id, defer_observed_tools=True)
    if row is None:
        return
    metadata = row.runtime_metadata or {}
    snapshot = normalize_executor_resource_snapshot(metadata.get("resource_snapshot"))
    received_at = metadata.get("resource_snapshot_received_at")
    try:
        received_at = datetime.fromisoformat(received_at) if isinstance(received_at, str) else None
    except ValueError:
        received_at = None
    payload = WebSocketExecutorMonitorUpdate(
        executor_id=executor_id,
        details_revision=metadata.get("monitor_runtime_revision"),
        status=row.status,
        runtime_state=row.runtime_state,
        desired_config_version=row.desired_config_version,
        applied_config_version=row.applied_config_version,
        last_observed_at=row.last_observed_at,
        resource_snapshot=(
            snapshot.with_current_freshness(received_at=received_at)
            if snapshot is not None
            else None
        ),
    ).model_dump(mode="json")
    for connection in viewers:
        if is_shared_owner_email(row.owner_email) or row.owner_email == connection.user_email:
            connection.send_scope_invalidation_nowait(payload)
