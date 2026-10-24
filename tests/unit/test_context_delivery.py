"""Delivery and replay invariants for controller-owned context messages."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cognis.core.agent_loop import AgentLoop, replace_orchestration_capability_guidance
from cognis.core.context import (
    ContextAssembler,
    _append_executor_pool_reminder,
    _append_routing_reminder,
    events_to_messages,
)
from cognis.core.context_projection import (
    apply_projection_decisions,
    projection_decision_batches,
    projection_decisions_from_diff,
)
from cognis.core.errors import ImmutablePrefixUnavailable
from cognis.core.executor_pool import ExecutorAvailability, ExecutorPool, ResolvedExecutorTarget
from cognis.core.session_cache import SessionCache
from cognis.models.agent import AgentDefinition
from cognis.models.session import (
    EventAppendResult,
    EventReadResult,
    ReasoningReportResult,
    SessionEvent,
    SessionModel,
)
from cognis.providers.llm.message_projection import project_messages_for_provider


def _executor_pool() -> ExecutorPool:
    return ExecutorPool(
        primary=[
            ResolvedExecutorTarget(
                executor_id="exec-primary",
                executor_type="websocket",
                is_primary=True,
                selection_source="explicit",
                description=None,
                state=ExecutorAvailability.USABLE,
            )
        ],
        additional=[
            ResolvedExecutorTarget(
                executor_id="raspi-camera",
                executor_type="websocket",
                is_primary=False,
                selection_source="additional_explicit",
                description="camera host",
                state=ExecutorAvailability.USABLE,
            )
        ],
    )


@pytest.mark.parametrize("empty", [False, True])
def test_initial_single_or_empty_executor_pool_needs_no_notice(empty: bool) -> None:
    messages = [{"role": "user", "content": "Inspect the repository."}]
    _append_executor_pool_reminder(
        messages,
        executor_pool=None
        if empty
        else ExecutorPool(primary=_executor_pool().primary, additional=[]),
        active_executor_id="exec-primary",
    )
    assert messages == [{"role": "user", "content": "Inspect the repository."}]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unchanged", "active_executor", "single_executor", "removed"])
async def test_executor_notice_keeps_accepted_position_across_cold_replay(change: str) -> None:
    loop = object.__new__(AgentLoop)
    loop._record_events_strict = AsyncMock()
    pool = _executor_pool()
    messages = [{"role": "user", "content": "Inspect assigned executors."}]
    _append_executor_pool_reminder(messages, executor_pool=pool, active_executor_id="exec-primary")
    first_notice = deepcopy(messages[-1])
    pending = ContextAssembler._collect_audit_messages(messages)
    await loop._record_outgoing_audit_messages(
        SimpleNamespace(turn_id="turn_executor_notice_first"), audit_messages=pending
    )
    recorded = loop._record_events_strict.call_args.args[1]
    events = [
        {"seq": 1, "type": "user_message", "data": {"content": messages[0]["content"]}},
        *[
            {"seq": index + 2, "type": event.type, "data": event.data}
            for index, event in enumerate(recorded)
        ],
        {"seq": 3, "type": "assistant_message", "data": {"content": "Assignments checked."}},
        {"seq": 4, "type": "user_message", "data": {"content": "Check again."}},
    ]
    replay = events_to_messages(events)
    assert replay[1]["content"] == first_notice["content"]
    if change == "single_executor":
        pool = ExecutorPool(primary=pool.primary, additional=[])
    _append_executor_pool_reminder(
        replay,
        executor_pool=None if change == "removed" else pool,
        active_executor_id="raspi-camera" if change == "active_executor" else "exec-primary",
    )
    expected_count = 1 if change == "unchanged" else 2
    assert sum(m.get("_audit_source") == "executor_pool_reminder" for m in replay) == expected_count
    for provider, api in (
        (SimpleNamespace(config={"preset": "anthropic"}), "chat"),
        (None, "responses"),
    ):
        previous = project_messages_for_provider(messages, provider=provider, llm_api=api).messages
        following = project_messages_for_provider(replay, provider=provider, llm_api=api).messages
        assert following[: len(previous)] == previous
    new_audits = ContextAssembler._collect_audit_messages(replay)
    assert len(new_audits) == expected_count - 1
    if change == "removed":
        assert "no executors" in str(replay[-1]["content"]).lower()
    elif change == "single_executor":
        assert "exec-primary" in replay[-1]["content"]
        assert "raspi-camera" not in replay[-1]["content"]
        assert "no executors" not in replay[-1]["content"].lower()
    if new_audits:
        await loop._record_outgoing_audit_messages(
            SimpleNamespace(turn_id="turn_executor_notice_second"), audit_messages=new_audits
        )
        events.extend(
            {"seq": index + 5, "type": event.type, "data": event.data}
            for index, event in enumerate(loop._record_events_strict.call_args.args[1])
        )
    replay = events_to_messages(events)
    _append_executor_pool_reminder(
        replay,
        executor_pool=None if change == "removed" else pool,
        active_executor_id="raspi-camera" if change == "active_executor" else "exec-primary",
    )
    assert sum(m.get("_audit_source") == "executor_pool_reminder" for m in replay) == expected_count
    assert not ContextAssembler._collect_audit_messages(replay)


def test_changed_capabilities_append_without_rewriting_history() -> None:
    messages = [{"role": "user", "content": "Inspect the repository."}]
    replace_orchestration_capability_guidance(messages, "First capability notice.")
    accepted = deepcopy(messages)
    replace_orchestration_capability_guidance(messages, "Updated capability notice.")
    assert messages[: len(accepted)] == accepted
    assert len(messages) == len(accepted) + 1
    replace_orchestration_capability_guidance(messages, "Updated capability notice.")
    assert len(messages) == len(accepted) + 1


@pytest.mark.asyncio
async def test_routing_notice_compares_latest_delivery_when_guidance_returns() -> None:
    loop = object.__new__(AgentLoop)
    loop._record_events_strict = AsyncMock()
    ctx = SimpleNamespace(turn_id="turn_routing_reentry")
    events = [{"seq": 1, "type": "user_message", "data": {"content": "Inspect safely."}}]
    messages = events_to_messages(events)
    for index, content in enumerate(
        ("Initial guidance.", "Updated guidance.", "Initial guidance.")
    ):
        accepted = deepcopy(messages)
        _append_routing_reminder(messages, content, turn_id=ctx.turn_id)
        assert messages[: len(accepted)] == accepted
        pending = ContextAssembler._collect_audit_messages(messages)
        assert len(pending) == 1, "A change back to earlier guidance must append a new notice"
        await loop._record_outgoing_audit_messages(ctx, audit_messages=pending)
        recorded = loop._record_events_strict.call_args.args[1]
        events.append({"seq": index + 2, "type": recorded[0].type, "data": recorded[0].data})
        messages = events_to_messages(events)
        _append_routing_reminder(messages, content, turn_id=ctx.turn_id)
        assert not ContextAssembler._collect_audit_messages(messages)


@pytest.mark.asyncio
async def test_delivered_notice_replays_with_identical_provider_provenance() -> None:
    loop = object.__new__(AgentLoop)
    loop._record_events_strict = AsyncMock()
    messages = [{"role": "user", "content": "Inspect the repository."}]
    replace_orchestration_capability_guidance(messages, "First capability notice.")
    pending = []
    loop._append_pending_audit_message(
        messages,
        pending,
        role="developer",
        source="orchestration_capability_guidance",
        content=messages[-1]["content"],
    )
    ctx = SimpleNamespace(turn_id="turn_context_delivery")
    await loop._record_outgoing_audit_messages(ctx, audit_messages=pending, on_token=None)
    recorded = loop._record_events_strict.call_args.args[1]
    events = [
        {"seq": 1, "type": "user_message", "data": {"content": messages[0]["content"]}},
        *[
            {"seq": index + 2, "type": event.type, "data": event.data}
            for index, event in enumerate(recorded)
        ],
    ]
    for provider, api in (
        (SimpleNamespace(config={"preset": "anthropic"}), "chat"),
        (None, "responses"),
    ):
        live = project_messages_for_provider(messages, provider=provider, llm_api=api)
        replayed = project_messages_for_provider(
            events_to_messages(events), provider=provider, llm_api=api
        )
        assert live.messages == replayed.messages


def _operation(name: str) -> dict:
    return {"operation": name, "rendering_policy_version": 1, "parameters": {}}


class _EventStore:
    """Intaris-shaped append/read boundary; derived caches are disposable."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.keys: dict[str, EventAppendResult] = {}
        self.writes: list[dict] = []
        self.reads = 0
        self.cancel_after_accept = False

    async def record_events(self, *, events, idempotency_key, **kwargs):
        self.writes.append({"key": idempotency_key, "events": deepcopy(events)})
        if idempotency_key not in self.keys:
            first = len(self.events) + 1
            for event in events:
                self.events.append(
                    {"seq": len(self.events) + 1, "type": event.type, "data": deepcopy(event.data)}
                )
            self.keys[idempotency_key] = EventAppendResult(
                ok=True, count=len(events), first_seq=first, last_seq=len(self.events)
            )
        if self.cancel_after_accept:
            self.cancel_after_accept = False
            raise asyncio.CancelledError()
        return self.keys[idempotency_key]

    async def read_events(self, *, after_seq=0, types=None, **kwargs):
        self.reads += 1
        return EventReadResult(
            events=[
                event
                for event in self.events
                if event["seq"] > after_seq and (types is None or event["type"] in types)
            ],
            last_seq=len(self.events),
            has_more=False,
        )

    async def report_reasoning(self, **kwargs):
        return ReasoningReportResult(ok=True)


