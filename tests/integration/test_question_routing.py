from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cognis.api.attention_actions import list_attention_rows_by_conversation
from cognis.api.routes.tasks import _task_board_item_response
from cognis.api.serializers import task_to_response
from cognis.core.agent_loop import PauseWaiter
from cognis.core.events import Event, EventBus, EventType
from cognis.core.followups import (
    QuestionFollowUp,
    build_follow_up_id,
    parse_follow_up_metadata,
    render_follow_up_block,
)
from cognis.core.management import task_pending_pause_response
from cognis.core.notifications import NotificationService
from cognis.core.questions import AGENT_QUESTION, QuestionOrigin, join_until_boundary
from cognis.models.task import TaskModel
from cognis.models.workflow import WorkflowState
from cognis.store.models import (
    Agent,
    Base,
    Conversation,
    FollowUpIntentRow,
    ManagedConversationLink,
    Task,
    User,
)
from cognis.store.models import Session as SessionRow
from cognis.store.queries import list_pending_notification_types_by_conversation

OWNER = "question-owner@example.com"


@pytest.fixture(params=["sqlite", "postgres"])
async def question_service(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[NotificationService, EventBus, Any]]:
    admin = None
    schema = None
    if request.param == "postgres":
        url = os.environ.get("COGNIS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("COGNIS_TEST_POSTGRES_URL is not configured")
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        schema = f"question_routing_{uuid.uuid4().hex}"
        admin = create_async_engine(url)
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(User(email=OWNER))
        await db.flush()
        db.add_all(
            [
                Agent(agent_id=aid, owner_email=OWNER, name=aid)
                for aid in ("parent-agent", "child-agent", "task-agent")
            ]
        )
        await db.flush()
        db.add_all(
            [
                Conversation(
                    conversation_id=cid,
                    user_email=OWNER,
                    agent_id="parent-agent",
                    context_type="web",
                )
                for cid in ("parent", "child", "task", "delivery", "other")
            ]
        )
        await db.flush()
        db.add_all(
            [
                SessionRow(
                    session_id="parent-session",
                    conversation_id="parent",
                    user_email=OWNER,
                    agent_id="parent-agent",
                ),
                SessionRow(
                    session_id="child-session",
                    conversation_id="child",
                    parent_session_id="parent-session",
                    user_email=OWNER,
                    agent_id="child-agent",
                ),
                SessionRow(
                    session_id="task-session",
                    conversation_id="task",
                    user_email=OWNER,
                    agent_id="task-agent",
                ),
            ]
        )
        await db.commit()
    bus = EventBus()
    service = NotificationService(factory, PauseWaiter(), bus, SimpleNamespace())
    try:
        yield service, bus, factory
    finally:
        if service._background_tasks:
            await asyncio.gather(*service._background_tasks)
        await engine.dispose()
        if admin is not None:
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()


def origin(*, task_id: str | None = None) -> QuestionOrigin:
    return QuestionOrigin(
        conversation_id="task" if task_id else "child",
        session_id="task-session" if task_id else "child-session",
        agent_id="task-agent" if task_id else "child-agent",
        tool_call_id="question-call",
        tool_name="step_request_questions",
        task_id=task_id,
        step_name="plan",
    )


async def ask(
    service: NotificationService,
    *,
    task_id: str | None = None,
    deliver: bool = True,
) -> Any:
    return await service.create_question(
        origin=origin(task_id=task_id),
        user_email=OWNER,
        notification_id="question-routing",
        deliver=deliver,
        payload={
            "origin_call_id": "question-call",
            "questions": [
                {
                    "id": "direction",
                    "question": "Which direction?",
                    "options": [{"id": "small", "label": "Small change"}],
                    "allow_custom": False,
                }
            ],
            "context": {"note": "Needs a decision"},
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        },
    )


@pytest.mark.asyncio
async def test_child_question_is_agent_only_with_full_origin(question_service: Any) -> None:
    service, bus, factory = question_service
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(EventType.FOLLOW_UP_TURN_REQUESTED, capture)
    bus.subscribe(EventType.NOTIFICATION_CREATED, capture)
    question = await ask(service)
    assert question.notification_type == AGENT_QUESTION
    assert question.conversation_id == "parent"
    assert len(events) == 1
    follow_up = parse_follow_up_metadata(events[0].data["follow_up"])
    assert isinstance(follow_up, QuestionFollowUp)
    assert follow_up.origin == origin()
    block = render_follow_up_block(follow_up)
    assert "question-call" in block and "child-agent" in block
    assert "user's preferences" in block and "rather than guess" in block
    assert await service.list_pending(OWNER) == []
    async with factory() as db:
        assert await list_pending_notification_types_by_conversation(db, OWNER, ["parent"]) == {}
        assert (
            await list_attention_rows_by_conversation(
                db, owner_email=OWNER, conversation_ids=["parent"]
            )
            == {}
        )
    assert not await service.resolve(question.notification_id, "continue", user_email=OWNER)


@pytest.mark.asyncio
async def test_answer_resumes_original_waiter_and_validates_authority(
    question_service: Any,
) -> None:
    service, _, _ = question_service
    question = await ask(service)
    waiting = asyncio.create_task(service.wait_for_resolution(question.notification_id, timeout=2))
    try:
        with pytest.raises(ValueError, match="assigned"):
            await service.answer_question(
                question.notification_id,
                user_email=OWNER,
                conversation_id="other",
                expected_revision=1,
                answers=[{"question_id": "direction", "selected_option_ids": ["small"]}],
            )
        with pytest.raises(ValueError, match="invalid option"):
            await service.answer_question(
                question.notification_id,
                user_email=OWNER,
                conversation_id="parent",
                expected_revision=1,
                answers=[{"question_id": "direction", "selected_option_ids": ["large"]}],
            )
        assert not await service.answer_question(
            question.notification_id,
            user_email=OWNER,
            conversation_id="parent",
            expected_revision=2,
            answers=[{"question_id": "direction", "selected_option_ids": ["small"]}],
        )
        assert await service.answer_question(
            question.notification_id,
            user_email=OWNER,
            conversation_id="parent",
            expected_revision=1,
            answers=[{"question_id": "direction", "selected_option_ids": ["small"]}],
        )
        resolution = await waiting
        assert resolution.data["answers"][0]["selected_option_ids"] == ["small"]
        assert resolution.data["answered_by"]["conversation_id"] == "parent"
        assert (
            await service.find_tool_question(
                session_id="child-session", tool_call_id="question-call"
            )
        ).status == "resolved"
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)


