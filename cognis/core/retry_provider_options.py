"""Read-only same-model alternatives for a provider rate-limit wait."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognis.store.coordination import database_now
from cognis.store.direct_turns import DirectTurnStatus, DirectTurnStore
from cognis.store.models import DirectTurnRequestRow

if TYPE_CHECKING:
    from cognis.core.provider_monitor import ProviderMonitor


class ModelCatalog(Protocol):
    """Visibility-filtered configured model references."""

    async def list_model_references(
        self, acting_user_email: str | None = None
    ) -> list[dict[str, Any]]: ...


async def resolve_retry_provider_context(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: str,
    turn_id: str | None,
    provider_id: str | None,
    model: str | None,
    load_failures: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> dict[str, Any] | None:
    """Reject historical failures once another execution supersedes them."""
    store = DirectTurnStore(session_factory)
    latest = await store.get_conversation_runtime_authority_row(conversation_id)
    if latest is None or (turn_id is not None and latest.turn_id != turn_id):
        return None
    if latest.status == DirectTurnStatus.RECOVERABLE.value:
        target = (latest.outcome or {}).get("retry_target", {})
        if target.get("scope") != "provider_model":
            return None
        if (provider_id and target.get("provider_id") != provider_id) or (
            model and target.get("model") != model
        ):
            return None
        return {
            "turn_id": latest.turn_id,
            "status": "waiting",
            "provider_id": target.get("provider_id"),
            "model": target.get("model"),
        }
    if latest.status == DirectTurnStatus.FAILED.value and turn_id and provider_id and model:
        failures = await load_failures()
        failure = next(
            (
                item
                for item in reversed(failures)
                if item.get("notice_kind") == "model_error" and item.get("turn_id") == turn_id
            ),
            None,
        )
        if (
            not failure
            or failure.get("provider_id") != provider_id
            or failure.get("model") != model
        ):
            return None
        # Event-store reads run outside the DB session; reject a successor or retry.
        current = await store.get_conversation_runtime_authority_row(conversation_id)
        if current is None or (
            current.request_id != latest.request_id
            or current.status != latest.status
            or current.fencing_token != latest.fencing_token
        ):
            return None
        return {"turn_id": turn_id, "status": "failed", "provider_id": provider_id, "model": model}
    return None


async def retry_provider_options(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    llm: ModelCatalog,
    monitor: ProviderMonitor | None,
    user_email: str,
    active_turn: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    """List visible exact-model alternatives without fetching upstream usage."""
    if not active_turn or (
        active_turn.get("status") not in {"waiting", "failed"}
        or not active_turn.get("model")
        or not active_turn.get("provider_id")
    ):
        return []
    model = active_turn["model"]
    current_provider = active_turn["provider_id"]
    references = await llm.list_model_references(acting_user_email=user_email)
    candidates = {
        ref["provider_id"]: {
            "provider_id": ref["provider_id"],
            "display_name": ref.get("provider_display_name") or ref["provider_id"],
            "model": model,
        }
        for ref in references
        if ref.get("model_id") == model
        and ref.get("provider_id")
        and ref["provider_id"] != current_provider
    }
    if not candidates:
        return []
    # Retry metadata belongs to the durable turn owner and is shared by replicas.
    # Only exact candidate identities are queried; no other conversation data escapes.
    async with session_factory() as db:
        now = await database_now(db)
        target = DirectTurnRequestRow.outcome["retry_target"]
        blocked = set(
            (
                await db.execute(
                    select(target["provider_id"].as_string()).where(
                        DirectTurnRequestRow.status == DirectTurnStatus.RECOVERABLE.value,
                        DirectTurnRequestRow.next_attempt_at > now,
                        target["scope"].as_string() == "provider_model",
                        target["model"].as_string() == model,
                        target["provider_id"].as_string().in_(candidates),
                    )
                )
            ).scalars()
        )
    if monitor is not None:
        observations = await monitor.list_visible(user_email)
        blocked.update(quota_blocked_providers(observations))
    return [
        candidate
        for provider_id, candidate in sorted(candidates.items())
        if provider_id not in blocked
    ]


def quota_blocked_providers(observations: Iterable[Any]) -> set[str]:
    """Exclude explicit fresh quota exhaustion, not merely warning thresholds."""
    return {
        observation.provider_id
        for observation in observations
        if not observation.stale
        and observation.usage is not None
        and observation.usage.ok
        and (observation.usage.allowed is False or observation.usage.limit_reached is True)
    }