async def _projection_runtime(store: _EventStore):
    session = SessionModel(
        session_id="sess_context_delivery",
        intaris_session_id="sess_context_delivery",
        conversation_id="conv_context_delivery",
        user_email="delivery@test.local",
        agent_id="delivery",
    )
    agent = AgentDefinition(agent_id="delivery", owner_email=session.user_email, name="Delivery")
    cache = SessionCache(store)
    await cache.refresh(session)
    assembler = object.__new__(ContextAssembler)
    assembler.guardrails = store
    assembler.session_cache = cache
    return session, agent, cache, assembler


@pytest.mark.asyncio
@pytest.mark.parametrize("skip_memory", [False, True])
@pytest.mark.parametrize(
    "second_reminder", [None, "Inspect the repository.", "Plan only; do not edit."]
)
async def test_routing_notice_survives_real_assembly_and_repeated_cold_replay(
    skip_memory: bool, second_reminder: str | None
) -> None:
    from tests.unit.test_context_assembler import (
        _LLM,
        _conversation,
        _Memory,
        _SessionManager,
    )

    store = _EventStore()
    store.get_session = AsyncMock(
        return_value=SimpleNamespace(intention=None, title=None, status="active", updated_at=None)
    )
    session, agent, cache, _ = await _projection_runtime(store)
    loop = object.__new__(AgentLoop)

    async def record(_ctx, events, **kwargs):
        return await store.record_events(
            events=events, idempotency_key=f"audits_{len(store.events)}"
        )

    loop._record_events_strict = record
    previous_payloads = {}
    caches = [cache]
    try:
        for turn, reminder in enumerate(["Inspect the repository.", second_reminder]):
            turn_id = f"turn_routing_{turn}"
            text = f"Request {turn}"
            metadata = {"ts": "2026-01-01T10:00:00Z"}
            await store.record_events(
                events=[
                    SessionEvent(
                        type="user_message",
                        data={"content": text, "turn_id": turn_id, "message_metadata": metadata},
                    )
                ],
                idempotency_key=f"admission_{turn_id}",
            )
            cache = SessionCache(store)
            caches.append(cache)
            assembler = ContextAssembler(
                memory=_Memory(),
                guardrails=store,
                llm=_LLM(),
                session_cache=cache,
                session_manager=_SessionManager(),
                compaction_threshold=0.85,
            )
            kwargs = dict(
                session=session,
                agent=agent,
                conversation=_conversation(),
                user_message=text,
                user_message_metadata=metadata,
                routing_reminder=reminder,
                required_turn_id=turn_id,
                skip_memory=skip_memory,
                tool_definitions=[],
            )
            result = await assembler.assemble(**kwargs)
            routing = [
                item for item in result.audit_messages if item["source"] == "routing_reminder"
            ]
            assert len(routing) == (1 if reminder else 0)
            if reminder:
                assert routing[0]["metadata"]["replayable"] is True
                assert routing[0]["metadata"]["canonical_role"] == "developer"
                assert "later requests" in routing[0]["content"]
            for provider, api in (
                (SimpleNamespace(config={"preset": "anthropic"}), "chat"),
                (None, "responses"),
            ):
                payload = project_messages_for_provider(
                    result.messages, provider=provider, llm_api=api
                ).messages
                previous = previous_payloads.get(api, [])
                assert payload[: len(previous)] == previous
                previous_payloads[api] = payload
            await loop._record_outgoing_audit_messages(
                SimpleNamespace(turn_id=turn_id), audit_messages=result.audit_messages
            )
            await cache.refresh(session)
            repeated = await assembler.assemble(**kwargs)
            assert not [
                item for item in repeated.audit_messages if item["source"] == "routing_reminder"
            ], "Same-turn reassembly must not duplicate a delivered routing notice"
            for provider, api in (
                (SimpleNamespace(config={"preset": "anthropic"}), "chat"),
                (None, "responses"),
            ):
                replayed = project_messages_for_provider(
                    repeated.messages, provider=provider, llm_api=api
                ).messages
                assert replayed[: len(previous_payloads[api])] == previous_payloads[api]
            await store.record_events(
                events=[SessionEvent(type="assistant_message", data={"content": "Done."})],
                idempotency_key=f"response_{turn_id}",
            )
    finally:
        for cache in caches:
            await cache.aclose()


