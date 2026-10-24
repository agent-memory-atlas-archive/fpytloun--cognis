"""Named inference route operations shared by HTTP and controller tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from cognis.api.common import api_exception
from cognis.core.management_access import ManagementActor
from cognis.ownership import SYSTEM_USER_EMAIL
from cognis.providers.llm.recovery_policy import NamedRouteConfig
from cognis.providers.llm.route_store import InferenceRouteStore, NamedRoute
from cognis.store.models import InferenceRoute, LLMProvider


class RouteUpdate(BaseModel):
    config: NamedRouteConfig
    expected_revision: int = Field(ge=1)


def result(route: NamedRoute) -> dict[str, Any]:
    return {
        "route_id": route.route_id,
        "revision": route.revision,
        "reference": f"cognis/{route.config.name}",
        "owner_scope": "global" if route.owner == SYSTEM_USER_EMAIL else "user",
        "config": route.config.model_dump(),
    }


async def validate_targets(llm: Any, config: NamedRouteConfig, owner: str) -> None:
    modes = set()
    for target in config.targets:
        await llm.resolve_model_reference(target.reference, acting_user_email=owner)
        info = await llm.get_model_info(
            target.model,
            provider_id=target.provider_id,
            acting_user_email=owner,
        )
        modes.add((info.supports_embedding, getattr(info, "model_mode", None)))
    if len(modes) != 1:
        raise ValueError("All route targets must support the same operation")
    if any(embedding for embedding, _ in modes) and len(config.targets) != 1:
        raise ValueError("Embedding routes support exactly one target")


async def list_routes(session_factory: Any, actor: ManagementActor) -> dict[str, Any]:
    """List routes visible to the actor."""
    routes = await InferenceRouteStore(session_factory).list(actor.email)
    return {"routes": [result(route) for route in routes]}


async def create_route(
    session_factory: Any,
    llm: Any,
    actor: ManagementActor,
    config: NamedRouteConfig,
    *,
    preview: bool = False,
) -> dict[str, Any]:
    """Validate targets and create a route in its authorized ownership scope."""
    actor.require_admin()
    try:
        owner = SYSTEM_USER_EMAIL
        async with session_factory() as session:
            for target in config.targets:
                provider = await session.get(LLMProvider, target.provider_id)
                if provider is None or provider.owner_email not in {SYSTEM_USER_EMAIL, actor.email}:
                    raise ValueError("Unknown or unavailable inference provider")
                if provider.owner_email != SYSTEM_USER_EMAIL:
                    owner = actor.email
        await validate_targets(llm, config, owner)
        if preview:
            return {"preview": True, "owner": owner, "config": config.model_dump(mode="json")}
        route = await InferenceRouteStore(session_factory).save(config, owner=owner)
        return result(route)
    except ValueError as exc:
        raise api_exception(422, "validation_error", str(exc)) from exc
    except IntegrityError as exc:
        raise api_exception(409, "route_conflict", "A route with this name already exists") from exc


async def update_route(
    session_factory: Any,
    llm: Any,
    actor: ManagementActor,
    route_id: str,
    payload: RouteUpdate,
    *,
    preview: bool = False,
) -> dict[str, Any]:
    """Replace a route using its atomic revision precondition."""
    actor.require_admin()
    try:
        async with session_factory() as session:
            existing = await session.get(InferenceRoute, route_id)
            if existing is None or existing.owner_email not in {SYSTEM_USER_EMAIL, actor.email}:
                raise ValueError("Unknown or unavailable inference route")
            owner = existing.owner_email
            if existing.revision != payload.expected_revision:
                raise ValueError("Inference route changed; read it again")
        await validate_targets(llm, payload.config, owner)
        if preview:
            return {
                "preview": True,
                "route_id": route_id,
                "config": payload.config.model_dump(mode="json"),
            }
        route = await InferenceRouteStore(session_factory).save(
            payload.config,
            owner=owner,
            route_id=route_id,
            expected_revision=payload.expected_revision,
        )
        return result(route)
    except ValueError as exc:
        raise api_exception(409, "route_conflict", str(exc)) from exc
    except IntegrityError as exc:
        raise api_exception(409, "route_conflict", "A route with this name already exists") from exc


async def delete_route(
    session_factory: Any,
    actor: ManagementActor,
    route_id: str,
    expected_revision: int,
    *,
    preview: bool = False,
) -> dict[str, Any]:
    """Reject dependencies before compare-and-swap deletion."""
    actor.require_admin()
    async with session_factory() as session:
        route = await session.get(InferenceRoute, route_id)
        if route is None or route.owner_email not in {SYSTEM_USER_EMAIL, actor.email}:
            raise api_exception(409, "route_conflict", "Route changed or no longer exists")
        try:
            await InferenceRouteStore.assert_unreferenced(session, route)
        except ValueError as exc:
            raise api_exception(409, "route_conflict", str(exc)) from exc
        if route.revision != expected_revision:
            raise api_exception(409, "route_conflict", "Route changed; read it again")
        if preview:
            return {"preview": True, "route_id": route_id, "deleted": False}
        deleted = await session.execute(
            delete(InferenceRoute).where(
                InferenceRoute.route_id == route_id,
                InferenceRoute.owner_email == route.owner_email,
                InferenceRoute.revision == expected_revision,
            )
        )
        if not deleted.rowcount:
            raise api_exception(409, "route_conflict", "Route changed or no longer exists")
        await session.commit()
    return {"deleted": True}
