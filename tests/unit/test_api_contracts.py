"""Contract tests for API response models.

Stage 20+ refactors occasionally drifted the shape between the DB
producers and the API response models (e.g. ``StepRunResponse.todos``
was typed ``dict`` while every producer wrote ``list[dict]``).

These tests pin the canonical shapes so future changes either update the
tests or immediately fail in CI.
"""

from __future__ import annotations

import json
import types

import pytest
from pydantic import ValidationError

from cognis.api.chat_v2.schemas import (
    BackgroundToolCallV2Response,
    ErrorTimelineItem,
    HandoffTimelineItem,
    MessageTimelineItem,
    RecapArtifact,
    RetryProviderOptionsResponse,
)
from cognis.api.models import (
    AgentGrantResponse,
    AgentResponse,
    BackgroundCommandDetailResponse,
    CreateScheduleRequest,
    CursorPage,
    DeliverableResponse,
    EffectiveToolItemResponse,
    ExecutorTokenResponse,
    HandoffLinkRequest,
    HandoffLinkResponse,
    ModelRoutingEntry,
    ModelRoutingResponse,
    NavigationSummaryResponse,
    OnboardingStateResponse,
    PendingPauseResponse,
    ProjectTaskSummaryResponse,
    ProviderMonitorResponse,
    ScheduleResponse,
    SkillResponse,
    SkillVersionResponse,
    StepProfileResponse,
    StepResponseRequest,
    StepRunResponse,
    TaskCreateRequest,
    TaskRerunResponse,
    TaskResponse,
    TaskUpdateRequest,
    ToolClassificationActionResponse,
    ToolClassificationOverrideRequest,
    ToolClassificationRequeueRequest,
    ToolResponse,
    UpdateScheduleRequest,
    UserPreferencesResponse,
    UserPreferencesUpdateRequest,
    WaitingConversationPage,
    WebSocketExecutorMonitorUpdate,
    WorkflowResponse,
)
from cognis.api.routes.profiling import ProfilingResponse, StartProfilingRequest
from cognis.api.routes.push import PushSubscriptionStatusResponse
from cognis.api.serializers import llm_provider_to_response, step_run_to_response
from cognis.core.library import (
    LibraryFilters,
    LibraryGroup,
    LibraryGroupsPage,
    LibraryItem,
    LibraryPage,
)
from cognis.models.search import (
    ConversationFlatSearchMatch,
    ConversationFlatSearchResponse,
    ConversationSearchMatch,
    ConversationSearchResponse,
    SearchMatch,
    SearchSessionMatch,
)
from cognis.models.task import TaskDelivery


def test_handoff_progress_and_recipient_link_contracts() -> None:
    legacy = HandoffTimelineItem(
        id="handoff:session:8",
        sort_key="0001",
        source_refs=[],
        text="Verified brief.",
        source_session_id="session",
        source_seq=7,
    )
    assert legacy.status == "complete"
    assert legacy.recipient_conversation_id is None
    assert legacy.model_copy(update={"status": "running"}).model_dump()["status"] == "running"
    assert (
        HandoffLinkRequest(
            source_session_id="session",
            source_event_seq=8,
            recipient_conversation_id="recipient",
        ).source_event_seq
        == 8
    )
    assert HandoffLinkResponse(ok=True).model_dump() == {"ok": True}


def test_profiling_contract_preserves_per_controller_state_and_report() -> None:
    from uuid import uuid4

    capture_id = str(uuid4())
    request = StartProfilingRequest.model_validate(
        {"capture_id": capture_id, "options": {"level": "full", "duration_seconds": 600}}
    )
    assert str(request.capture_id) == capture_id
    assert request.targets is None
    response = ProfilingResponse.model_validate(
        {
            "meta": {"capture_id": capture_id},
            "desired": "stop",
            "controllers": {"controller:incarnation": {"state": "stopping", "owned_tracing": True}},
            "reports": {},
        }
    )
    assert response.model_dump()["controllers"]["controller:incarnation"]["state"] == "stopping"
    with pytest.raises(ValidationError):
        StartProfilingRequest.model_validate(
            {
                "capture_id": capture_id,
                "options": {"level": "full", "include_locals": True},
            }
        )


@pytest.mark.parametrize("family", ["porcelain", "classic", "gruvbox", "paper"])
@pytest.mark.parametrize("mode", ["light", "dark", "system"])
def test_user_theme_family_contract(family: str, mode: str) -> None:
    payload = UserPreferencesUpdateRequest.model_validate(
        {"display": {"theme_family": family, "theme": mode}}
    )
    response = UserPreferencesResponse.model_validate(payload.model_dump(mode="json"))
    assert response.display.theme_family == family
    assert response.display.theme == mode