@pytest.mark.asyncio
async def test_within_turn_delivery_commits_once_and_cold_cache_replays_projection() -> None:
    store = _EventStore()
    await store.record_events(
        events=[
            SessionEvent(type="user_message", data={"content": "Inspect the repository."}),
            SessionEvent(
                type="tool_call",
                data={
                    "call_id": "call_delivery_read",
                    "name": "read",
                    "arguments": {"path": "/repo"},
                    "provider_arguments_json": '{ "path" : "/repo" }',
                },
            ),
            SessionEvent(
                type="tool_result",
                data={
                    "call_id": "call_delivery_read",
                    "name": "read",
                    "result": "multibyte 漢字\n" * 900,
                    "recovery_call_id": "call_delivery_read",
                },
            ),
        ],
        idempotency_key="delivery_initial_events",
    )
    session, agent, cache, assembler = await _projection_runtime(store)
    ctx = SimpleNamespace(
        session=session,
        agent=agent,
        turn_id="turn_context_delivery",
        execution_fence=None,
        pending_events=[],
    )
    loop = object.__new__(AgentLoop)
    loop.context_assembler = assembler
    loop._record_events_strict = AsyncMock()
    decisions = {"call_delivery_read": [_operation("compact_result")]}
    original = events_to_messages(store.events)
    accepted = apply_projection_decisions(original, decisions)
    reads_before = store.reads
    await loop._commit_context_delivery(
        ctx,
        audit_messages=[],
        projection_decisions=decisions,
        on_token=None,
    )
    writes = len(store.writes)
    await loop._commit_context_delivery(
        ctx,
        audit_messages=[],
        projection_decisions=decisions,
        on_token=None,
    )
    assert len(store.writes) == writes
    assert store.reads == reads_before
    # A new cache has neither Redis nor any accepted in-memory prompt.
    cold = SessionCache(store)
    await cold.refresh(session)
    replay = events_to_messages(
        cold.get_events_since_compaction(session.session_id),
        projection_decisions=cold.get_projection_decisions(session.session_id),
    )
    for provider, api in (
        (SimpleNamespace(config={"preset": "anthropic"}), "chat"),
        (None, "responses"),
    ):
        assert project_messages_for_provider(accepted, provider=provider, llm_api=api).messages == (
            project_messages_for_provider(replay, provider=provider, llm_api=api).messages
        )
    assert ContextAssembler._collect_audit_messages(replay) == []
    await cache.aclose()
    await cold.aclose()