@pytest.mark.asyncio
async def test_forward_preserves_identity_expiry_and_waiter(question_service: Any) -> None:
    service, _, _ = question_service
    question = await ask(service)
    waiting = asyncio.create_task(service.wait_for_resolution(question.notification_id, timeout=2))
    await asyncio.sleep(0)
    assert await service.forward_question(
        question.notification_id,
        user_email=OWNER,
        conversation_id="parent",
        expected_revision=1,
    )
    forwarded = await service.get(question.notification_id)
    assert forwarded.notification_type == "step_question"
    assert forwarded.revision == 2
    assert forwarded.expires_at.replace(tzinfo=UTC) == question.expires_at
    assert forwarded.payload["questions"] == question.payload["questions"]
    assert forwarded.payload["question_origin"] == question.payload["question_origin"]
    assert service._pause_waiter.get(question.notification_id).pause_type == "step_question"
    assert not await service.forward_question(
        question.notification_id,
        user_email=OWNER,
        conversation_id="parent",
        expected_revision=1,
    )
    assert await service.resolve(
        question.notification_id,
        "continue",
        {
            "answers": [{"question_id": "direction", "selected_option_ids": ["small"]}],
            "mode": "structured",
        },
        user_email=OWNER,
    )
    assert (await waiting).decision == "continue"


@pytest.mark.asyncio
@pytest.mark.parametrize("source_type", ["agent", "scheduler", "api"])
async def test_task_question_routes_to_source_or_pinned_delivery(
    question_service: Any, source_type: str
) -> None:
    service, _, factory = question_service
    async with factory() as db:
        db.add(
            Task(
                task_id="task-question",
                title="Question task",
                created_by=OWNER,
                agent_id="task-agent",
                status="running",
                source_type=source_type,
                source_ref="parent" if source_type == "agent" else None,
                source_session_id="parent-session" if source_type == "agent" else None,
                delivery_mode="specific_conversation",
                delivery_target="delivery",
            )
        )
        await db.commit()
    question = await ask(service, task_id="task-question")
    assert question.conversation_id == ("parent" if source_type == "agent" else "delivery")
    assert question.payload["question_origin"]["task_title"] == "Question task"
    assert question.payload["question_origin"]["source_type"] == source_type
    assert question.payload["question_routing"]["user_conversation_id"] == "delivery"