def test_user_theme_family_defaults_and_strict_updates() -> None:
    preferences = UserPreferencesResponse.model_validate({"display": {"theme": "dark"}})
    assert preferences.display.theme_family == "classic"
    assert preferences.display.theme == "dark"
    for family in ["future-family", None, 1, {}]:
        with pytest.raises(ValidationError):
            UserPreferencesUpdateRequest.model_validate({"display": {"theme_family": family}})


def test_chat_v2_error_turn_identity_contract() -> None:
    item = ErrorTimelineItem(
        id="error:turn-contract",
        sort_key="0001",
        source_refs=[],
        title="Turn failed",
        turn_id="turn-contract",
    )
    assert item.model_dump()["turn_id"] == "turn-contract"
    assert ErrorTimelineItem.model_validate(item.model_dump()).turn_id == "turn-contract"
    assert (
        ErrorTimelineItem.model_validate(
            {key: value for key, value in item.model_dump().items() if key != "turn_id"}
        ).turn_id
        is None
    )


def test_onboarding_state_response_contract() -> None:
    assert OnboardingStateResponse().model_dump() == {"status": "pending"}
    for status in ("completed", "dismissed"):
        assert OnboardingStateResponse.model_validate({"status": status}).status == status


def test_executor_monitor_update_contract() -> None:
    frame = WebSocketExecutorMonitorUpdate(
        executor_id="host-linux",
        details_revision=None,
        status="active",
        runtime_state="active",
        desired_config_version=2,
        applied_config_version=2,
        last_observed_at=None,
        resource_snapshot=None,
    )
    assert frame.model_dump(mode="json") == {
        "type": "executor_monitor_update",
        "executor_id": "host-linux",
        "details_revision": None,
        "status": "active",
        "runtime_state": "active",
        "desired_config_version": 2,
        "applied_config_version": 2,
        "last_observed_at": None,
        "resource_snapshot": None,
    }


def test_waiting_conversation_page_contract() -> None:
    response = WaitingConversationPage.model_validate(
        {
            "conversations": {"items": [], "cursor": None, "has_more": False},
            "active_conversation_ids": ["conversation-running"],
        }
    )
    assert response.model_dump() == {
        "conversations": {"items": [], "cursor": None, "has_more": False},
        "active_conversation_ids": ["conversation-running"],
        "activity_complete": True,
    }
    assert (
        WaitingConversationPage.model_validate(
            {**response.model_dump(), "activity_complete": False}
        ).activity_complete
        is False
    )
    with pytest.raises(ValidationError):
        WaitingConversationPage.model_validate(
            {
                "conversations": {"items": [], "cursor": None, "has_more": False},
                "active_conversation_ids": [False],
            }
        )


def test_navigation_summary_contract() -> None:
    model = NavigationSummaryResponse.model_validate(
        {
            "chat_groups": [
                {
                    "count": 3,
                    "has_unread": True,
                    "session_observed": False,
                    "pending_notification_types": ["gate"],
                }
            ],
            "dashboard": {"total": 2, "critical": 1, "warning": 1, "info": 0},
            "schedules": 1,
            "tasks": 4,
        }
    )
    assert model.model_dump()["chat_groups"][0]["active_session_status"] is None
    with pytest.raises(ValidationError):
        NavigationSummaryResponse.model_validate(
            {
                **model.model_dump(),
                "tasks": -1,
            }
        )


def test_background_command_detail_contract() -> None:
    response = BackgroundCommandDetailResponse.model_validate(
        {
            "shell_id": "shell-preview",
            "executor_id": "exec-a",
            "command": "npm run dev",
            "status": "completed",
            "exit_code": 0,
            "output_tail": "Ready",
            "user_email": "user@example.com",
            "turn_id": "turn-private",
        }
    )
    assert response.exit_code == 0
    assert response.output_tail == "Ready"
    assert response.session_id is None
    assert "user_email" not in response.model_dump()
    assert "turn_id" not in response.model_dump()


def test_message_text_streaming_is_independent_of_partial_content() -> None:
    message = MessageTimelineItem(
        id="message:turn-a:phase:0",
        message_id="turn-a",
        sort_key="0",
        role="assistant",
        content="Commentary",
        stable=False,
        status="running",
        partial=True,
        text_streaming=False,
    )
    payload = message.model_dump()
    assert payload["text_streaming"] is False
    assert payload["partial"] is True
    assert MessageTimelineItem.model_validate(payload).text_streaming is False
    del payload["text_streaming"]
    assert MessageTimelineItem.model_validate(payload).text_streaming is None