@pytest.mark.asyncio
async def test_cancel_after_projection_ack_invalidates_then_reconciles_without_duplicate() -> None:
    store = _EventStore()
    session, agent, cache, assembler = await _projection_runtime(store)
    decisions = {"call_delivery_cancel": [_operation("compact_result")]}
    store.cancel_after_accept = True
    with pytest.raises(asyncio.CancelledError):
        await assembler.persist_projection_decisions(
            session=session, agent=agent, decisions=decisions
        )
    entry = cache.get_entry(session.session_id)
    assert entry is None or entry.canonical_stale
    await cache.refresh(session)
    assert cache.get_projection_decisions(session.session_id) == decisions
    await assembler.persist_projection_decisions(session=session, agent=agent, decisions=decisions)
    assert len(store.events) == 1
    await cache.aclose()


@pytest.mark.asyncio
async def test_projection_write_failure_blocks_delivery() -> None:
    loop = object.__new__(AgentLoop)
    loop._record_outgoing_audit_messages = AsyncMock()
    loop.context_assembler = SimpleNamespace(
        persist_projection_decisions=AsyncMock(
            side_effect=ImmutablePrefixUnavailable("write rejected", reason="record_failed")
        )
    )
    ctx = SimpleNamespace(session=None, agent=None, execution_fence=None, pending_events=[])
    with pytest.raises(ImmutablePrefixUnavailable):
        await loop._commit_context_delivery(
            ctx,
            audit_messages=[],
            projection_decisions={"call_failure": [_operation("compact_result")]},
            on_token=None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("assemble_first", [False, True])
@pytest.mark.parametrize("retry_before_commit", [False, True])
async def test_actual_live_threshold_selection_survives_restart_and_next_under_threshold_cycle(
    assemble_first: bool,
    retry_before_commit: bool,
) -> None:
    store = _EventStore()
    initial = [SessionEvent(type="user_message", data={"content": "Inspect all files."})]
    for index in range(45):
        call_id = f"call_threshold_read_{index}"
        initial.extend(
            [
                SessionEvent(
                    type="tool_call",
                    data={
                        "call_id": call_id,
                        "name": "read",
                        "arguments": {"path": f"/repo/{index}"},
                    },
                ),
                SessionEvent(
                    type="tool_result",
                    data={
                        "call_id": call_id,
                        "name": "read",
                        "result": f"Result {index}\n" + "content " * 2500,
                        "recovery_call_id": call_id,
                    },
                ),
            ]
        )
    await store.record_events(events=initial, idempotency_key="live_threshold_initial")
    session, agent, cache, assembler = await _projection_runtime(store)
    original = events_to_messages(store.events)
    loop = object.__new__(AgentLoop)
    loop.providers = SimpleNamespace(
        llm=SimpleNamespace(
            count_tokens=lambda text, _model=None: len(str(text)) // 4,
            count_messages_tokens=lambda messages, _model: sum(
                len(str(message.get("content") or "")) // 4 + 4 for message in messages
            ),
        )
    )
    loop.context_assembler = assembler
    loop._record_events_strict = AsyncMock()
    if assemble_first:
        assembler.llm = loop.providers.llm
        original = assembler._finalize_assembled_messages(
            messages=original,
            resolved_model="test-model",
            max_context_tokens=1_000_000,
            available_prompt_tokens=1_000_000,
            max_prompt_tokens=1_000_000,
            tool_schema_tokens=0,
        )[0]
    ctx = SimpleNamespace(
        session=session,
        agent=agent,
        turn_id="turn_live_threshold",
        pending_events=[],
        current_model="test-model",
        current_model_info=SimpleNamespace(
            max_input_tokens=100_000,
            max_output_tokens=0,
        ),
        current_provider_id=None,
        projection_state=None,
        execution_fence=None,
    )
    projected = loop._project_model_messages_for_budget(
        ctx,
        messages=deepcopy(original),
        tool_schemas=[],
        resolved_model="test-model",
        max_context_tokens=100_000,
    )
    assert projected.decisions
    if retry_before_commit:
        persist = assembler.persist_projection_decisions
        assembler.persist_projection_decisions = AsyncMock(
            side_effect=ImmutablePrefixUnavailable("write rejected", reason="record_failed")
        )
        with pytest.raises(ImmutablePrefixUnavailable):
            await loop._commit_context_delivery(
                ctx, audit_messages=[], projection_decisions=projected.decisions, on_token=None
            )
        assembler.persist_projection_decisions = persist
        previous = projected
        skips = ctx.projection_state.skip_count
        projected = await loop._project_model_messages_for_budget_offloaded(
            ctx,
            messages=deepcopy(original),
            tool_schemas=[],
            resolved_model="test-model",
            max_context_tokens=100_000,
        )
        assert ctx.projection_state.skip_count > skips
        assert projected.messages == previous.messages
        assert projected.decisions == previous.decisions, (
            "A cached retry must retain the decisions needed to persist its rendering"
        )
    await loop._commit_context_delivery(
        ctx,
        audit_messages=[],
        projection_decisions=projected.decisions,
        on_token=None,
    )
    cold = SessionCache(store)
    await cold.refresh(session)
    replay = events_to_messages(
        cold.get_events_since_compaction(session.session_id),
        projection_decisions=cold.get_projection_decisions(session.session_id),
    )
    for provider, api in (
        (SimpleNamespace(config={"preset": "anthropic"}), "chat"),
        (None, "responses"),
    ):
        assert (
            project_messages_for_provider(
                projected.messages,
                provider=provider,
                llm_api=api,
            ).messages
            == project_messages_for_provider(replay, provider=provider, llm_api=api).messages
        )
    # A new turn seeds from canonical decisions, not from the previous rich list.
    ctx.projection_state = None
    replay.append({"role": "user", "content": "Continue after projection."})
    unchanged = loop._project_model_messages_for_budget(
        ctx,
        messages=replay,
        tool_schemas=[],
        resolved_model="test-model",
        max_context_tokens=100_000,
    )
    assert not unchanged.decisions
    await cache.aclose()
    await cold.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("effort", ["high", "xhigh"])
async def test_native_responses_message_survives_cold_replay_and_effort_switch(effort: str) -> None:
    from uuid import uuid4

    from cognis.core.agent_loop import _attach_responses_output_items
    from cognis.providers.llm.litellm import _apply_responses_request_defaults
    from cognis.providers.llm.responses_bridge import messages_to_responses_input

    content = "Inspecting the result. 漢字"
    native = [
        {"type": "reasoning", "id": "rs_delivery", "encrypted_content": "opaque", "summary": []},
        {
            "type": "message",
            "id": "msg_delivery",
            "role": "assistant",
            "status": "completed",
            "phase": "commentary",
            "content": [{"type": "output_text", "text": content, "annotations": []}],
        },
    ]
    live = {"role": "assistant", "content": content}
    _attach_responses_output_items(live, native, durable=False)
    data = {"content": content}
    _attach_responses_output_items(data, native, durable=True)
    store = _EventStore()
    await store.record_events(
        events=[
            SessionEvent(type="user_message", data={"content": "Inspect the result."}),
            SessionEvent(type="assistant_message", data=data),
        ],
        idempotency_key="native_message_initial",
    )
    session, _, cache, _ = await _projection_runtime(store)
    session.session_id = f"sess_{uuid4().hex}"
    cold = SessionCache(store)
    try:
        await cold.refresh(session)
        replay = events_to_messages(cold.get_events_since_compaction(session.session_id))
        accepted = messages_to_responses_input(
            [{"role": "user", "content": "Inspect the result."}, live]
        )
        # A profile/effort switch reconstructs from canonical events, then appends updates.
        replay.append({"role": "system", "content": "Continue the request with the new profile."})
        rebuilt = messages_to_responses_input(replay)
        assert rebuilt[: len(accepted)] == accepted
        provider = SimpleNamespace(
            provider_id="codex",
            backend="litellm",
            location="controller",
            config={"preset": "chatgpt", "codex_transport": "direct"},
        )
        requests = [
            _apply_responses_request_defaults(
                {"reasoning": {"effort": value}},
                provider=provider,
                resolved_model="gpt-6.1-sol",
                instructions="Unchanged instructions.",
                session_id=session.session_id,
            )
            for value in ("high", effort)
        ]
        assert requests[0]["prompt_cache_key"] == requests[1]["prompt_cache_key"]
        assert requests[0]["instructions"] == requests[1]["instructions"]
    finally:
        await cache.aclose()
        await cold.aclose()


def test_parallel_tool_group_omission_is_one_indivisible_decision() -> None:
    before = [
        {"role": "user", "content": "Inspect"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": "read", "arguments": "{}"}}
                for call_id in ("call_parallel_one", "call_parallel_two")
            ],
        },
        {"role": "tool", "tool_call_id": "call_parallel_one", "content": "first"},
        {"role": "tool", "tool_call_id": "call_parallel_two", "content": "second"},
        {"role": "user", "content": "Continue"},
    ]
    after = [before[0], before[-1]]
    decisions = projection_decisions_from_diff(before, after)
    assert decisions == {"call_parallel_one": [_operation("omit_tool_group")]}
    assert apply_projection_decisions(before, decisions) == after
    assert apply_projection_decisions(after, decisions) == after
    assert len(projection_decision_batches(decisions)) == 1


