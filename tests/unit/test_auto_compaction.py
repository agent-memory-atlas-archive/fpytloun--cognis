"""Tests for automatic post-turn compaction in the agent loop."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest

from cognis.core.agent_loop import (
    CHAT_POLICY,
    AgentLoop,
    CompactionRunContext,
    PauseWaiter,
    SessionLock,
    StepContext,
)
from cognis.core.compaction import CompactionModelContext, CompactionResult
from cognis.core.events import Event, EventBus, EventType
from cognis.core.session_cache import CachedEvent, CachedSessionState
from cognis.models.agent import AgentDefinition
from cognis.models.session import (
    ConversationContext,
    ConversationModel,
    SessionModel,
    SessionTransition,
)
from cognis.models.tool import ToolCall, ToolResult
from cognis.models.workflow import StepDefinition, StepOutput
from cognis.store import queries

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCompactionStrategy:
    def __init__(
        self,
        *,
        result: CompactionResult | None = None,
        fail: bool = False,
        slow: float = 0.0,
    ) -> None:
        self.calls: list[tuple[str, str, bool]] = []  # (session_id, trigger, long_lived_chat)
        self.preserve_turns = 2
        self._result = result or CompactionResult(
            compacted=True,
            method="llm",
            summary="Auto-compaction summary text",
            compaction_seq=10,
            turns_compacted=5,
        )
        self._fail = fail
        self._slow = slow
        self.fallback_calls: list[tuple[str, str]] = []
        self.model_contexts: list[object | None] = []

    async def compact(
        self,
        session: SessionModel,
        *,
        trigger: str = "manual",
        model_context: object | None = None,
        long_lived_chat: bool = False,
    ) -> CompactionResult:
        self.model_contexts.append(model_context)
        self.calls.append((session.session_id, trigger, long_lived_chat))
        if self._slow:
            await asyncio.sleep(self._slow)
        if self._fail:
            raise RuntimeError("compaction failed")
        return self._result

    async def compact_with_fallback(
        self,
        session: SessionModel,
        *,
        trigger: str = "manual",
        model_context: object | None = None,
    ) -> CompactionResult:
        del model_context
        self.fallback_calls.append((session.session_id, trigger))
        return CompactionResult(
            compacted=True,
            method="mechanical",
            summary="Mechanical fallback summary",
            compaction_seq=20,
            turns_compacted=5,
        )


class _FakeGuardrails:
    async def record_events(self, *, session_id: str, events: list, **_: Any) -> Any:
        return type("AppendResult", (), {"ok": True, "first_seq": 1, "last_seq": len(events)})()


class _RejectedGuardrails:
    async def record_events(self, *, session_id: str, events: list, **_: Any) -> Any:
        return type("AppendResult", (), {"ok": False, "first_seq": 0, "last_seq": 0})()


@pytest.mark.asyncio
async def test_compaction_transition_cannot_append_after_ownership_loss() -> None:
    from unittest.mock import AsyncMock

    from cognis.core.compaction.publication import (
        CompactionOwnershipLost,
        CompactionPublicationGuard,
        compaction_publication_guard,
    )

    guardrails = _FakeGuardrails()
    guardrails.record_events = AsyncMock()
    loop = _minimal_agent_loop(
        compaction=_FakeCompactionStrategy(),
        session_cache=_FakeSessionCache(entry=_cache_entry_with_events(5)),
        guardrails=guardrails,
    )
    guard = CompactionPublicationGuard(
        token="lost-owner", check=AsyncMock(side_effect=CompactionOwnershipLost("lost"))
    )
    token = compaction_publication_guard.set(guard)
    try:
        with pytest.raises(CompactionOwnershipLost):
            await loop.persist_compaction_lifecycle(
                _session(), {"compaction_id": "compact-lost", "status": "running"}
            )
    finally:
        compaction_publication_guard.reset(token)
    guardrails.record_events.assert_not_awaited()


class _FakeLLM:
    def __init__(self) -> None:
        self.resolve_calls: list[dict[str, object]] = []

    async def resolve_model_target(
        self,
        *,
        explicit_model: str | None = None,
        task_type: str = "default",
        explicit_provider_id: str | None = None,
        acting_user_email: str | None = None,
    ) -> tuple[str, str | None]:
        self.resolve_calls.append(
            {
                "explicit_model": explicit_model,
                "task_type": task_type,
                "explicit_provider_id": explicit_provider_id,
                "acting_user_email": acting_user_email,
            }
        )
        return explicit_model or "default-model", explicit_provider_id or "default-provider"


class _FakeSessionManager:
    def __init__(self, *, fail: bool = False) -> None:
        self.rotations: list[dict[str, Any]] = []
        self._fail = fail

    def session_factory(self) -> Any:
        return _FakeDbSession()

    async def rotate_session(
        self,
        *,
        conversation_id: str,
        current_session: SessionModel,
        intention: str,
        completion_reason: str = "compacted",
        transition: SessionTransition = SessionTransition.COMPACT,
        compaction_summary: str | None = None,
        compaction_summary_event_data: dict[str, Any] | None = None,
        tail_events: list[Any] | None = None,
        fences: list[Any] | None = None,
    ) -> SessionModel:
        del compaction_summary, tail_events
        self.rotations.append(
            {
                "conversation_id": conversation_id,
                "old_session_id": current_session.session_id,
                "intention": intention,
                "completion_reason": completion_reason,
                "transition": transition,
                "compaction_summary_event_data": compaction_summary_event_data,
                "fences": list(fences or []),
            }
        )
        if self._fail:
            raise RuntimeError("rotation failed")
        return SessionModel(
            session_id="new-session-1",
            conversation_id=conversation_id,
            user_email=current_session.user_email,
            agent_id=current_session.agent_id,
            intaris_session_id="new-session-1",
        )


class _FakeDbSession:
    async def __aenter__(self) -> _FakeDbSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeSessionCache:
    def __init__(self, *, entry: CachedSessionState | None = None) -> None:
        self._entry = entry
        self.refreshed: list[str] = []
        self.compactions: list[tuple[str, str, int]] = []  # (session_id, summary, seq)

    def get_entry(self, session_id: str) -> CachedSessionState | None:
        if self._entry and self._entry.session_id == session_id:
            return self._entry
        return None

    def get_model_override(self, session_id: str) -> str | None:
        del session_id
        return None

    def get_model_override_provider_id(self, session_id: str) -> str | None:
        del session_id
        return None

    def get_reasoning_effort_override(self, session_id: str) -> str | None:
        del session_id
        return None

    async def refresh(self, session: SessionModel) -> CachedSessionState:
        self.refreshed.append(session.session_id)
        return CachedSessionState(
            session_id=session.session_id,
            intaris_session_id=session.intaris_session_id or session.session_id,
            initialized=True,
        )

    async def apply_compaction(
        self, session: SessionModel, *, summary: str, compaction_seq: int
    ) -> None:
        self.compactions.append((session.session_id, summary, compaction_seq))

    def get_events_since_compaction(
        self, session_id: str, types: list[str] | None = None
    ) -> list[CachedEvent]:
        if self._entry is None or self._entry.session_id != session_id:
            return []
        events = self._entry.events
        if types is None:
            return list(events)
        allowed = set(types)
        return [event for event in events if event.type in allowed]

    async def append_recorded_events(
        self, session: SessionModel, events: list, result: Any
    ) -> None:
        pass


@dataclass
class _FakeContextResult:
    messages: list[dict[str, Any]] = field(default_factory=list)
    recommend_compaction: bool = False
    cache_breakpoint_index: int | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session(session_id: str = "session-1") -> SessionModel:
    return SessionModel(
        session_id=session_id,
        conversation_id="conv-1",
        user_email="user@example.com",
        agent_id="agent-1",
        intaris_session_id=session_id,
        mnemory_session_id="mnemory-1",
    )


def _conversation() -> ConversationModel:
    return ConversationModel(
        conversation_id="conv-1",
        user_email="user@example.com",
        agent_id="agent-1",
        context=ConversationContext(type="web"),
        active_session_id="session-1",
    )


def _cache_entry_with_events(user_event_count: int) -> CachedSessionState:
    events: list[CachedEvent] = []
    seq = 0
    for i in range(user_event_count):
        seq += 1
        events.append(CachedEvent(seq=seq, type="user_message", data={"content": f"msg {i}"}))
        seq += 1
        events.append(
            CachedEvent(seq=seq, type="assistant_message", data={"content": f"reply {i}"})
        )
    return CachedSessionState(
        session_id="session-1",
        intaris_session_id="session-1",
        events=events,
        last_event_seq=seq,
        initialized=True,
    )


# ---------------------------------------------------------------------------
# Tests — _auto_compact method
# ---------------------------------------------------------------------------

# We test _auto_compact directly by constructing the required objects.
# This avoids the complexity of wiring up the full agent loop.


def _minimal_agent_loop(
    *,
    compaction: _FakeCompactionStrategy | None = None,
    session_manager: _FakeSessionManager | None = None,
    session_cache: _FakeSessionCache | None = None,
    event_bus: EventBus | None = None,
    llm: _FakeLLM | None = None,
    guardrails: Any | None = None,
) -> AgentLoop:
    """Create an AgentLoop with only the fields needed for _auto_compact."""
    loop = AgentLoop(
        providers=type(
            "P",
            (),
            {"llm": llm or _FakeLLM(), "guardrails": guardrails or _FakeGuardrails()},
        )(),
        session_manager=session_manager or _FakeSessionManager(),
        session_cache=session_cache or _FakeSessionCache(),
        context_assembler=None,
        compaction_strategy=compaction or _FakeCompactionStrategy(),
        tool_router=None,
        remember_queue=type("RQ", (), {"enqueue": staticmethod(lambda _: None)})(),
        event_bus=event_bus or EventBus(),
        session_lock=SessionLock(),
        pause_waiter=PauseWaiter(),
    )
    return loop


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_run", [True, False])
async def test_zero_turn_compaction_publishes_terminal_status(explicit_run: bool) -> None:
    published: list[Event] = []
    bus = EventBus()

    async def capture(event: Event) -> None:
        published.append(event)

    bus.subscribe_all(capture)
    loop = _minimal_agent_loop(
        compaction=_FakeCompactionStrategy(
            result=CompactionResult(compacted=True, method="llm", turns_compacted=0)
        ),
        session_cache=_FakeSessionCache(entry=_cache_entry_with_events(5)),
        event_bus=bus,
    )
    result = await loop._auto_compact(
        _step_context(),
        run=CompactionRunContext(trigger="pre_turn_auto", reason="context_compaction_threshold")
        if explicit_run
        else None,
    )
    assert result is not None and not result.compacted
    assert [event.type for event in published] == [
        EventType.SESSION_COMPACTION_STARTED,
        EventType.SESSION_COMPACTION_FINISHED,
    ]
    assert published[0].data["compaction_id"] == published[1].data["compaction_id"]
    assert published[1].data["status"] == "skipped"
    assert published[1].data["fallback_reason"] == "no_compactable_history"


@pytest.mark.asyncio
@pytest.mark.parametrize("reject_start", [True, False])
async def test_rejected_compaction_append_is_not_published(reject_start: bool) -> None:
    compaction = _FakeCompactionStrategy(
        result=CompactionResult(compacted=False, method="no_compactable_history")
    )
    cache = _FakeSessionCache(entry=_cache_entry_with_events(5))
    published: list[Event] = []
    bus = EventBus()

    async def capture(event: Event) -> None:
        published.append(event)

    bus.subscribe_all(capture)

    class RejectTransition:
        async def record_events(self, *, session_id: str, events: list, **kwargs: Any) -> Any:
            reject = reject_start or events[0].data["status"] != "running"
            delegate = _RejectedGuardrails() if reject else _FakeGuardrails()
            return await delegate.record_events(session_id=session_id, events=events, **kwargs)

    loop = _minimal_agent_loop(
        compaction=compaction,
        session_cache=cache,
        event_bus=bus,
        guardrails=RejectTransition(),
    )

    with pytest.raises(RuntimeError, match="rejected compaction event"):
        await loop._auto_compact(  # noqa: SLF001
            _step_context(),
            run=CompactionRunContext(
                trigger="pre_turn_auto",
                reason="context_compaction_threshold",
            ),
        )

    assert [item.type for item in published] == (
        [] if reject_start else [EventType.SESSION_COMPACTION_STARTED]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["summary", "model_context", "fallback"])
async def test_cancelling_compaction_persists_terminal_occurrence(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    started = asyncio.Event()
    entered = asyncio.Event()
    published: list[Event] = []
    bus = EventBus()

    async def capture(item: Event) -> None:
        published.append(item)
        if item.type == EventType.SESSION_COMPACTION_STARTED:
            started.set()

    bus.subscribe_all(capture)
    loop = _minimal_agent_loop(
        compaction=_FakeCompactionStrategy(slow=60),
        session_cache=_FakeSessionCache(entry=_cache_entry_with_events(5)),
        event_bus=bus,
    )

    async def block(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await asyncio.Event().wait()

    if stage == "model_context":
        monkeypatch.setattr(loop, "_resolve_compaction_model_context", block)
    elif stage == "fallback":
        monkeypatch.setattr("cognis.core.agent_loop.AUTO_COMPACTION_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(loop.compaction_strategy, "compact_with_fallback", block)
    task = asyncio.create_task(
        loop._auto_compact(
            _step_context(),
            run=CompactionRunContext(trigger="tool_loop_pressure", reason="pressure"),
            emit_timeout_notice=False,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    if stage != "summary":
        await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert published[-1].data["status"] == "failed"
    assert published[-1].data["fallback_reason"] == "cancelled"
    assert published[-1].data["compaction_id"] == published[0].data["compaction_id"]


def _step_context(session: SessionModel | None = None) -> StepContext:
    return StepContext(
        step_definition=StepDefinition(name="direct", type="run", prompt=""),
        session=session or _session(),
        conversation=_conversation(),
        agent=AgentDefinition(
            agent_id="agent-1",
            name="Test Agent",
            owner_email="user@example.com",
        ),
        policy=CHAT_POLICY,
    )


@pytest.mark.asyncio
async def test_auto_compact_triggers_rotation_and_caches() -> None:
    """Full happy path: compaction + rotation + cache pre-population."""
    compaction = _FakeCompactionStrategy()
    session_mgr = _FakeSessionManager()
    cache = _FakeSessionCache(entry=_cache_entry_with_events(5))
    published: list[Event] = []
    bus = EventBus()

    async def capture(event: Event) -> None:
        published.append(event)

    bus.subscribe_all(capture)

    loop = _minimal_agent_loop(
        compaction=compaction,
        session_manager=session_mgr,
        session_cache=cache,
        event_bus=bus,
    )

    ctx = _step_context()
    result = await loop._auto_compact(ctx)
    assert result is not None
    await loop._rotate_after_compaction(ctx, result, trigger="automatic")

    # Compaction was called with trigger="automatic"
    assert len(compaction.calls) == 1
    assert compaction.calls[0] == ("session-1", "automatic", False)

    # Session was rotated
    assert len(session_mgr.rotations) == 1
    assert session_mgr.rotations[0]["old_session_id"] == "session-1"
    assert session_mgr.rotations[0]["completion_reason"] == "compacted"
    marker_data = session_mgr.rotations[0]["compaction_summary_event_data"]
    assert marker_data["timeline_visible"] is True
    assert marker_data["marker_role"] == "context_seed"
    assert marker_data["method"] == "llm"
    assert marker_data["trigger"] == "automatic"
    assert marker_data["status"] == "compacted"
    assert marker_data["turns_compacted"] == 5

    # Cache was refreshed for the new session; the durable summary event is
    # recorded by SessionManager during rotation.
    assert cache.refreshed == ["new-session-1"]
    assert cache.compactions == []

    # Runtime start is visible before the terminal rotation event.
    assert [event.type.value for event in published] == [
        "session_compaction_started",
        "session_compacted",
    ]
    assert published[0].data["session_id"] == "session-1"
    assert published[0].data["status"] == "running"
    assert published[1].data["previous_session_id"] == "session-1"
    assert published[1].data["session_id"] == "new-session-1"
    assert published[1].data["status"] == "compacted"


@pytest.mark.asyncio
async def test_zero_turn_compaction_does_not_rotate() -> None:
    session_manager = _FakeSessionManager()
    loop = _minimal_agent_loop(session_manager=session_manager)
    result = CompactionResult(
        compacted=True,
        method="llm",
        summary="No effective history",
        compaction_seq=1,
        turns_compacted=0,
    )

    rotated = await loop._rotate_after_compaction(
        _step_context(),
        result,
        trigger="automatic",
    )

    assert rotated is None
    assert session_manager.rotations == []


@pytest.mark.asyncio
async def test_stale_rotated_session_stops_before_step_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[Event] = []
    bus = EventBus()

    async def capture(event: Event) -> None:
        published.append(event)

    bus.subscribe_all(capture)
    loop = _minimal_agent_loop(event_bus=bus)
    ctx = _step_context()
    ctx.turn_id = "turn-1"

    async def fake_get_conversation(db_session: object, conversation_id: str) -> Any:
        del db_session, conversation_id
        return type("ConversationRow", (), {"active_session_id": "new-session-1"})()

    async def fake_get_session_row(db_session: object, session_id: str) -> Any:
        del db_session, session_id
        return type(
            "SessionRow",
            (),
            {"status": "completed", "completion_reason": "compacted"},
        )()

    monkeypatch.setattr(queries, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(queries, "get_session_row", fake_get_session_row)

    result = await loop._stale_session_step_output(ctx, phase="before_assistant_or_tool_dispatch")

    assert result is not None
    assert result.metadata["interrupted"] is True
    assert result.metadata["continuation_reason"] == "session_rotated"
    assert result.metadata["active_session_id"] == "new-session-1"
    assert result.metadata["completion_reason"] == "compacted"
    assert [event.type for event in published] == [EventType.SYSTEM_NOTICE]


@pytest.mark.asyncio
async def test_terminal_child_session_stops_before_step_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _minimal_agent_loop()
    ctx = _step_context()
    ctx.session.parent_session_id = "parent-session"
    ctx.turn_id = "turn-child"

    async def fake_get_conversation(db_session: object, conversation_id: str) -> Any:
        del db_session, conversation_id
        return type("ConversationRow", (), {"active_session_id": "root-session"})()

    async def fake_get_session_row(db_session: object, session_id: str) -> Any:
        del db_session, session_id
        return type(
            "SessionRow",
            (),
            {"status": "terminated", "completion_reason": None},
        )()

    monkeypatch.setattr(queries, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(queries, "get_session_row", fake_get_session_row)

    result = await loop._stale_session_step_output(
        ctx,
        phase="before_assistant_or_tool_dispatch",
    )

    assert result is not None
    assert result.metadata["continuation_reason"] == "session_terminal"
    assert result.metadata["session_status"] == "terminated"


@pytest.mark.asyncio
async def test_intaris_terminated_result_marks_cognis_session_terminated() -> None:
    loop = _minimal_agent_loop()
    ctx = _step_context()
    loop.session_manager.mark_terminated = AsyncMock(return_value=True)
    result = ToolResult(
        output="Session is terminated",
        is_error=True,
        metadata={
            "evaluation": {
                "session_status": "terminated",
                "status_reason": "safety hard kill",
            }
        },
    )

    await loop._sync_guardrails_terminal_result(ctx, result)

    loop.session_manager.mark_terminated.assert_awaited_once_with(
        ctx.session.session_id,
        reason="safety hard kill",
    )
    assert ctx.session.status == "terminated"


@pytest.mark.asyncio
async def test_terminal_session_is_blocked_at_each_tool_dispatch() -> None:
    loop = _minimal_agent_loop()
    ctx = _step_context()
    loop._stale_session_step_output = AsyncMock(
        return_value=StepOutput(
            summary="Session is terminal.",
            metadata={
                "continuation_reason": "session_terminal",
                "session_status": "terminated",
            },
        )
    )

    result = await loop.execute_controller_tool(
        ctx,
        ToolCall(call_id="call-after-terminal", name="bash", arguments={"command": "pwd"}),
    )

    assert result.is_error is True
    assert result.metadata["code"] == "session_not_continuable"
    assert result.metadata["session_status"] == "terminated"


@pytest.mark.asyncio
async def test_auto_compact_resolves_model_context_before_cycle_model_call() -> None:
    """Pre-turn auto-compaction has a concrete model for same-session routing."""

    compaction = _FakeCompactionStrategy()
    cache = _FakeSessionCache(entry=_cache_entry_with_events(5))
    llm = _FakeLLM()
    loop = _minimal_agent_loop(compaction=compaction, session_cache=cache, llm=llm)

    ctx = _step_context()
    result = await loop._auto_compact(ctx)

    assert result is not None
    assert llm.resolve_calls == [
        {
            "explicit_model": None,
            "task_type": "default",
            "explicit_provider_id": None,
            "acting_user_email": "user@example.com",
        }
    ]
    model_context = compaction.model_contexts[0]
    assert isinstance(model_context, CompactionModelContext)
    assert model_context.model == "default-model"
    assert model_context.provider_id == "default-provider"
    assert ctx.current_model == "default-model"
    assert ctx.current_provider_id == "default-provider"


@pytest.mark.asyncio
async def test_auto_compact_skips_when_few_events() -> None:
    """Early exit when user event count <= preserve_turns."""
    compaction = _FakeCompactionStrategy()
    compaction.preserve_turns = 5
    cache = _FakeSessionCache(entry=_cache_entry_with_events(3))

    loop = _minimal_agent_loop(compaction=compaction, session_cache=cache)
    ctx = _step_context()
    result = await loop._auto_compact(ctx)

    # Compaction should not be called
    assert result is None
    assert len(compaction.calls) == 0


@pytest.mark.asyncio
async def test_auto_compact_does_not_skip_large_tool_heavy_single_turn() -> None:
    compaction = _FakeCompactionStrategy()
    compaction.preserve_turns = 5
    entry = _cache_entry_with_events(1)
    next_seq = entry.events[-1].seq + 1
    for index in range(60):
        call_id = f"call-{index}"
        entry.events.extend(
            [
                CachedEvent(
                    seq=next_seq + index * 2,
                    type="tool_call",
                    data={"call_id": call_id, "name": "read"},
                ),
                CachedEvent(
                    seq=next_seq + index * 2 + 1,
                    type="tool_result",
                    data={"call_id": call_id, "name": "read", "result": "x"},
                ),
            ]
        )
    cache = _FakeSessionCache(entry=entry)
    loop = _minimal_agent_loop(compaction=compaction, session_cache=cache)

    result = await loop._auto_compact(_step_context())

    assert result is not None
    assert result.compacted
    assert len(compaction.calls) == 1


@pytest.mark.asyncio
async def test_auto_compact_skips_when_noop() -> None:
    """Compaction returns noop — no rotation should happen."""
    compaction = _FakeCompactionStrategy(
        result=CompactionResult(compacted=False, method="noop"),
    )
    session_mgr = _FakeSessionManager()
    cache = _FakeSessionCache(entry=_cache_entry_with_events(5))

    loop = _minimal_agent_loop(
        compaction=compaction,
        session_manager=session_mgr,
        session_cache=cache,
    )
    ctx = _step_context()
    result = await loop._auto_compact(ctx)

    assert result is not None
    assert result.compacted is False
    assert len(compaction.calls) == 1
    assert len(session_mgr.rotations) == 0


@pytest.mark.asyncio
async def test_auto_compact_compaction_failure_returns_none() -> None:
    """Compaction failure should return None.

    compact() now handles its own retry and mechanical fallback internally.
    When compact() raises, _auto_compact surfaces the failure cleanly by
    returning None rather than attempting a second fallback call.
    """
    compaction = _FakeCompactionStrategy(fail=True)
    session_mgr = _FakeSessionManager()
    cache = _FakeSessionCache(entry=_cache_entry_with_events(5))

    loop = _minimal_agent_loop(
        compaction=compaction,
        session_manager=session_mgr,
        session_cache=cache,
    )
    ctx = _step_context()

    # Should not raise; compact() already handled its own fallback internally.
    result = await loop._auto_compact(ctx)

    assert result is None
    assert len(compaction.calls) == 1
    # No rotation attempted when compaction failed.
    assert len(session_mgr.rotations) == 0


@pytest.mark.asyncio
async def test_auto_compact_rotation_failure_is_graceful() -> None:
    """Rotation failure after successful compaction should not raise."""
    compaction = _FakeCompactionStrategy()
    session_mgr = _FakeSessionManager(fail=True)
    cache = _FakeSessionCache(entry=_cache_entry_with_events(5))

    loop = _minimal_agent_loop(
        compaction=compaction,
        session_manager=session_mgr,
        session_cache=cache,
    )
    ctx = _step_context()

    # Should not raise
    result = await loop._auto_compact(ctx)
    assert result is not None
    rotated = await loop._rotate_after_compaction(ctx, result, trigger="automatic")

    assert len(compaction.calls) == 1
    assert rotated is None
    assert len(session_mgr.rotations) == 1
    assert len(cache.compactions) == 0  # Cache not populated after rotation failure


@pytest.mark.asyncio
async def test_auto_compact_timeout_is_graceful() -> None:
    """Slow compaction should time out without raising."""
    compaction = _FakeCompactionStrategy(slow=20.0)  # > AUTO_COMPACTION_TIMEOUT_SECONDS
    cache = _FakeSessionCache(entry=_cache_entry_with_events(5))

    published: list[Event] = []
    bus = EventBus()

    async def capture(event: Event) -> None:
        published.append(event)

    bus.subscribe_all(capture)
    loop = _minimal_agent_loop(compaction=compaction, session_cache=cache, event_bus=bus)
    ctx = _step_context()
    run = CompactionRunContext(trigger="automatic", reason="test_timeout")

    # Monkey-patch timeout to be very short for test speed
    import cognis.core.agent_loop as agent_loop_mod

    original_timeout = agent_loop_mod.AUTO_COMPACTION_TIMEOUT_SECONDS
    agent_loop_mod.AUTO_COMPACTION_TIMEOUT_SECONDS = 0.05
    try:
        result = await loop._auto_compact(ctx, run=run)
    finally:
        agent_loop_mod.AUTO_COMPACTION_TIMEOUT_SECONDS = original_timeout

    # Compaction was attempted, timed out, then used fallback.
    assert result is not None
    # The fake strategy returns "mechanical"; real strategy returns "mechanical_sliding_window".
    assert result.method in ("mechanical", "mechanical_sliding_window")
    assert run.used_timeout_fallback is True
    assert len(compaction.calls) == 1
    assert compaction.fallback_calls == [("session-1", "automatic_timeout_fallback")]
    assert any(event.type.value == "system_notice" for event in published)


@pytest.mark.asyncio
async def test_auto_compact_no_cache_entry_runs_normally() -> None:
    """When no cache entry exists, skip early-exit check and proceed."""
    compaction = _FakeCompactionStrategy()
    session_mgr = _FakeSessionManager()
    cache = _FakeSessionCache(entry=None)

    loop = _minimal_agent_loop(
        compaction=compaction,
        session_manager=session_mgr,
        session_cache=cache,
    )
    ctx = _step_context()
    result = await loop._auto_compact(ctx)
    assert result is not None
    await loop._rotate_after_compaction(ctx, result, trigger="automatic")

    # Should still run compaction (no early-exit)
    assert len(compaction.calls) == 1
    assert len(session_mgr.rotations) == 1


@pytest.mark.asyncio
async def test_idle_checkpoint_compacts_with_ambient_prompt_and_trigger() -> None:
    compaction = _FakeCompactionStrategy()
    session_mgr = _FakeSessionManager()
    cache = _FakeSessionCache(entry=_cache_entry_with_events(11))
    published: list[Event] = []
    bus = EventBus()

    async def capture(event: Event) -> None:
        published.append(event)

    bus.subscribe_all(capture)
    loop = _minimal_agent_loop(
        compaction=compaction,
        session_manager=session_mgr,
        session_cache=cache,
        event_bus=bus,
    )

    new_session = await loop.run_idle_checkpoint_compaction(
        conversation=_conversation(),
        session=_session(),
        agent=AgentDefinition(
            agent_id="agent-1",
            name="Test Agent",
            owner_email="user@example.com",
        ),
        min_events=20,
    )

    assert new_session is not None
    assert compaction.calls == [("session-1", "idle_checkpoint", True)]
    assert len(session_mgr.rotations) == 1
    assert session_mgr.rotations[0]["transition"] is SessionTransition.RENEW
    assert published[0].data["trigger"] == "idle_checkpoint"


@pytest.mark.asyncio
async def test_idle_checkpoint_skips_below_min_events() -> None:
    compaction = _FakeCompactionStrategy()
    session_mgr = _FakeSessionManager()
    cache = _FakeSessionCache(entry=_cache_entry_with_events(9))
    loop = _minimal_agent_loop(
        compaction=compaction,
        session_manager=session_mgr,
        session_cache=cache,
    )

    new_session = await loop.run_idle_checkpoint_compaction(
        conversation=_conversation(),
        session=_session(),
        agent=AgentDefinition(
            agent_id="agent-1",
            name="Test Agent",
            owner_email="user@example.com",
        ),
        min_events=20,
    )

    assert new_session is None
    assert compaction.calls == []
    assert session_mgr.rotations == []


class _FakeLeaseStore:
    """In-memory stand-in for DatabaseLeaseStore with a takeover switch."""

    def __init__(self) -> None:
        self.acquired: list[str] = []
        self.released: list[str] = []
        self.taken_over: set[str] = set()
        self.busy: set[str] = set()

    async def acquire(self, resource_key: str, owner_id: str, *, ttl_seconds: float) -> Any:
        from datetime import UTC, datetime

        from cognis.store.coordination import Lease

        del ttl_seconds
        if resource_key in self.busy:
            return None
        self.acquired.append(resource_key)
        return Lease(
            resource_key=resource_key,
            owner_id=owner_id,
            fencing_token=7,
            lease_expires_at=datetime.now(UTC),
        )

    async def is_current(self, lease: Any) -> bool:
        return lease.resource_key not in self.taken_over

    async def release(self, lease: Any) -> bool:
        self.released.append(lease.resource_key)
        return True


def _fenced_loop(
    lease_store: _FakeLeaseStore,
    *,
    compaction: _FakeCompactionStrategy | None = None,
    session_manager: _FakeSessionManager | None = None,
) -> AgentLoop:
    loop = _minimal_agent_loop(
        compaction=compaction,
        session_manager=session_manager,
        session_cache=_FakeSessionCache(entry=_cache_entry_with_events(5)),
    )
    loop._session_factory = object()
    loop._compaction_leases = lease_store
    loop._controller_runtime = type(
        "Runtime", (), {"controller_id": "controller-a", "incarnation_id": "boot-a"}
    )()
    return loop


@pytest.mark.asyncio
async def test_auto_compact_skips_when_another_controller_holds_the_lease() -> None:
    compaction = _FakeCompactionStrategy()
    leases = _FakeLeaseStore()
    leases.busy.add("compaction:session:session-1")
    loop = _fenced_loop(leases, compaction=compaction)

    result = await loop._auto_compact(_step_context())

    assert result is None
    assert compaction.calls == [], "no LLM compaction while another owner compacts"
    assert leases.released == []


@pytest.mark.asyncio
async def test_auto_compact_holds_lease_through_rotation_and_fences_it() -> None:
    compaction = _FakeCompactionStrategy()
    session_mgr = _FakeSessionManager()
    leases = _FakeLeaseStore()
    loop = _fenced_loop(leases, compaction=compaction, session_manager=session_mgr)
    ctx = _step_context()

    result = await loop._auto_compact(ctx)
    assert result is not None and result.compacted
    assert leases.acquired == ["compaction:session:session-1"]
    assert ctx.compaction_lease is not None, "lease must survive until rotation"
    assert leases.released == []

    new_session = await loop._rotate_after_compaction(ctx, result, trigger="automatic")
    assert new_session is not None
    assert [lease.resource_key for lease in session_mgr.rotations[0]["fences"]] == [
        "compaction:session:session-1"
    ]
    assert ctx.compaction_lease is None
    assert leases.released == ["compaction:session:session-1"]


@pytest.mark.asyncio
async def test_auto_compact_releases_lease_when_nothing_is_compacted() -> None:
    compaction = _FakeCompactionStrategy(
        result=CompactionResult(compacted=False, method="no_compactable_history")
    )
    leases = _FakeLeaseStore()
    loop = _fenced_loop(leases, compaction=compaction)
    ctx = _step_context()

    result = await loop._auto_compact(ctx)
    assert result is not None and not result.compacted
    assert ctx.compaction_lease is None
    assert leases.released == ["compaction:session:session-1"]


@pytest.mark.asyncio
async def test_rotation_refuses_after_takeover_between_check_and_commit() -> None:
    from cognis.core.compaction.publication import CompactionOwnershipLost

    compaction = _FakeCompactionStrategy()
    session_mgr = _FakeSessionManager()
    leases = _FakeLeaseStore()
    loop = _fenced_loop(leases, compaction=compaction, session_manager=session_mgr)
    ctx = _step_context()
    result = await loop._auto_compact(ctx)
    assert result is not None and result.compacted

    # Ownership changes after the entry check passed.
    leases.taken_over.add("compaction:session:session-1")
    with pytest.raises(CompactionOwnershipLost):
        await loop._rotate_after_compaction(ctx, result, trigger="automatic")
    assert session_mgr.rotations == [], "a stale owner must not rotate"
    assert ctx.compaction_lease is None
    assert leases.released == ["compaction:session:session-1"]


@pytest.mark.asyncio
async def test_lost_direct_turn_fence_stops_compaction_before_any_work() -> None:
    from cognis.core.direct_turn_runtime import StaleDirectTurnOwner

    compaction = _FakeCompactionStrategy()
    leases = _FakeLeaseStore()
    loop = _fenced_loop(leases, compaction=compaction)
    ctx = _step_context()

    class _LostFence:
        lease = None

        async def assert_current(self) -> None:
            raise StaleDirectTurnOwner("lost")

    ctx.execution_fence = _LostFence()
    with pytest.raises(StaleDirectTurnOwner):
        await loop._auto_compact(ctx)
    assert compaction.calls == []
    assert leases.acquired == []


@pytest.mark.asyncio
async def test_compaction_publication_guard_gates_the_intaris_append() -> None:
    from cognis.core.compaction.publication import (
        CompactionOwnershipLost,
        CompactionPublicationGuard,
        compaction_publication_guard,
    )
    from cognis.core.compaction.strategy import CompactionStrategy

    recorded: list[tuple[str, str | None]] = []

    class _Guardrails:
        async def record_events(self, *, session_id: str, events: Any, idempotency_key: str) -> Any:
            recorded.append((session_id, idempotency_key))
            return type("Append", (), {"ok": True, "last_seq": 42})()

    class _Cache:
        async def apply_compaction(self, *_: Any, **__: Any) -> None:
            return None

    strategy = CompactionStrategy.__new__(CompactionStrategy)
    strategy.guardrails = _Guardrails()
    strategy.session_cache = _Cache()
    strategy.llm = type("LLM", (), {"count_tokens": lambda self, text, model: len(text) // 4})()
    session = SessionModel(
        session_id="session-1",
        conversation_id="conv-1",
        user_email="user@example.com",
        agent_id="agent-1",
        intaris_session_id="session-1",
    )
    older = [
        CachedEvent(seq=i, type="user_message", data={"content": f"m{i}"}) for i in range(1, 4)
    ]

    async def _lost() -> None:
        raise CompactionOwnershipLost("gone")

    token = compaction_publication_guard.set(
        CompactionPublicationGuard(token="fence7", check=_lost)
    )
    try:
        with pytest.raises(CompactionOwnershipLost):
            await strategy._record_compaction(
                session=session,
                summary="summary",
                formatted_input="input",
                older_events=older,
                preserved_tail_events=[],
                method="llm",
                resolved_model="test-model",
                compaction_id="compact_1",
            )
    finally:
        compaction_publication_guard.reset(token)
    assert recorded == [], "no compaction_summary may be appended by a stale owner"

    async def _ok() -> None:
        return None

    token = compaction_publication_guard.set(CompactionPublicationGuard(token="fence7", check=_ok))
    try:
        result = await strategy._record_compaction(
            session=session,
            summary="summary",
            formatted_input="input",
            older_events=older,
            preserved_tail_events=[],
            method="llm",
            resolved_model="test-model",
            compaction_id="compact_1",
        )
    finally:
        compaction_publication_guard.reset(token)
    assert result.compaction_seq == 42
    assert recorded == [("session-1", "session-1:compaction:llm:3:fence7")]