def test_retry_provider_options_response_matches_ui_contract() -> None:
    assert RetryProviderOptionsResponse().model_dump() == {
        "turn_id": None,
        "provider_id": None,
        "model": None,
        "options": [],
    }
    response = RetryProviderOptionsResponse(
        turn_id="turn-1",
        provider_id="anthropic",
        model="claude-sonnet-4",
        options=[{"provider_id": "backup", "display_name": "Backup", "model": "claude-sonnet-4"}],
    )
    assert response.model_dump()["options"][0] == {
        "provider_id": "backup",
        "display_name": "Backup",
        "model": "claude-sonnet-4",
    }


def test_project_task_page_preserves_readable_card_metadata_without_runtime() -> None:
    page = CursorPage[ProjectTaskSummaryResponse].model_validate(
        {
            "items": [
                {
                    "task_id": "task_project_card",
                    "status": "completed",
                    "created_by": "owner@test.cz",
                    "is_readonly_for_caller": True,
                    "visibility": "project",
                    "priority": 3,
                    "source_type": "schedule",
                    "result_summary": "Ready for review",
                }
            ],
            "cursor": None,
            "has_more": False,
        }
    )
    item = page.model_dump(mode="json")["items"][0]
    assert item["result_summary"] == "Ready for review"
    assert item["priority"] == 3
    assert item["is_readonly_for_caller"] is True
    assert "attention_actions" not in item
    assert "progress_summary" not in item


def test_provider_monitor_contract_includes_freshness_policy_and_usage() -> None:
    response = ProviderMonitorResponse(
        provider_id="claude",
        display_name="Claude",
        monitoring={},
        usage={
            "provider_id": "claude",
            "source": "anthropic_subscription_usage",
            "primary": {"used_percent": 85},
        },
        alert_severity="warning",
    )
    payload = response.model_dump(mode="json")
    assert payload["monitoring"] == {
        "enabled": True,
        "interval_minutes": 15,
        "warning_percent": 20,
        "critical_percent": 0,
    }
    assert payload["usage"]["primary"]["used_percent"] == 85
    assert {
        "checked_at",
        "health_checked_at",
        "next_refresh_at",
        "stale",
        "error",
    } <= payload.keys()


def test_recap_artifact_size_contract_matches_numeric_ui_field() -> None:
    artifact = RecapArtifact(id="art-1", title="image.png", mime_type="image/png", size_bytes=73269)
    assert artifact.model_dump()["size_bytes"] == 73269
    with pytest.raises(ValidationError):
        RecapArtifact(id="art-1", title="image.png", mime_type="image/png", size_bytes="73269")


def test_task_requests_normalize_empty_optional_ids() -> None:
    create = TaskCreateRequest(
        agent_id="agent-1",
        title="Task",
        workflow_id="",
        project_id=" ",
        skill_id="",
    )
    update = TaskUpdateRequest(agent_id="", workflow_id="", project_id="", skill_id="")

    assert create.workflow_id is None
    assert create.project_id is None
    assert create.skill_id is None
    assert update.agent_id is None
    assert update.workflow_id is None
    assert update.project_id is None
    assert update.skill_id is None


def test_task_delivery_defaults_to_preferred_channel() -> None:
    assert TaskCreateRequest(agent_id="agent-1", title="Task").delivery_mode == "preferred_channel"
    assert TaskDelivery().mode == "preferred_channel"


class _FakeRow(types.SimpleNamespace):
    """Flexible stand-in for a SQLAlchemy ORM row in serializer tests."""


def _step_run_row(**overrides: object) -> _FakeRow:
    defaults = {
        "step_run_id": "sr-1",
        "task_id": "task-1",
        "step_name": "execute",
        "step_type": "run",
        "status": "completed",
        "attempt": 1,
        "agent_id": "agent-1",
        "workspace_root": None,
        "working_directory": None,
        "conversation_id": None,
        "session_id": None,
        "intaris_session_id": None,
        "output": None,
        "evaluation": None,
        "runtime_info": None,
        "todos": None,
        "started_at": None,
        "completed_at": None,
        "updated_at": None,
    }
    defaults.update(overrides)
    return _FakeRow(**defaults)


