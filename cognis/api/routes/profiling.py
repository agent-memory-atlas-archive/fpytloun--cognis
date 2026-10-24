"""Admin API-key/session authorized, content-free controller diagnostics."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from cognis.api.common import api_exception, require_admin
from cognis.core.profiling_capture import CaptureOptions
from cognis.core.profiling_control import ProfilingConflict, ProfilingControl
from cognis.core.redis_service import RedisUnavailableError

router = APIRouter(prefix="/api/v1/system/profiling", tags=["system"])


class StartProfilingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capture_id: UUID
    options: CaptureOptions = Field(default_factory=CaptureOptions)
    targets: list[str] | None = Field(default=None, min_length=1, max_length=8)


class ProfilingResponse(BaseModel):
    """Versioned aggregates; raw payloads or raw heap snapshots are never returned."""

    version: int = 1
    meta: dict[str, Any]
    desired: str
    controllers: dict[str, dict[str, Any]]
    reports: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ProfilingDiscoveryResponse(BaseModel):
    owner_id: str
    allowed: bool
    ready_owners: list[str]
    levels: list[str]
    local: dict[str, Any] | None
    coordination_error: str | None = None


def _control(request: Request) -> ProfilingControl:
    require_admin(request)
    service = getattr(request.app.state, "profiling_control", None)
    if service is None:
        raise api_exception(503, "profiling_unavailable", "Profiling service unavailable")
    return cast(ProfilingControl, service)


async def _result(operation: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await operation
    except RedisUnavailableError:
        raise api_exception(
            503, "profiling_unavailable", "Retry with the same capture ID"
        ) from None
    except ProfilingConflict as exc:
        raise api_exception(409, "profiling_conflict", str(exc)) from None
    except PermissionError:
        raise api_exception(403, "profiling_disabled", "Profiling disabled by deployment") from None
    except KeyError:
        raise api_exception(404, "profiling_not_found", "Capture expired or not found") from None
    except ValueError:
        raise api_exception(
            422, "profiling_invalid_target", "Select currently ready owners"
        ) from None


@router.get("", response_model=ProfilingDiscoveryResponse)
async def discover_profiling(request: Request) -> Any:
    return await _result(_control(request).discover())


@router.post("/captures", response_model=ProfilingResponse, status_code=202)
async def start_profiling(request: Request, body: StartProfilingRequest) -> Any:
    return await _result(_control(request).admit(str(body.capture_id), body.options, body.targets))


@router.get("/captures/{capture_id}", response_model=ProfilingResponse)
async def profiling_status(request: Request, capture_id: UUID) -> Any:
    result = await _result(_control(request).read(str(capture_id)))
    result["reports"] = {}
    return result


@router.get("/captures/{capture_id}/report", response_model=ProfilingResponse)
async def profiling_report(request: Request, capture_id: UUID) -> Any:
    return await _result(_control(request).read(str(capture_id)))


@router.post("/captures/{capture_id}/stop", response_model=ProfilingResponse, status_code=202)
async def stop_profiling(request: Request, capture_id: UUID) -> Any:
    return await _result(_control(request).request_stop(str(capture_id)))
