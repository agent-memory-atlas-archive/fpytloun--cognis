"""Shared selection of the owner-scoped attachment analysis route."""

from __future__ import annotations

from typing import Any

from cognis.store.queries import get_model_routing


async def get_attachment_analysis_route(
    session_factory: Any, *, owner_email: str | None = None
) -> tuple[str | None, str | None]:
    """Resolve the configured route without holding a session during inference."""
    async with session_factory() as session:
        route = None
        if owner_email:
            route = await get_model_routing(session, "attachment_analysis", owner_email=owner_email)
        if route is None:
            route = await get_model_routing(session, "attachment_analysis")
    if route is None:
        return None, None
    model = str(getattr(route, "model", "") or "").strip()
    if not model:
        return None, None
    provider_id = getattr(route, "provider_id", None)
    return model, str(provider_id) if isinstance(provider_id, str) and provider_id else None
