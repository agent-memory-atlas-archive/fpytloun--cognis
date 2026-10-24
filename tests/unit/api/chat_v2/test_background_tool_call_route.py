"""Chat v2 route that moves a running tool call to the background."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from cognis.api.app import create_app
from cognis.api.chat_v2 import routes as chat_v2_routes
from cognis.api.chat_v2.routes import chat_v2_background_tool_call
from cognis.api.chat_v2.schemas import BackgroundToolCallV2Response
from cognis.core.tool_backgrounding import (
    ToolBackgroundError,
    ToolBackgroundErrorCode,
    ToolBackgroundRequestResult,
)

_PATH = "/api/v1/chat/v2/conversations/{conversation_id}/tool-calls/{call_id}/background"


class _Service:
    def __init__(self, *, result: Any = None, error: ToolBackgroundError | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, str]] = []

    async def request_background(self, *, conversation_id: str, call_id: str) -> Any:
        self.calls.append({"conversation_id": conversation_id, "call_id": call_id})
        if self.error is not None:
            raise self.error
        return self.result


def _request(service: Any) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(tool_backgrounding=service)))


@pytest.fixture()
def authorized(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    checked: list[str] = []

    async def _require(_request: object, conversation_id: str) -> tuple[Any, Any]:
        checked.append(conversation_id)
        return SimpleNamespace(email="user@test.com"), SimpleNamespace(
            conversation_id=conversation_id
        )

    monkeypatch.setattr(chat_v2_routes, "_require_mutable_conversation", _require)
    return checked


def test_background_route_is_registered() -> None:
    routes = {
        (method, route.path)
        for route in create_app().routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert ("POST", _PATH) in routes


@pytest.mark.asyncio
@pytest.mark.parametrize(("already", "status"), [(False, "requested"), (True, "already_requested")])
async def test_background_route_authorizes_then_requests(
    authorized: list[str], already: bool, status: str
) -> None:
    service = _Service(
        result=ToolBackgroundRequestResult(
            call_id="call-1", tool_name="bash", executor_id="exec-a", already_requested=already
        )
    )

    response = await chat_v2_background_tool_call(cast(Any, _request(service)), "conv-1", "call-1")

    assert authorized == ["conv-1"]
    assert service.calls == [{"conversation_id": "conv-1", "call_id": "call-1"}]
    assert isinstance(response, BackgroundToolCallV2Response)
    assert response.status == status
    assert response.tool_name == "bash"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "http_status"),
    [
        (ToolBackgroundErrorCode.UNKNOWN_CALL, 404),
        (ToolBackgroundErrorCode.NO_ACTIVE_TURN, 409),
        (ToolBackgroundErrorCode.NOT_BACKGROUNDABLE, 409),
        (ToolBackgroundErrorCode.UNSUPPORTED_TOOL, 409),
        (ToolBackgroundErrorCode.EXECUTOR_UNSUPPORTED, 409),
        (ToolBackgroundErrorCode.EXECUTOR_UNAVAILABLE, 503),
    ],
)
async def test_background_route_maps_service_errors(
    authorized: list[str], code: ToolBackgroundErrorCode, http_status: int
) -> None:
    service = _Service(error=ToolBackgroundError(code))

    with pytest.raises(HTTPException) as error:
        await chat_v2_background_tool_call(cast(Any, _request(service)), "conv-1", "call-1")

    assert error.value.status_code == http_status
    assert code.value in str(error.value.detail)


@pytest.mark.asyncio
async def test_background_route_rejects_before_service_when_unauthorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _deny(_request: object, _conversation_id: str) -> tuple[Any, Any]:
        raise HTTPException(status_code=404, detail="Conversation not found")

    monkeypatch.setattr(chat_v2_routes, "_require_mutable_conversation", _deny)
    service = _Service()

    with pytest.raises(HTTPException):
        await chat_v2_background_tool_call(cast(Any, _request(service)), "conv-1", "call-1")

    assert service.calls == []