def test_projection_batches_bound_actual_multibyte_json_and_never_copy_content() -> None:
    decisions = {
        f'call_{index}_漢字"\\': [_operation("compact_result"), _operation("compact_attachment")]
        for index in range(2000)
    }
    batches = projection_decision_batches(decisions, max_bytes=4096)
    assert len(batches) > 1
    for data in batches:
        encoded = json.dumps(
            [SessionEvent(type="lifecycle", data=data).model_dump()],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        assert len(encoded) <= 4096
        assert set(data) == {"event", "decisions"}
        assert all(
            set(item) == {"call_id", "operation", "rendering_policy_version", "parameters"}
            for item in data["decisions"]
        )
        counts = {}
        for item in data["decisions"]:
            counts[item["call_id"]] = counts.get(item["call_id"], 0) + 1
        assert set(counts.values()) == {2}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output_continuation,fallback", [(False, False), (True, False), (False, True)]
)
async def test_real_loop_preserves_provider_prefix_and_canonical_history(
    output_continuation: bool,
    fallback: bool,
) -> None:
    from cognis.core.agent_loop import CHAT_POLICY, PauseWaiter, SessionLock, StepContext
    from cognis.core.tool_exposure import LLMApiMode, ToolDiscoveryMode, ToolExposureContract
    from cognis.models.config import ModelInfo
    from cognis.models.workflow import StepDefinition
    from tests.unit.test_agent_loop import (
        _FakeContextAssembler,
        _FakeReminderLLM,
        _NoopEventBus,
        _NoopRememberQueue,
        _NoopSessionCache,
        _NoopSessionManager,
    )

    store = _EventStore()
    session, agent, cache, projection_assembler = await _projection_runtime(store)
    if fallback:
        history = []
        for index in range(45):
            call_id = f"call_fallback_read_{index}"
            history.extend(
                [
                    SessionEvent(
                        type="tool_call",
                        data={
                            "call_id": call_id,
                            "name": "read",
                            "arguments": {"path": f"/repo/{index}"},
                        },
                    ),
                    SessionEvent(
                        type="tool_result",
                        data={
                            "call_id": call_id,
                            "name": "read",
                            "result": "source " * 3000,
                            "recovery_call_id": call_id,
                        },
                    ),
                ]
            )
        await store.record_events(events=history, idempotency_key="fallback_history")
        await cache.refresh(session)

    class Assembler(_FakeContextAssembler):
        async def assemble(self, **kwargs):
            result = await super().assemble(**kwargs)
            result.messages = events_to_messages(store.events)
            _append_routing_reminder(
                result.messages,
                "Inspect safely for this request.",
                turn_id=kwargs["required_turn_id"],
            )
            _append_executor_pool_reminder(
                result.messages, executor_pool=_executor_pool(), active_executor_id="exec-primary"
            )
            result.audit_messages = ContextAssembler._collect_audit_messages(result.messages)
            return result

    class LLM(_FakeReminderLLM):
        async def get_model_info(self, model, **kwargs):
            if not fallback:
                return await super().get_model_info(model, **kwargs)
            capacity = 100_000 if model == "fallback-model" else 1_000_000
            return ModelInfo(model_id=model, context_window=capacity, max_input_tokens=capacity)

        def count_tokens(self, text, model=None):
            return len(str(text)) // 4

        def count_messages_tokens(self, messages, model=None):
            return sum(len(str(m.get("content") or "")) // 4 + 4 for m in messages)

        async def resolve_tool_exposure_contract(self, **kwargs):
            return ToolExposureContract(LLMApiMode.CHAT_COMPLETIONS, ToolDiscoveryMode.NONE)

        async def stream_generate(self, messages, **kwargs):
            for message in messages:
                if message.get("_audit_source") == "routing_reminder":
                    assert any(
                        event["data"].get("source") == "routing_reminder"
                        and event["data"].get("content") == message["content"]
                        and event["data"].get("replayable") is True
                        for event in store.events
                    ), "Routing notices must be canonical before provider inference"
            if fallback:
                prepared = await kwargs["cognis_prepare_candidate"](
                    SimpleNamespace(
                        target=SimpleNamespace(model="fallback-model", provider_id=None),
                    )
                )
                assert any(
                    event["data"].get("event") == "context_projection" for event in store.events
                ), "Fallback must commit its projection decisions before provider inference"
                messages = prepared.messages
            self.calls.append(deepcopy(messages))
            if output_continuation and len(self.calls) == 1:
                yield {
                    "choices": [
                        {"delta": {"content": "First response segment."}, "finish_reason": "length"}
                    ]
                }
            else:
                yield {
                    "choices": [
                        {
                            "delta": {"content": "Completed response segment."},
                            "finish_reason": "stop",
                        }
                    ]
                }

    llm = LLM()
    if fallback:
        llm.inference_recovery = SimpleNamespace()
    assembler = Assembler(max_context_tokens=1_000_000 if fallback else 0)
    assembler.persist_projection_decisions = projection_assembler.persist_projection_decisions
    loop = AgentLoop(
        providers=SimpleNamespace(llm=llm, guardrails=store),
        session_manager=_NoopSessionManager(),
        session_cache=_NoopSessionCache(),
        context_assembler=assembler,
        compaction_strategy=SimpleNamespace(),
        tool_router=SimpleNamespace(),
        remember_queue=_NoopRememberQueue(),
        event_bus=_NoopEventBus(),
        session_lock=SessionLock(),
        pause_waiter=PauseWaiter(),
    )
    for turn in range(1 if fallback else 2):
        text = f"Inspect repository, turn {turn}."
        await store.record_events(
            events=[SessionEvent(type="user_message", data={"content": text})],
            idempotency_key=f"admission_delivery_{turn}",
        )
        ctx = StepContext(
            step_definition=StepDefinition(name="direct", type="run", prompt=""),
            session=session,
            conversation=SimpleNamespace(
                conversation_id=session.conversation_id,
                title=None,
                title_source="unset",
            ),
            agent=agent,
            policy=CHAT_POLICY,
            user_message=text,
            user_attachments=[],
            system_initiated=False,
            turn_id=f"turn_delivery_{turn}",
        )
        await loop.run_step(ctx)
    cold = SessionCache(store)
    await cold.refresh(session)
    for provider, api in (
        (SimpleNamespace(config={"preset": "anthropic"}), "chat"),
        (None, "responses"),
    ):
        payloads = [
            project_messages_for_provider(messages, provider=provider, llm_api=api).messages
            for messages in llm.calls
        ]
        for previous, following in zip(payloads, payloads[1:], strict=False):
            assert following[: len(previous)] == previous, (
                [(m["role"], str(m.get("content"))[:70]) for m in previous],
                [(m["role"], str(m.get("content"))[:70]) for m in following],
            )
        replay = project_messages_for_provider(
            events_to_messages(
                store.events,
                projection_decisions=cold.get_projection_decisions(session.session_id),
            ),
            provider=provider,
            llm_api=api,
        ).messages
        assert replay[: len(payloads[-1])] == payloads[-1]
    notices = [
        event for event in store.events if event["data"].get("source") == "executor_pool_reminder"
    ]
    assert len(notices) == 1
    assert notices[0]["data"]["replayable"] is True
    routing_notices = [
        event for event in store.events if event["data"].get("source") == "routing_reminder"
    ]
    assert len(routing_notices) == (1 if fallback else 2)
    await cache.aclose()
    await cold.aclose()