@pytest.mark.asyncio
async def test_managed_question_routes_to_immediate_controller(question_service: Any) -> None:
    service, _, factory = question_service
    async with factory() as db:
        session = await db.get(SessionRow, "child-session")
        session.parent_session_id = None
        db.add(
            ManagedConversationLink(
                link_id="managed-question-link",
                user_email=OWNER,
                controller_agent_id="parent-agent",
                controller_conversation_id="parent",
                target_agent_id="child-agent",
                target_conversation_id="child",
            )
        )
        await db.commit()
    assert (await ask(service)).conversation_id == "parent"


@pytest.mark.asyncio
async def test_join_yields_for_question_without_cancelling_child(question_service: Any) -> None:
    service, bus, _ = question_service
    incoming = asyncio.Event()

    async def receive(event: Event) -> None:
        incoming.set()

    bus.subscribe(EventType.FOLLOW_UP_TURN_REQUESTED, receive)

    async def child() -> str:
        question = await ask(service)
        await service.wait_for_resolution(question.notification_id, timeout=2)
        return "child-completed"

    async def boundary(_: int | None) -> str:
        await incoming.wait()
        return "queued_question"

    running = asyncio.create_task(child())
    result, reason = await asyncio.wait_for(join_until_boundary(running, boundary, 0), timeout=1)
    assert result is None and reason == "queued_question"
    assert not running.done()
    await service.answer_question(
        "question-routing",
        user_email=OWNER,
        conversation_id="parent",
        expected_revision=1,
        answers=[{"question_id": "direction", "selected_option_ids": ["small"]}],
    )
    assert await running == "child-completed"


@pytest.mark.asyncio
async def test_join_parent_cancellation_cancels_child() -> None:
    child = asyncio.create_task(asyncio.Event().wait())

    async def boundary(_: int | None) -> str:
        await asyncio.Event().wait()
        return "queued_question"

    joined = asyncio.create_task(join_until_boundary(child, boundary, None))
    await asyncio.sleep(0)
    joined.cancel()
    with pytest.raises(asyncio.CancelledError):
        await joined
    assert child.cancelled()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["admitted", "submitted", "failed"])
async def test_recovery_preserves_active_mediation_and_forwards_terminal(
    question_service: Any,
    status: str,
) -> None:
    service, _, factory = question_service
    question = await ask(service)
    async with factory() as db:
        db.add(
            FollowUpIntentRow(
                intent_id="question-intent",
                conversation_id="parent",
                follow_up_id=build_follow_up_id(
                    kind="question",
                    conversation_id="parent",
                    parts={"question_id": question.notification_id},
                ),
                status=status,
                event_payload={},
            )
        )
        await db.commit()
    await service.recover_questions()
    recovered = await service.get(question.notification_id)
    assert recovered.notification_type == (
        AGENT_QUESTION if status == "admitted" else "step_question"
    )


@pytest.mark.asyncio
async def test_recovery_republishes_missed_question_delivery(question_service: Any) -> None:
    service, bus, _ = question_service
    question = await ask(service)
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(EventType.FOLLOW_UP_TURN_REQUESTED, capture)
    await service.recover_questions()
    assert events[0].data["follow_up"]["question_id"] == question.notification_id
    assert (await service.get(question.notification_id)).revision == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["cancelled", "failed", "completed"])
async def test_terminal_child_question_is_not_forwarded(
    question_service: Any, terminal: str
) -> None:
    service, _, factory = question_service
    question = await ask(service)
    async with factory() as db:
        session = await db.get(SessionRow, "child-session")
        session.status = terminal
        await db.commit()
    assert not await service.forward_question(
        question.notification_id,
        user_email=OWNER,
        conversation_id="parent",
        expected_revision=1,
    )
    assert not await service.answer_question(
        question.notification_id,
        user_email=OWNER,
        conversation_id="parent",
        expected_revision=1,
        answers=[{"question_id": "direction", "selected_option_ids": ["small"]}],
    )
    await service.recover_questions()
    recovered = await service.get(question.notification_id)
    assert recovered.status == "resolved"
    assert recovered.resolution["decision"] == "cancel"
    assert recovered.resolution["reason"] == "origin_execution_terminal"
    assert await service.list_pending(OWNER) == []