class TestStepRunTodosContract:
    """StepRunResponse.todos must always be list[dict]."""

    def test_empty_list_round_trip(self) -> None:
        response = step_run_to_response(_step_run_row(todos=[]))
        assert response.todos == []

    def test_populated_list_round_trip(self) -> None:
        payload = [
            {"content": "Ship release", "status": "in_progress"},
            {"content": "Write changelog", "status": "pending"},
        ]
        response = step_run_to_response(_step_run_row(todos=payload))
        assert response.todos == payload

    def test_none_is_normalized_to_empty_list(self) -> None:
        response = step_run_to_response(_step_run_row(todos=None))
        assert response.todos == []

    def test_unexpected_dict_is_coerced_to_empty_list(self) -> None:
        # Historical shape drift — StepRunResponse must not raise when a
        # legacy row stored a dict under ``todos``.
        response = step_run_to_response(_step_run_row(todos={"stray": "value"}))
        assert response.todos == []

    def test_non_dict_items_are_filtered(self) -> None:
        response = step_run_to_response(_step_run_row(todos=[{"ok": True}, "garbage"]))
        assert response.todos == [{"ok": True}]

    def test_runtime_info_round_trip(self) -> None:
        payload = {"executor_id": "exec-1", "environment": {"home": "/home/alice"}}
        response = step_run_to_response(_step_run_row(runtime_info=payload))
        assert response.runtime_info == payload

    def test_response_rejects_non_list_when_constructed_directly(self) -> None:
        with pytest.raises(ValidationError):
            StepRunResponse(
                step_run_id="sr",
                task_id="task",
                step_name="s",
                step_type="run",
                status="running",
                agent_id="agent",
                todos={"wrong": "shape"},  # type: ignore[arg-type]
            )


def test_deliverable_response_round_trip() -> None:
    response = DeliverableResponse(
        deliverable_id="dlv-1",
        step_run_id="sr-1",
        version=2,
        content="# Result",
        format="markdown",
        title="Implementation summary",
        target="channel",
        outputs={"tests": "passed"},
        status="approved",
    )

    assert response.outputs == {"tests": "passed"}
    assert response.status == "approved"


def test_executor_token_response_allows_non_expiring_tokens() -> None:
    response = ExecutorTokenResponse(executor_id="exec-1", token="jwt", expires_in=None)

    assert response.expires_in is None


def test_search_responses_round_trip_current_intaris_shape() -> None:
    match = SearchMatch(
        session_id="intaris-1",
        kind="reasoning",
        ref_id="audit-1",
        snippet="matched <mark>reasoning</mark>",
        score=0.9,
    )
    session_match = SearchSessionMatch(
        session_id="intaris-1",
        match_count=1,
        top_match=match,
    )
    conversation_match = ConversationSearchMatch(
        conversation_id="conv-1",
        agent_id="agent-1",
        status="active",
        session_id="sess-1",
        intaris_session_id="intaris-1",
        match_count=session_match.match_count,
        top_match=session_match.top_match,
        extra_matches=[
            SearchMatch(
                session_id="intaris-1",
                kind="intention",
                ref_id="audit-2",
                snippet="related <mark>intention</mark>",
                score=0.7,
            )
        ],
        kind_rank=0,
    )
    flat_match = ConversationFlatSearchMatch(
        conversation_id="conv-1",
        agent_id="agent-1",
        status="active",
        session_id="sess-1",
        intaris_session_id="intaris-1",
        match=match,
        kind_rank=0,
    )

    assert (
        ConversationSearchResponse(matches=[conversation_match]).matches[0].top_match.ref_id
        == "audit-1"
    )
    assert (
        ConversationSearchResponse(matches=[conversation_match]).matches[0].extra_matches[0].ref_id
        == "audit-2"
    )
    assert ConversationFlatSearchResponse(matches=[flat_match]).matches[0].match.kind == "reasoning"


def test_push_subscription_status_response_round_trip() -> None:
    response = PushSubscriptionStatusResponse(
        configured=True,
        enabled_subscriptions=1,
        last_error="push endpoint rejected request",
    )

    assert response.configured is True
    assert response.enabled_subscriptions == 1
    assert response.last_error == "push endpoint rejected request"


