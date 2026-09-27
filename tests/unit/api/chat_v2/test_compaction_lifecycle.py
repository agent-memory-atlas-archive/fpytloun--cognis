"""Compaction occurrence replay and runtime ordering contracts."""

import pytest

from cognis.api.chat_v2.event_store import RawSessionEvent
from cognis.api.chat_v2.normalizer import normalize_session_events
from cognis.api.chat_v2.projector import project_timeline
from cognis.api.chat_v2.realtime import compaction_runtime_item


def event(seq: int, status: str) -> RawSessionEvent:
    return RawSessionEvent(
        store_id="intaris",
        session_id="source",
        seq=seq,
        type="lifecycle",
        data={
            "event": "session_compaction_started"
            if status == "running"
            else "session_compaction_finished",
            "compaction_id": "compact-recovery",
            "status": status,
            "turn_id": "active-turn",
            "phase": "mid_turn",
        },
    )


@pytest.mark.parametrize("status", ["compacted", "failed", "skipped"])
@pytest.mark.parametrize("reversed_delivery", [False, True])
def test_terminal_occurrence_wins_without_moving_start(
    status: str, reversed_delivery: bool
) -> None:
    events = [event(10, "running"), event(20, status)]
    if reversed_delivery:
        events.reverse()
    items = project_timeline(normalize_session_events(events).events).timeline.items
    assert len(items) == 1
    assert items[0].id == "compaction:compact-recovery"
    assert items[0].status == status


def test_reload_projects_durable_start() -> None:
    items = project_timeline(normalize_session_events([event(10, "running")]).events).timeline.items
    assert len(items) == 1
    assert items[0].status == "running"


def test_pressure_reason_uses_binding_projection_limit() -> None:
    from cognis.core.agent_loop import (
        CompactionRunContext,
        ContextPressureSnapshot,
        ProjectedMessages,
    )
    from cognis.core.context_projection import ProjectionPolicy

    snapshot = ContextPressureSnapshot(
        prompt_tokens=668585,
        max_context_tokens=1000000,
        max_input_tokens=872000,
        reserve_output_tokens=128000,
        effective_reserve_output_tokens=32768,
        available_prompt_tokens=839232,
        threshold_prompt_tokens=797270,
        exceeded=False,
        reason="within_budget",
    )
    run = CompactionRunContext.from_snapshot(
        snapshot, trigger="tool_loop_pressure", reason="pressure"
    )
    run.apply_projection_boundary(
        ProjectedMessages(
            messages=[],
            snapshot=snapshot,
            policy=ProjectionPolicy.from_budget(
                max_context_tokens=1000000,
                available_prompt_tokens=839232,
            ),
        )
    )
    assert run.compaction_threshold_prompt_tokens == 660000
    assert run.hard_pressure_exceeded
    assert "668,585" in run.reason and "660,000" in run.reason
    assert "797,270" not in run.reason


def test_idle_start_is_superseded_by_new_owner_occurrence() -> None:
    old = event(10, "running")
    old.data["turn_id"] = None
    new = event(20, "running")
    new.data.update(compaction_id="compact-next-owner", turn_id=None)
    items = project_timeline(normalize_session_events([old, new]).events).timeline.items
    assert [item.status for item in items] == ["failed", "running"]


def test_mid_turn_runtime_uses_active_phase_not_pre_turn_band() -> None:
    item = compaction_runtime_item(
        {
            "session_id": "source",
            "compaction_id": "compact-recovery",
            "phase": "mid_turn",
            "assistant_phase_index": 12,
        }
    )
    assert item is not None
    assert item.sort_key.startswith("9998:")
    assert ":000012:" in item.sort_key


def test_only_successful_correlated_historical_warning_is_hidden() -> None:
    notice = RawSessionEvent(
        store_id="intaris",
        session_id="source",
        seq=9,
        type="lifecycle",
        data={
            "event": "system_notice",
            "kind": "tool_call_context_pressure",
            "compaction_id": "compact-recovery",
            "message": "Context window is critically full; stopping this turn before more tool calls.",
        },
    )
    for status, expected in [("compacted", 1), ("failed", 2)]:
        items = project_timeline(
            normalize_session_events([notice, event(20, status)]).events
        ).timeline.items
        assert len(items) == expected