@pytest.mark.asyncio
async def test_task_attention_and_details_stay_hidden_until_forwarded(
    question_service: Any,
) -> None:
    service, _, factory = question_service
    state = WorkflowState(
        status="paused",
        pending_pause_type=AGENT_QUESTION,
        pending_pause_payload={
            "pause_id": "question-routing",
            "questions": [{"id": "direction", "question": "Which?"}],
        },
    )
    async with factory() as db:
        db.add(
            Task(
                task_id="task-question",
                title="Question task",
                created_by=OWNER,
                agent_id="task-agent",
                status="paused",
                source_type="agent",
                source_ref="parent",
                delivery_mode="specific_conversation",
                delivery_target="delivery",
                workflow_state=state.model_dump(mode="json"),
            )
        )
        await db.commit()
        row = await db.get(Task, "task-question")
        assert _task_board_item_response(row).attention_type is None
    question = await ask(service, task_id="task-question")
    task = TaskModel(
        task_id="task-question",
        title="Question task",
        created_by=OWNER,
        agent_id="task-agent",
        status="paused",
        workflow_state=state,
    )
    assert task_pending_pause_response(service._pause_waiter, task) is None
    assert task_to_response(task).workflow_state.pending_pause_payload is None
    assert task_pending_pause_response(PauseWaiter(), task) is None
    assert await service.forward_question(
        question.notification_id,
        user_email=OWNER,
        conversation_id="parent",
        expected_revision=1,
    )
    async with factory() as db:
        row = await db.get(Task, "task-question")
        assert _task_board_item_response(row).attention_type == "step_input"
        task.workflow_state = WorkflowState.model_validate(row.workflow_state)
        assert task_pending_pause_response(PauseWaiter(), task).pause_type == "step_input"
    assert task_pending_pause_response(service._pause_waiter, task).pause_type == "step_question"


@pytest.mark.asyncio
async def test_answer_and_forward_have_one_winner_across_controllers(
    question_service: Any,
    request: pytest.FixtureRequest,
) -> None:
    if request.node.callspec.params.get("question_service") != "postgres":
        pytest.skip("Concurrent writers use isolated PostgreSQL connections")
    service, _, factory = question_service
    question = await ask(service)
    other = NotificationService(factory, PauseWaiter(), EventBus(), SimpleNamespace())

    async def answer() -> bool:
        try:
            return await other.answer_question(
                question.notification_id,
                user_email=OWNER,
                conversation_id="parent",
                expected_revision=1,
                answers=[{"question_id": "direction", "selected_option_ids": ["small"]}],
            )
        except ValueError:
            return False

    answered, forwarded = await asyncio.gather(
        answer(),
        service.forward_question(
            question.notification_id,
            user_email=OWNER,
            conversation_id="parent",
            expected_revision=1,
        ),
    )
    assert answered != forwarded
    stored = await service.get(question.notification_id)
    assert (stored.status == "resolved") == answered
    assert (stored.notification_type == "step_question") == forwarded
    if other._background_tasks:
        await asyncio.gather(*other._background_tasks)


@pytest.mark.asyncio
async def test_answered_task_recovers_admission_without_a_local_waiter(
    question_service: Any,
) -> None:
    service, _, factory = question_service
    async with factory() as db:
        db.add(
            Task(
                task_id="task-question",
                title="Question task",
                created_by=OWNER,
                agent_id="task-agent",
                status="paused",
                source_type="agent",
                source_ref="parent",
                delivery_mode="specific_conversation",
                delivery_target="delivery",
                workflow_state=WorkflowState(
                    status="paused",
                    pending_pause_type=AGENT_QUESTION,
                    pending_pause_payload={"pause_id": "question-routing"},
                ).model_dump(mode="json"),
            )
        )
        await db.commit()
    question = await ask(service, task_id="task-question")
    assert await service.answer_question(
        question.notification_id,
        user_email=OWNER,
        conversation_id="parent",
        expected_revision=1,
        answers=[{"question_id": "direction", "selected_option_ids": ["small"]}],
    )
    attempts: list[str] = []

    async def resume(task_id: str) -> TaskModel:
        attempts.append(task_id)
        if len(attempts) == 1:
            raise ValueError("No execution capacity available to resume the task")
        async with factory() as db:
            task = await db.get(Task, task_id)
            state = WorkflowState.model_validate(task.workflow_state)
            assert state.pending_pause_type == "step_input"
            assert state.pending_pause_payload["answers"][0]["selected_option_ids"] == ["small"]
            task.status = "running"
            await db.commit()
        return TaskModel(
            task_id=task_id,
            title="Question task",
            created_by=OWNER,
            agent_id="task-agent",
            status="running",
        )

    recovered = NotificationService(
        factory,
        PauseWaiter(),
        EventBus(),
        SimpleNamespace(),
        task_queue=SimpleNamespace(has_active_run=lambda _: False, resume_task=resume),
    )
    await recovered.recover_questions()
    await recovered.recover_questions()
    await recovered.recover_questions()
    assert attempts == ["task-question", "task-question"]


