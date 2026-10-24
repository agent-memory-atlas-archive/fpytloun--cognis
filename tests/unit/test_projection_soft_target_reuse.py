"""Soft sizing goals must not rewrite an accepted, still-safe provider prefix."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from cognis.core.agent_loop import AgentLoop, ProjectedMessages, StepInterrupted
from cognis.core.context_projection import (
    PressureMode,
    ProjectionPolicy,
    ProjectionResult,
    ProjectionTurnState,
    apply_projection_decisions,
    projection_source_fingerprint,
    tool_transcript_prefix_fingerprint,
)
from cognis.core.message_markers import PROTECTED_TOOL_OUTPUT
from cognis.core.session_cache import SessionCache
from cognis.models.session import SessionEvent
from cognis.providers.llm.anthropic.integration import _convert_messages
from cognis.providers.llm.responses_bridge import messages_to_responses_input
from tests.unit.test_context_delivery import _EventStore, _projection_runtime

LARGE_CALL = "call_abc5ab37a31e4a28a56da007bd49a5e8"
COMPACT = {"operation": "compact_result", "rendering_policy_version": 1, "parameters": {}}


def _runtime(
    *,
    candidate_tokens: int = 230_000,
    mode: PressureMode = PressureMode.pressure,
) -> tuple[AgentLoop, SimpleNamespace, list[dict], Mock]:
    raw = [
        {"role": "user", "content": "Inspect the evidence."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": LARGE_CALL,
                    "type": "function",
                    "function": {"name": "read", "arguments": '{ "path": "src" }'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": LARGE_CALL,
            "content": "Earlier evidence\n" * 2_000,
            "_tool_name": "read",
            "_recovery_call_id": LARGE_CALL,
        },
        {"role": "user", "content": "Continue."},
        {
            "role": "developer",
            "content": "Protected execution evidence.",
            PROTECTED_TOOL_OUTPUT: True,
        },
    ]
    decisions = {LARGE_CALL: [COMPACT]}
    accepted = apply_projection_decisions(raw, decisions)
    policy = ProjectionPolicy.from_budget(
        max_context_tokens=400_000,
        available_prompt_tokens=250_240,
        phase="within_turn",
        pressure_mode=mode,
    )
    state = ProjectionTurnState(
        turn_id="turn_soft_target_reuse",
        policy=policy,
        pressure_mode=mode,
        last_result=ProjectionResult(
            messages=accepted, mutable_start_index=0, decisions=deepcopy(decisions)
        ),
        last_message_count=len(raw),
        last_projected_token_estimate=225_000,
        last_prefix_fingerprint=tool_transcript_prefix_fingerprint(raw),
        last_source_fingerprint=projection_source_fingerprint(raw),
    )
    ctx = SimpleNamespace(
        current_model="gpt-6-astra",
        current_model_info=SimpleNamespace(max_input_tokens=272_000, max_output_tokens=0),
        agent=SimpleNamespace(llm_config=None),
        session=SimpleNamespace(session_id="sess_soft_target_reuse"),
        turn_id=state.turn_id,
        projection_state=state,
        last_projection_snapshot=SimpleNamespace(prompt_tokens=225_000),
        cancel_event=None,
        execution_fence=None,
        pending_events=[],
    )

    def count_messages(messages: list[dict], _model: str) -> int:
        if messages == [{"role": "user", "content": "Budget recovery"}]:
            return 100_000
        if any(message.get("content") == raw[2]["content"] for message in messages):
            return 260_000
        return candidate_tokens

    loop = object.__new__(AgentLoop)
    loop.providers = SimpleNamespace(
        llm=SimpleNamespace(
            count_messages_tokens=Mock(side_effect=count_messages),
            count_tokens=Mock(return_value=18_000),
        )
    )
    reproject = Mock(
        return_value=ProjectedMessages(
            messages=[{"role": "user", "content": "Budget recovery"}],
            snapshot=None,
            mode="critical",
        )
    )
    loop._project_model_messages = reproject
    return loop, ctx, raw, reproject


def _project(loop: AgentLoop, ctx: SimpleNamespace, messages: list[dict], **kwargs):
    return loop._project_model_messages_for_budget(
        ctx,
        messages=messages,
        tool_schemas=kwargs.pop("tool_schemas", []),
        resolved_model="gpt-6-astra",
        max_context_tokens=400_000,
        **kwargs,
    )


@pytest.mark.parametrize("mode", [PressureMode.normal, PressureMode.pressure])
@pytest.mark.parametrize("candidate_tokens", [230_000, 237_727])
def test_soft_target_reuses_accepted_prefix_below_all_safety_gates(
    mode: PressureMode,
    candidate_tokens: int,
) -> None:
    loop, ctx, raw, reproject = _runtime(candidate_tokens=candidate_tokens, mode=mode)
    accepted = deepcopy(ctx.projection_state.last_result.messages)
    decisions = deepcopy(ctx.projection_state.last_result.decisions)
    tail = {"role": "user", "content": "New evidence to consider."}
    working = [*raw, tail]
    original = deepcopy(working)

    result = _project(loop, ctx, working)

    reproject.assert_not_called()
    assert result.messages == [*accepted, tail]
    assert working == original
    assert result.decisions == decisions
    assert result.snapshot.prompt_tokens == candidate_tokens
    assert not result.snapshot.exceeded
    assert ctx.projection_state.skip_count == 1
    assert ctx.projection_state.reproject_count == 0
    assert ctx.projection_state.last_message_count == len(working)
    assert messages_to_responses_input(result.messages) == messages_to_responses_input(
        [*accepted, tail]
    )
    assert _convert_messages(result.messages) == _convert_messages([*accepted, tail])


@pytest.mark.parametrize("candidate_tokens", [237_728, 240_211, 245_236])
def test_soft_target_reuse_retains_exact_pressure_and_hard_budget_guards(
    candidate_tokens: int,
) -> None:
    loop, ctx, raw, reproject = _runtime(candidate_tokens=candidate_tokens)
    result = _project(loop, ctx, [*raw, {"role": "user", "content": "Continue."}])

    reproject.assert_called()
    assert ctx.projection_state.forced_critical_count == 1
    assert result.messages == [{"role": "user", "content": "Budget recovery"}]


@pytest.mark.parametrize(
    "condition",
    [
        "changed_prefix",
        "shortened_prefix",
        "unknown_prefix",
        "unknown_source",
        "changed_tool_result",
        "changed_native_content",
        "oversized_tail",
        "pressure_transition",
        "critical_pressure",
        "initial_projection",
    ],
)
def test_soft_target_reuse_does_not_bypass_other_projection_triggers(condition: str) -> None:
    loop, ctx, raw, reproject = _runtime()
    working = [*raw, {"role": "user", "content": "New evidence."}]
    if condition == "changed_prefix":
        working = deepcopy(working)
        working[0]["content"] = "Revised execution context."
    elif condition == "shortened_prefix":
        working = raw[:-1]
    elif condition == "unknown_prefix":
        ctx.projection_state.last_prefix_fingerprint = None
    elif condition == "unknown_source":
        ctx.projection_state.last_source_fingerprint = None
    elif condition == "changed_tool_result":
        working = deepcopy(working)
        working[2]["content"] += "Additional evidence."
    elif condition == "changed_native_content":
        working = deepcopy(working)
        working[1]["_responses_output_items"] = [{"type": "message", "content": []}]
    elif condition == "oversized_tail":
        working[-1] = {
            "role": "tool",
            "tool_call_id": "call_d40d0c4bc9f0469f90068429563816f2",
            "content": "New large evidence",
            "_token_estimate": 10_000,
        }
    elif condition == "pressure_transition":
        ctx.projection_state.pressure_mode = PressureMode.normal
        ctx.projection_state.last_projected_token_estimate = 235_000
        ctx.last_projection_snapshot.prompt_tokens = 235_000
    elif condition == "critical_pressure":
        ctx.projection_state.pressure_mode = PressureMode.critical
        ctx.projection_state.last_projected_token_estimate = 244_000
        ctx.last_projection_snapshot.prompt_tokens = 244_000
    elif condition == "initial_projection":
        ctx.projection_state.last_result = None

    _project(loop, ctx, working)
    reproject.assert_called()


def test_soft_target_reuse_counts_current_schema_overhead() -> None:
    loop, ctx, raw, reproject = _runtime(candidate_tokens=230_000)
    schemas = [{"type": "function", "function": {"name": "read", "parameters": {}}}]
    _project(loop, ctx, [*raw, {"role": "user", "content": "Continue."}], tool_schemas=schemas)

    reproject.assert_called()
    assert ctx.projection_state.forced_critical_count == 1
    loop.providers.llm.count_tokens.assert_called()


def test_soft_target_reuse_respects_calibrated_pressure_boundary() -> None:
    loop, ctx, raw, reproject = _runtime(candidate_tokens=230_000)
    ctx.current_provider_id = "codex"
    calibration = Mock(
        side_effect=lambda _session, **kwargs: (
            237_728 if kwargs["raw_prompt_tokens"] == 230_000 else kwargs["raw_prompt_tokens"],
            {"ratio": 237_728 / 230_000},
        )
    )
    loop.session_cache = SimpleNamespace(apply_prompt_token_calibration=calibration)

    _project(loop, ctx, [*raw, {"role": "user", "content": "Continue."}])

    reproject.assert_called()
    assert ctx.projection_state.forced_critical_count == 1
    assert any(call.kwargs["raw_prompt_tokens"] == 230_000 for call in calibration.call_args_list)


def test_mutable_token_estimates_do_not_disable_source_identity() -> None:
    loop, ctx, raw, reproject = _runtime()
    raw[2]["_token_estimate"] = 42
    _project(loop, ctx, [*raw, {"role": "user", "content": "Continue."}])
    reproject.assert_not_called()


@pytest.mark.parametrize("missing_count", ["all", "candidate"])
def test_unavailable_exact_count_retains_original_projection_without_false_critical(
    missing_count: str,
) -> None:
    loop, ctx, raw, reproject = _runtime()
    counter = loop.providers.llm.count_messages_tokens.side_effect

    def unavailable(messages: list[dict], model: str) -> int:
        count = counter(messages, model)
        if missing_count == "all" or count == 230_000:
            raise RuntimeError("Token estimator unavailable")
        return count

    loop.providers.llm.count_messages_tokens.side_effect = unavailable
    _project(loop, ctx, [*raw, {"role": "user", "content": "Continue."}])

    reproject.assert_called_once()
    assert reproject.call_args.kwargs["pressure_mode"] == "pressure"
    assert ctx.projection_state.forced_critical_count == 0


@pytest.mark.parametrize(
    ("mode", "candidate_tokens"), [(PressureMode.normal, 230_000), (PressureMode.pressure, 237_700)]
)
def test_repeated_soft_reuse_keeps_accepted_history_and_pending_decisions(
    mode: PressureMode,
    candidate_tokens: int,
) -> None:
    loop, ctx, raw, reproject = _runtime(candidate_tokens=candidate_tokens, mode=mode)
    expected = deepcopy(ctx.projection_state.last_result.messages)
    decisions = deepcopy(ctx.projection_state.last_result.decisions)
    working = list(raw)
    for index in range(3):
        tail = {"role": "user", "content": f"Additional observation {index}."}
        working.append(tail)
        expected.append(tail)
        result = _project(loop, ctx, working)
        ctx.last_projection_snapshot = result.snapshot
        assert result.messages == expected
        assert result.decisions == decisions
    reproject.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_before_publish", [False, True])
async def test_soft_reuse_offload_publishes_fingerprint_only_after_cancellation_check(
    cancel_before_publish: bool,
) -> None:
    loop, ctx, raw, reproject = _runtime()
    original = ctx.projection_state
    prior_fingerprint = original.last_source_fingerprint
    ctx.cancel_event = asyncio.Event()
    if cancel_before_publish:
        ctx.cancel_event.set()
    operation = loop._project_model_messages_for_budget_offloaded(
        ctx,
        messages=[*raw, {"role": "user", "content": "New evidence."}],
        tool_schemas=[],
        resolved_model="gpt-6-astra",
        max_context_tokens=400_000,
    )
    if cancel_before_publish:
        with pytest.raises(StepInterrupted):
            await operation
        assert ctx.projection_state is original
    else:
        result = await operation
        assert ctx.projection_state is not original
        assert ctx.projection_state.last_source_fingerprint != prior_fingerprint
        assert result.decisions == original.last_result.decisions
    assert original.last_source_fingerprint == prior_fingerprint
    reproject.assert_not_called()


@pytest.mark.asyncio
async def test_soft_reuse_retries_pending_decisions_through_durable_delivery() -> None:
    loop, ctx, raw, reproject = _runtime(mode=PressureMode.normal)
    store = _EventStore()
    await store.record_events(
        events=[
            SessionEvent(type="user_message", data={"content": raw[0]["content"]}),
            SessionEvent(
                type="tool_call", data={"call_id": LARGE_CALL, "name": "read", "arguments": {}}
            ),
            SessionEvent(
                type="tool_result",
                data={
                    "call_id": LARGE_CALL,
                    "name": "read",
                    "result": raw[2]["content"],
                    "recovery_call_id": LARGE_CALL,
                },
            ),
        ],
        idempotency_key="soft_reuse_original_events",
    )
    session, agent, cache, assembler = await _projection_runtime(store)
    cold = SessionCache(store)
    ctx.session, ctx.agent = session, agent
    loop.context_assembler = assembler
    loop._record_events_strict = AsyncMock()
    try:
        first = _project(loop, ctx, raw)
        store.cancel_after_accept = True
        with pytest.raises(asyncio.CancelledError):
            await loop._commit_context_delivery(
                ctx, audit_messages=[], projection_decisions=first.decisions, on_token=None
            )
        second = _project(loop, ctx, raw)
        assert second.decisions == first.decisions
        await loop._commit_context_delivery(
            ctx, audit_messages=[], projection_decisions=second.decisions, on_token=None
        )
        await cold.refresh(session)
        durable = cold.get_projection_decisions(session.session_id)
        assert durable == first.decisions
        assert (
            len(
                [
                    event
                    for event in store.events
                    if event["data"].get("event") == "context_projection"
                ]
            )
            == 1
        )
        assert apply_projection_decisions(raw, durable) == first.messages
        reproject.assert_not_called()
    finally:
        await cache.aclose()
        await cold.aclose()