def test_agent_response_round_trips_sharing_fields() -> None:
    response = AgentResponse(
        agent_id="agent-1",
        owner_email="owner@example.com",
        name="Shared Agent",
        status="active",
        is_shared_with_me=True,
        shared_by_email="owner@example.com",
        granted_permission="use",
        executor_scope="owner_executor",
        is_readonly_for_caller=True,
        agent_profiles={
            "fast": {
                "profile_id": "fast",
                "description": "Low latency",
                "provider_id": "openai",
                "model": "gpt-fast",
                "reasoning_effort": "low",
                "system_prompt_extra": "Be concise.",
            }
        },
        default_agent_profile_id="fast",
    )

    assert response.is_shared_with_me is True
    assert response.shared_by_email == "owner@example.com"
    assert response.executor_scope == "owner_executor"
    assert response.agent_profiles["fast"]["model"] == "gpt-fast"
    assert response.default_agent_profile_id == "fast"


def test_agent_grant_response_round_trip() -> None:
    response = AgentGrantResponse(
        grant_id="grant-1",
        agent_id="agent-1",
        grantee_type="user",
        grantee_user_email="guest@example.com",
        permission="use",
        executor_scope="grantee_executor",
        granted_by="owner@example.com",
    )

    assert response.grantee_user_email == "guest@example.com"
    assert response.executor_scope == "grantee_executor"


class TestPendingPauseShapeContract:
    """PendingPauseResponse must accept first-class question sets only."""

    def test_questions_as_canonical_shape(self) -> None:
        response = PendingPauseResponse(
            pause_id="p-1",
            pause_type="step_input",
            questions=[
                {
                    "id": "q1",
                    "question": "Choose",
                    "options": [{"id": "approve", "label": "Approve"}],
                }
            ],
        )
        assert response.questions is not None
        assert response.questions[0].id == "q1"
        assert response.questions[0].options[0].id == "approve"

    def test_questions_none_is_allowed_for_non_question_pauses(self) -> None:
        response = PendingPauseResponse(pause_id="p-1", pause_type="step_input")
        assert response.questions is None

    def test_singular_question_is_not_canonical(self) -> None:
        with pytest.raises(ValidationError):
            PendingPauseResponse(
                pause_id="p-1",
                pause_type="step_input",
                question="Legacy?",
            )

    def test_step_response_requires_structured_answers(self) -> None:
        request = StepResponseRequest(
            answers=[{"question_id": "q1", "selected_option_ids": ["yes"]}],
            mode="structured",
        )
        assert request.answers[0].question_id == "q1"


class TestSkillResponseContracts:
    def test_skill_version_accepts_asset_manifest_entries(self) -> None:
        response = SkillVersionResponse(
            version_id="sv-1",
            skill_id="skill-1",
            version_number=1,
            content_hash="a" * 64,
            instructions="hello",
            asset_manifest=[
                {
                    "filename": "scripts/tool.py",
                    "asset_id": "sa-1",
                    "artifact_namespace": "skills",
                    "artifact_object_id": "ska-1",
                    "content_hash": "b" * 64,
                    "size_bytes": 10,
                    "content_type": "text/x-python",
                    "url": "https://example.test/tool.py",
                }
            ],
        )
        assert response.asset_manifest is not None
        assert response.asset_manifest[0].artifact_object_id == "ska-1"

    def test_skill_response_round_trips_current_version_shape(self) -> None:
        response = SkillResponse(
            skill_id="skill-1",
            name="Skill One",
            instructions="hello",
            attach_to_all_agents=False,
            current_version=SkillVersionResponse(
                version_id="sv-1",
                skill_id="skill-1",
                version_number=1,
                content_hash="a" * 64,
                instructions="hello",
            ),
        )
        assert response.current_version is not None
        assert response.current_version.version_id == "sv-1"

    def test_skill_version_round_trips_decomposition_fields(self) -> None:
        response = SkillVersionResponse(
            version_id="sv-1",
            skill_id="skill-1",
            version_number=2,
            content_hash="a" * 64,
            instructions="hello",
            steps=[{"name": "plan", "type": "run", "prompt": "Plan it"}],
            decomposition_source_hash="b" * 64,
            decomposition_stale=True,
        )

        assert response.steps is not None
        assert response.steps[0]["name"] == "plan"
        assert response.decomposition_stale is True


class TestTaskResponseRoundTrip:
    """TaskResponse round trip preserves delivery default and status."""

    def test_defaults(self) -> None:
        response = TaskResponse(
            task_id="task-1",
            title="Task",
            status="running",
            created_by="user@example.com",
            agent_id="agent-1",
            source_type="api",
        )
        assert response.description == ""
        assert response.workflow_state is None
        assert response.completion_mode_family == "default"
        assert response.created_by_agent_id is None


