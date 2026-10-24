"""Authenticated informational inbox endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from cognis.api.common import require_current_user
from cognis.core.inbox import InboxPage, InboxService

router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])


class InboxReadRequest(BaseModel):
    notification_ids: list[str] = Field(min_length=1, max_length=100)


@router.get("", response_model=InboxPage)
async def list_inbox(
    request: Request,
    cursor: str | None = None,
    unread: bool = False,
    limit: int = Query(default=30, ge=1, le=100),
) -> InboxPage:
    """List only the authenticated recipient's inbox."""
    user = require_current_user(request)
    service: InboxService = request.app.state.inbox_service
    try:
        return await service.list_page(user.email, cursor=cursor, unread=unread, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid inbox cursor") from exc


@router.post("/read", response_model=dict[str, bool])
async def read_inbox(request: Request, payload: InboxReadRequest) -> dict[str, bool]:
    """Acknowledgement is personal state, allowed even for read-only users."""
    user = require_current_user(request)
    await request.app.state.inbox_service.mark_read(user.email, payload.notification_ids)
    return {"ok": True}
