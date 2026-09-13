"""Post-commit hints for durable task claiming; never transfer claim authority."""

from __future__ import annotations

from datetime import UTC, datetime

from cognis.core.cluster_signals import (
    ClusterSignalKind,
    ClusterSignalScope,
    ClusterSignalService,
)
from cognis.core.events import Event, EventBus, EventType


async def publish_queue_wakeup(
    event_bus: EventBus, cluster_signals: ClusterSignalService | None
) -> None:
    """Wake local and remote claimers after a committed queue/capacity change."""
    await event_bus.publish(
        Event(
            type=EventType.CLUSTER_SCOPE_INVALIDATED,
            data={"kind": ClusterSignalKind.TASK_QUEUE_CHANGED, "scope": {}},
        )
    )
    if cluster_signals is not None:
        await cluster_signals.publish(
            ClusterSignalKind.TASK_QUEUE_CHANGED,
            scope=ClusterSignalScope(),
            revision=datetime.now(UTC),
        )