class TestTaskCreateRequest:
    """TaskCreateRequest preserves optional creator-agent marker."""

    def test_created_by_agent_id_defaults_to_none(self) -> None:
        create = TaskCreateRequest(agent_id="agent-1", title="Task")
        assert create.created_by_agent_id is None

    def test_session_policy_accepts_string_clauses(self) -> None:
        create = TaskCreateRequest(
            agent_id="agent-1",
            title="Task",
            session_policy={
                "allow_policies": ["Session may pass AWS SSO"],
                "deny_policies": ["Session must not write through SSM"],
            },
        )

        assert create.session_policy.allow_policies == ["Session may pass AWS SSO"]
        assert create.session_policy.deny_policies == ["Session must not write through SSM"]


class TestScheduleRequests:
    """Schedule requests strip reserved task template fields."""

    def test_create_strips_task_creator_agent_marker(self) -> None:
        request = CreateScheduleRequest(
            name="Daily",
            agent_id="agent-1",
            schedule_type="interval",
            interval_seconds=60,
            task_template={"title": "Task", "created_by_agent_id": "agent-2"},
        )

        assert request.task_template == {"title": "Task"}

    def test_create_accepts_session_policy(self) -> None:
        request = CreateScheduleRequest(
            name="Daily",
            agent_id="agent-1",
            schedule_type="interval",
            interval_seconds=60,
            task_template={"title": "Task"},
            session_policy={"allow_policies": ["Session may pass AWS SSO"]},
        )

        assert request.session_policy.allow_policies == ["Session may pass AWS SSO"]

    def test_create_accepts_agent_profile_id(self) -> None:
        request = CreateScheduleRequest(
            name="Daily",
            agent_id="agent-1",
            agent_profile_id="fast",
            schedule_type="interval",
            interval_seconds=60,
        )

        assert request.agent_profile_id == "fast"

    def test_update_strips_task_creator_agent_marker(self) -> None:
        request = UpdateScheduleRequest(
            task_template={"title": "Task", "created_by_agent_id": "agent-2"}
        )

        assert request.task_template == {"title": "Task"}

    def test_update_accepts_null_agent_profile_id(self) -> None:
        request = UpdateScheduleRequest(agent_profile_id=None)

        assert "agent_profile_id" in request.model_fields_set
        assert request.agent_profile_id is None

    def test_response_includes_agent_profile_id(self) -> None:
        response = ScheduleResponse(
            schedule_id="sched-1",
            name="Daily",
            schedule_type="interval",
            interval_seconds=60,
            agent_id="agent-1",
            agent_profile_id="fast",
            created_by="owner@example.com",
        )

        assert response.agent_profile_id == "fast"


def test_task_rerun_response_round_trip() -> None:
    response = TaskRerunResponse(
        ok=True,
        source_task_id="task-old",
        task_id="task-new",
        status="queued",
        created_new=True,
    )

    assert response.source_task_id == "task-old"
    assert response.task_id == "task-new"
    assert response.created_new is True


def test_task_retry_reuses_action_response_without_new_task_identity() -> None:
    from cognis.api.models import TaskActionResponse

    response = TaskActionResponse(ok=True, task_id="task-recovery", status="running")
    assert TaskActionResponse.model_validate(response.model_dump()) == response
    assert response.model_dump() == {
        "ok": True,
        "task_id": "task-recovery",
        "status": "running",
    }


def test_workflow_response_round_trips_lifecycle_and_lineage() -> None:
    response = WorkflowResponse(
        workflow_id="wf-1",
        name="Workflow",
        lifecycle="ephemeral",
        lineage={"base_workflow_id": "system:software-development"},
    )

    assert response.lifecycle == "ephemeral"
    assert response.lineage == {"base_workflow_id": "system:software-development"}


def test_workflow_response_preserves_step_profile_shape() -> None:
    response = WorkflowResponse(
        workflow_id="wf-1",
        name="Workflow",
        steps=[
            {
                "name": "execute",
                "type": "run",
                "step_profile_id": "system:coding",
                "step_profile_mode": "hard",
                "step_profile": {
                    "matrix": {"filesystem": ["read", "write"]},
                    "tool_overrides": {"include": ["read"], "exclude": ["bash"]},
                    "allow_tool_search": False,
                },
            }
        ],
    )

    assert response.steps[0]["step_profile_id"] == "system:coding"
    assert response.steps[0]["step_profile_mode"] == "hard"
    assert response.steps[0]["step_profile"]["matrix"]["filesystem"] == ["read", "write"]


