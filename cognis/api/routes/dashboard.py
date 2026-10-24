"""Dashboard-specific lightweight API routes."""

from fastapi import APIRouter, Request

from cognis.api.common import api_exception, forbid_mutation_for_viewer, require_current_user
from cognis.api.dashboard_issues import collect_dashboard_issues
from cognis.api.models import (
    DashboardIssueDismissRequest,
    DashboardIssuesResponse,
    NavigationSummaryResponse,
)
from cognis.api.navigation_summary import collect_navigation_summary
from cognis.api.routes.conversations import (
    _active_background_shells,
    sidebar_active_conversation_ids,
)

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/navigation-summary", response_model=NavigationSummaryResponse)
async def navigation_summary(request: Request) -> NavigationSummaryResponse:
    user = require_current_user(request)
    background_shells = await _active_background_shells(request, user_email=user.email)
    async with request.app.state.session_factory() as session:

        async def resolve_active_ids(conversation_ids: list[str]) -> set[str]:
            return await sidebar_active_conversation_ids(
                request,
                session,
                user_email=user.email,
                conversation_ids=conversation_ids,
                background_shells=background_shells,
            )

        return await collect_navigation_summary(
            session, user_email=user.email, resolve_active_ids=resolve_active_ids
        )


@router.get("/issues", response_model=DashboardIssuesResponse)
async def dashboard_issues(request: Request) -> DashboardIssuesResponse:
    user = require_current_user(request)
    async with request.app.state.session_factory() as session:
        return await collect_dashboard_issues(session, user_email=user.email)


@router.post("/issues/schedules/{schedule_id}/dismiss", response_model=dict)
async def dismiss_schedule_issue(
    request: Request,
    schedule_id: str,
    payload: DashboardIssueDismissRequest,
) -> dict[str, bool]:
    forbid_mutation_for_viewer(request)
    user = require_current_user(request)
    result = await request.app.state.notification_service.dismiss_schedule_action(
        schedule_id,
        user_email=user.email,
        incident_token=payload.incident_token,
    )
    if result == "not_found":
        raise api_exception(404, "not_found", "Schedule issue not found")
    if result == "stale":
        raise api_exception(409, "stale_incident", "Schedule issue changed; refresh and try again")
    return {"ok": True}
