"""Thin owner-scoped hook administration adapters."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from cognis.api.common import api_exception, forbid_mutation_for_viewer, require_current_user
from cognis.core.hooks import HookError, manage_hooks, notify_hook_change
from cognis.models.hooks import HookAssignment, HookDefinition, HookResponse, HookRunResponse

router = APIRouter(prefix="/api/v1", tags=["hooks"])


async def _action(request: Request, action: str, **kwargs: Any) -> dict[str, Any]:
    user = require_current_user(request)
    if action not in {"hooks_list", "hooks_get", "hook_assignments_get", "hook_runs_list"}:
        forbid_mutation_for_viewer(request)
    try:
        async with request.app.state.session_factory() as db:
            result = await manage_hooks(db, owner=user.email, action=action, **kwargs)
            await db.commit()
        await notify_hook_change(getattr(request.app.state, "event_bus", None), action, kwargs)
        return result
    except HookError as exc:
        raise api_exception(400, "hook_validation_error", str(exc)) from exc


@router.get("/hooks", response_model=dict[str, list[HookResponse]])
async def list_hooks(request: Request) -> dict[str, Any]:
    return await _action(request, "hooks_list")


@router.post("/hooks", response_model=HookResponse)
async def create_hook(request: Request, payload: HookDefinition) -> dict[str, Any]:
    return await _action(request, "hooks_create", definition=payload.model_dump(mode="json"))


@router.get("/hooks/runs", response_model=dict[str, list[HookRunResponse]])
async def list_runs(request: Request, agent_id: str | None = None) -> dict[str, Any]:
    return await _action(request, "hook_runs_list", agent_id=agent_id)


@router.get("/hooks/{hook_id}", response_model=HookResponse)
async def get_hook(request: Request, hook_id: str) -> dict[str, Any]:
    return await _action(request, "hooks_get", hook_id=hook_id)


@router.put("/hooks/{hook_id}", response_model=HookResponse)
async def update_hook(
    request: Request,
    hook_id: str,
    payload: HookDefinition,
    expected_revision: int,
) -> dict[str, Any]:
    return await _action(
        request,
        "hooks_update",
        hook_id=hook_id,
        definition=payload.model_dump(mode="json"),
        expected_revision=expected_revision,
    )


@router.delete("/hooks/{hook_id}")
async def delete_hook(request: Request, hook_id: str, expected_revision: int) -> dict[str, Any]:
    return await _action(
        request, "hooks_delete", hook_id=hook_id, expected_revision=expected_revision
    )


@router.get("/agents/{agent_id}/hooks", response_model=dict[str, list[HookAssignment]])
async def get_assignments(request: Request, agent_id: str) -> dict[str, Any]:
    return await _action(request, "hook_assignments_get", agent_id=agent_id)


@router.put("/agents/{agent_id}/hooks", response_model=HookAssignment)
async def put_assignment(
    request: Request,
    agent_id: str,
    payload: HookAssignment,
) -> dict[str, Any]:
    return await _action(
        request,
        "hook_assignments_put",
        agent_id=agent_id,
        assignment=payload.model_dump(mode="json"),
    )


@router.delete("/agents/{agent_id}/hooks/{hook_id}")
async def remove_assignment(request: Request, agent_id: str, hook_id: str) -> dict[str, Any]:
    return await _action(request, "hook_assignments_remove", agent_id=agent_id, hook_id=hook_id)