def test_tool_response_round_trips_classification_fields() -> None:
    response = ToolResponse(
        name="read",
        description="Read a file",
        category="filesystem",
        profile_group="filesystem",
        read_only=True,
        capabilities=["read"],
        classification_status="ready",
        classification_source="declared",
        classification_confidence=1.0,
    )

    assert response.capabilities == ["read"]
    assert response.profile_group == "filesystem"
    assert response.classification_status == "ready"
    assert response.classification_source == "declared"
    assert response.classification_confidence == 1.0


def test_effective_tool_item_round_trips_classification_fields() -> None:
    response = EffectiveToolItemResponse(
        tool_id="builtin:read",
        name="read",
        description="Read a file",
        category="filesystem",
        profile_group="filesystem",
        read_only=True,
        capabilities=["read"],
        classification_status="pending",
        classification_source="llm",
        classification_confidence=0.83,
        permission="allow",
    )

    assert response.capabilities == ["read"]
    assert response.profile_group == "filesystem"
    assert response.classification_status == "pending"
    assert response.classification_source == "llm"
    assert response.classification_confidence == pytest.approx(0.83)


def test_step_profile_response_round_trips_matrix_shape() -> None:
    response = StepProfileResponse(
        profile_id="system:coding",
        name="Coding",
        mode="soft",
        has_override=True,
        is_custom=False,
        config={
            "matrix": {"filesystem": ["read", "write"], "shell": ["write", "privileged"]},
            "allow_tool_search": True,
        },
    )

    assert response.profile_id == "system:coding"
    assert response.has_override is True
    assert response.is_custom is False
    assert response.config["matrix"]["filesystem"] == ["read", "write"]


def test_tool_classification_action_models_round_trip() -> None:
    requeue = ToolClassificationRequeueRequest(
        tool_id="mcp:github:search/issues", pending_only=False
    )
    override = ToolClassificationOverrideRequest(
        tool_id="mcp:github:search/issues",
        profile_group="development",
        capabilities=["read"],
    )
    response = ToolClassificationActionResponse(updated=1, status="queued")

    assert requeue.tool_id == "mcp:github:search/issues"
    assert override.profile_group == "development"
    assert override.capabilities == ["read"]
    assert response.updated == 1
    assert response.status == "queued"


class TestModelRoutingContracts:
    def test_model_routing_defaults_to_empty_route_entries(self) -> None:
        response = ModelRoutingResponse()

        assert response.default == ModelRoutingEntry(model=None, reasoning_effort=None)
        assert response.image_generation == ModelRoutingEntry(model=None, reasoning_effort=None)
        assert response.attachment_analysis == ModelRoutingEntry(model=None, reasoning_effort=None)

    def test_model_routing_preserves_nested_entry_shape(self) -> None:
        response = ModelRoutingResponse(
            default={"model": "gpt-5.4", "reasoning_effort": "xhigh"},
            speech_to_text={"model": "gpt-4o-transcribe", "reasoning_effort": None},
        )

        assert response.default.model == "gpt-5.4"
        assert response.default.reasoning_effort == "xhigh"
        assert response.speech_to_text.model == "gpt-4o-transcribe"


class TestLLMProviderSerializer:
    """Provider list enriches stored models with derived capability fields."""

    def _provider_row(self, **config_overrides: object) -> _FakeRow:
        config = {
            "preset": "openai",
            "default_model": "gpt-5.4",
            "models": [
                {
                    "model_id": "gpt-5.4",
                    "supports_reasoning": True,
                },
                {
                    "model_id": "gpt-4o-mini",
                    "supports_reasoning": False,
                },
            ],
            **config_overrides,
        }
        return _FakeRow(
            provider_id="openai",
            display_name="OpenAI",
            location="controller",
            backend="litellm",
            config=config,
            is_default=True,
            status="active",
            created_at=None,
            updated_at=None,
            last_test=None,
        )

    def test_reasoning_model_gets_reasoning_efforts_populated(self) -> None:
        response = llm_provider_to_response(self._provider_row())

        reasoning_model = next(m for m in response.models if m["model_id"] == "gpt-5.4")
        assert reasoning_model["reasoning_efforts"] == [
            "default",
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
        ]

    def test_non_reasoning_model_keeps_empty_reasoning_efforts(self) -> None:
        response = llm_provider_to_response(self._provider_row())

        standard_model = next(m for m in response.models if m["model_id"] == "gpt-4o-mini")
        assert standard_model.get("reasoning_efforts", []) == []

    def test_explicitly_configured_reasoning_efforts_are_preserved(self) -> None:
        response = llm_provider_to_response(
            self._provider_row(
                models=[
                    {
                        "model_id": "gpt-5.4",
                        "supports_reasoning": True,
                        "reasoning_efforts": ["default", "low", "high"],
                    }
                ]
            )
        )

        reasoning_model = next(m for m in response.models if m["model_id"] == "gpt-5.4")
        assert reasoning_model["reasoning_efforts"] == ["default", "low", "high"]