@pytest.mark.asyncio
async def test_task_attempt_revision_fences_old_question(question_service: Any) -> None:
    service, _, factory = question_service
    async with factory() as db:
        db.add(
            Task(
                task_id="task-question",
                title="Question task",
                created_by=OWNER,
                agent_id="task-agent",
                status="paused",
                source_type="agent",
                source_ref="parent",
                delivery_mode="specific_conversation",
                delivery_target="delivery",
            )
        )
        await db.commit()
    question = await ask(service, task_id="task-question")
    assert question.payload["question_origin"]["task_attempt_number"] == 1
    async with factory() as db:
        task = await db.get(Task, "task-question")
        task.attempt_number = 2
        await db.commit()
    assert not await service.answer_question(
        question.notification_id,
        user_email=OWNER,
        conversation_id="parent",
        expected_revision=1,
        answers=[{"question_id": "direction", "selected_option_ids": ["small"]}],
    )
    assert not await service.forward_question(
        question.notification_id,
        user_email=OWNER,
        conversation_id="parent",
        expected_revision=1,
    )
    await service.recover_questions()
    assert (await service.get(question.notification_id)).resolution[
        "reason"
    ] == "origin_execution_terminal"


@pytest.mark.asyncio
async def test_recovery_cannot_deliver_before_pause_commit(question_service: Any) -> None:
    service, _, factory = question_service
    async with factory() as db:
        db.add(
            Task(
                task_id="task-question",
                title="Question task",
                created_by=OWNER,
                agent_id="task-agent",
                status="running",
                source_type="agent",
                source_ref="parent",
                delivery_mode="specific_conversation",
                delivery_target="delivery",
            )
        )
        await db.commit()
    question = await ask(service, task_id="task-question", deliver=False)
    bus = EventBus()
    other = NotificationService(factory, PauseWaiter(), bus, SimpleNamespace())
    events: list[Event] = []

    async def forward_on_delivery(event: Event) -> None:
        events.append(event)
        assert await other.forward_question(
            question.notification_id,
            user_email=OWNER,
            conversation_id="parent",
            expected_revision=1,
        )

    bus.subscribe(EventType.FOLLOW_UP_TURN_REQUESTED, forward_on_delivery)
    # Interleave another controller between question creation and task-pause commit.
    await other.recover_questions()
    await other.deliver_question(question)
    assert events == []
    assert not await other.forward_question(
        question.notification_id,
        user_email=OWNER,
        conversation_id="parent",
        expected_revision=1,
    )
    assert not await other.answer_question(
        question.notification_id,
        user_email=OWNER,
        conversation_id="parent",
        expected_revision=1,
        answers=[{"question_id": "direction", "selected_option_ids": ["small"]}],
    )
    # Simulate origin committing its pause, then crashing before explicit activation.
    async with factory() as db:
        task = await db.get(Task, "task-question")
        task.status = "paused"
        task.workflow_state = WorkflowState(
            status="paused",
            pending_pause_type=AGENT_QUESTION,
            pending_pause_payload={"pause_id": question.notification_id},
        ).model_dump(mode="json")
        await db.commit()
    await other.recover_questions()
    assert len(events) == 1
    stored = await service.get(question.notification_id)
    assert stored.notification_type == "step_question"
    async with factory() as db:
        task = await db.get(Task, "task-question")
        assert task.workflow_state["pending_pause_type"] == "step_input"
    # A delayed origin activation cannot undo promotion or emit another mediation.
    await service.activate_question(question.notification_id)
    await other.recover_questions()
    assert len(events) == 1
