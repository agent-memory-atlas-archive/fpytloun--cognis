"""HTTP adapters for named inference route management."""

from typing import Any

from fastapi import APIRouter, Request

from cognis.api.common import require_admin, require_session_user
from cognis.core import route_management as service
from cognis.core.management_access import ManagementActor
from cognis.core.route_management import RouteUpdate
from cognis.providers.llm.recovery_policy import NamedRouteConfig

router = APIRouter()


@router.get("/api/v1/inference-routes")
async def list_routes(request: Request) -> dict[str, Any]:
    user = require_session_user(request)
    return await service.list_routes(
        request.app.state.session_factory, ManagementActor(user.email, user.role)
    )


@router.post("/api/v1/inference-routes")
async def create_route(request: Request, config: NamedRouteConfig) -> dict[str, Any]:
    user = require_admin(request)
    return await service.create_route(
        request.app.state.session_factory,
        request.app.state.providers.llm,
        ManagementActor(user.email, user.role),
        config,
    )


@router.put("/api/v1/inference-routes/{route_id}")
async def update_route(request: Request, route_id: str, payload: RouteUpdate) -> dict[str, Any]:
    user = require_admin(request)
    return await service.update_route(
        request.app.state.session_factory,
        request.app.state.providers.llm,
        ManagementActor(user.email, user.role),
        route_id,
        payload,
    )


@router.delete("/api/v1/inference-routes/{route_id}")
async def delete_route(request: Request, route_id: str, expected_revision: int) -> dict[str, Any]:
    user = require_admin(request)
    return await service.delete_route(
        request.app.state.session_factory,
        ManagementActor(user.email, user.role),
        route_id,
        expected_revision,
    )