def test_background_tool_call_response_contract_is_strict() -> None:
    payload = BackgroundToolCallV2Response(
        conversation_id="conv-1",
        call_id="call-1",
        tool_name="bash",
        status="already_requested",
        server_time="2026-10-01T00:00:00Z",
    ).model_dump(mode="json")
    assert set(payload) == {"conversation_id", "call_id", "tool_name", "status", "server_time"}
    with pytest.raises(ValidationError):
        BackgroundToolCallV2Response.model_validate({**payload, "status": "moved"})
    with pytest.raises(ValidationError):
        BackgroundToolCallV2Response.model_validate({**payload, "shell_id": "shell_1"})


def test_upstream_request_error_body_contract() -> None:
    import httpx
    from openai import BadRequestError

    from cognis.api.routes.inference import upstream_failure

    exc = BadRequestError(
        "private upstream text",
        response=httpx.Response(400, request=httpx.Request("POST", "https://provider.test")),
        body={"error": {"code": "json_validate_failed", "message": "private upstream text"}},
    )
    response = upstream_failure(exc)
    assert response.status_code == 422
    assert json.loads(response.body) == {
        "error": {"code": "upstream_json_validate_failed", "category": "request"}
    }


@pytest.mark.parametrize("can_edit", [True, False, None])
def test_queued_edit_capability_survives_chat_projection(can_edit: bool | None) -> None:
    from cognis.api.chat_v2.schemas import QueueState
    from cognis.api.chat_v2.sync import queue_state_from_messages
    from cognis.api.models import QueuedMessagesResponse

    message: dict[str, object] = {"queue_id": "queue-1", "content": "queued", "position": 1}
    if can_edit is not None:
        message["can_edit"] = can_edit
    projected = queue_state_from_messages([message])
    restored = QueueState.model_validate_json(projected.model_dump_json())
    assert restored.messages[0].can_edit is bool(can_edit)
    rest_response = QueuedMessagesResponse(messages=[message], queued_count=1)
    restored_rest = QueuedMessagesResponse.model_validate_json(rest_response.model_dump_json())
    assert restored_rest.messages[0].can_edit is bool(can_edit)


def test_library_contracts() -> None:
    """List contracts retain origin, lineage and nullable detached provenance."""
    row = LibraryItem.model_validate(
        {
            "id": "art_contract_upload",
            "kind": "artifact",
            "title": "brief.pdf",
            "format": "application/pdf",
            "created_at": "2026-10-17T06:00:00Z",
            "updated_at": "2026-10-17T06:00:00Z",
            "status": "attached",
            "origin": "user",
        }
    )
    page = LibraryPage(items=[row]).model_dump(mode="json")
    assert page["items"][0]["origin"] == "user"
    assert page["items"][0]["conversation_id"] is None
    assert page["next_cursor"] is None
    assert (
        LibraryGroupsPage(groups=[LibraryGroup(id="", label="No project", count=1)]).groups[0].id
        == ""
    )
    with pytest.raises(ValidationError):
        LibraryFilters.model_validate({"origin": "upload"})


@pytest.mark.parametrize(
    "kind", ["agent", "project", "conversation", "task", "schedule", "deliverable", "artifact"]
)
def test_palette_navigation_projection_contract(kind: str) -> None:
    """Every search producer shares the compact, nullable navigation contract."""
    from cognis.core.palette import PalettePage

    page = PalettePage.model_validate(
        {
            "items": [
                {
                    "kind": kind,
                    "id": f"{kind}-palette-contract",
                    "title": "Command palette",
                    "project_id": None,
                    "agent_id": None,
                    "status": None,
                    "format": None,
                    "updated_at": "2026-10-23T12:00:00Z",
                    "href": "/",
                }
            ],
        }
    ).model_dump(mode="json")
    assert page["next_cursor"] is None
    assert page["items"][0]["size_bytes"] == 0
    assert set(page["items"][0]) == {
        "kind",
        "id",
        "title",
        "project_id",
        "agent_id",
        "agent_name",
        "agent_avatar_url",
        "project_avatar_url",
        "project_icon",
        "project_color",
        "origin",
        "producer_name",
        "status",
        "format",
        "updated_at",
        "href",
        "size_bytes",
    }
    assert "content" not in page["items"][0]
