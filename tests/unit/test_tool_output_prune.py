"""Tests for the post-step tool output prune."""

from __future__ import annotations

from cognis.core.context_projection import (
    PROJECTION_RENDERING_POLICY_VERSION,
    PressureMode,
    project_messages,
)
from cognis.core.tool_output_prune import (
    PRUNE_PROTECT,
    PRUNE_PROTECTED_TOOL_NAMES,
    PruneCandidate,
    cleared_tool_result_marker,
    prune_candidate_from_event_data,
    select_prune_call_ids,
)


def _candidate(call_id: str, output: str, tool_name: str = "read") -> PruneCandidate:
    return PruneCandidate(call_id=call_id, tool_name=tool_name, output=output)


def _user_turn() -> PruneCandidate:
    return PruneCandidate(call_id="", tool_name="", output="", is_user_turn=True)


def test_prune_candidate_requires_confirmed_recovery_metadata() -> None:
    base = {
        "call_id": "call-1",
        "name": "read",
        "result": "important evidence",
    }

    assert prune_candidate_from_event_data(base) is None
    assert prune_candidate_from_event_data({**base, "has_full_output": True}) is None
    assert (
        prune_candidate_from_event_data(
            {**base, "has_full_output": False, "recovery_call_id": "call-1"}
        )
        is None
    )

    candidate = prune_candidate_from_event_data(
        {**base, "has_full_output": True, "recovery_call_id": "stored-call-1"}
    )
    assert candidate == PruneCandidate(
        call_id="call-1",
        tool_name="read",
        output="important evidence",
    )


def test_prune_returns_empty_when_under_budget() -> None:
    """Below ``PRUNE_PROTECT`` tokens nothing should be pruned."""

    candidates = [
        _candidate("c1", "hello world"),
        _candidate("c2", "more output"),
    ]
    pruned = select_prune_call_ids(
        candidates,
        token_counter=lambda text: len(text.split()),
    )
    assert pruned == set()


def test_prune_drops_oldest_once_budget_exceeded() -> None:
    """Once the cumulative tail exceeds the budget, older calls are pruned."""

    # Two user turns frame the recent window so the walk can prune
    # outside it. With each event costing the full protect budget,
    # any second post-window event is enough to cross the threshold.
    candidates = [
        _user_turn(),
        _candidate("oldest", "x"),
        _candidate("middle", "x"),
        _user_turn(),
        _candidate("newer", "x"),
        _candidate("newest", "x"),
        _user_turn(),
    ]

    def counter(_: str) -> int:
        return PRUNE_PROTECT  # Each event alone fills the budget.

    pruned = select_prune_call_ids(candidates, token_counter=counter)
    # Walk goes newest → oldest. Matches OpenCode's prune semantics:
    # the first event past the user-turn window fits inside the
    # protect budget and is kept; everything strictly older is pruned.
    assert "oldest" in pruned
    assert "middle" not in pruned  # Sits exactly at the budget boundary, kept.
    assert "newer" not in pruned
    assert "newest" not in pruned


def test_prune_protects_recent_user_turns() -> None:
    """Tool results inside the last ``PRUNE_MIN_USER_TURNS`` are kept."""

    candidates = [
        _candidate("ancient", "huge"),
        _user_turn(),
        _candidate("recent", "huge"),
        _user_turn(),
        _candidate("brand_new", "huge"),
    ]

    def counter(_: str) -> int:
        return PRUNE_PROTECT * 5

    pruned = select_prune_call_ids(candidates, token_counter=counter)
    # ``recent`` and ``brand_new`` sit inside the user-turn protection
    # window; only ``ancient`` is eligible.
    assert pruned == {"ancient"}


def test_prune_skips_protected_tool_names() -> None:
    """Skill/system results never get pruned even when budget exceeded."""

    candidates = [
        _candidate("a", "x", tool_name="skill_load"),
        _user_turn(),
        _user_turn(),
        _candidate("b", "x", tool_name="read"),
    ]
    pruned = select_prune_call_ids(
        candidates,
        token_counter=lambda _: PRUNE_PROTECT * 2,
    )
    assert "a" not in pruned
    # All known protected tool names — guard against accidental removal.
    assert "skill_load" in PRUNE_PROTECTED_TOOL_NAMES
    assert "step_complete" in PRUNE_PROTECTED_TOOL_NAMES
    assert "write_deliverable" in PRUNE_PROTECTED_TOOL_NAMES


def test_cleared_marker_includes_call_id_recovery_hint() -> None:
    text = cleared_tool_result_marker("call_abc123")
    assert "call_abc123" in text
    assert "read_tool_output" in text
    assert "cleared" in text.lower()


def test_events_to_messages_replays_a_durable_tool_result_projection() -> None:
    """Pruned tool results render as the clearance marker, not their content."""

    from cognis.core.context import events_to_messages

    events = [
        {
            "type": "tool_call",
            "data": {"name": "read", "call_id": "old-1", "arguments": {"file_path": "a.py"}},
        },
        {
            "type": "tool_result",
            "data": {
                "call_id": "old-1",
                "name": "read",
                "result": "ORIGINAL CONTENT",
                "has_full_output": True,
                "recovery_call_id": "stored-old-1",
            },
        },
        {
            "type": "tool_call",
            "data": {"name": "read", "call_id": "fresh-1", "arguments": {"file_path": "b.py"}},
        },
        {
            "type": "tool_result",
            "data": {"call_id": "fresh-1", "name": "read", "result": "FRESH CONTENT"},
        },
    ]

    messages = events_to_messages(
        events,
        projection_decisions={
            "old-1": [
                {
                    "operation": "compact_result",
                    "rendering_policy_version": PROJECTION_RENDERING_POLICY_VERSION,
                }
            ]
        },
    )

    tool_messages = [m for m in messages if m.get("role") == "tool"]
    by_id = {m["tool_call_id"]: m for m in tool_messages}

    assert "ORIGINAL CONTENT" not in by_id["old-1"]["content"]
    assert "stored-old-1" in by_id["old-1"]["content"]
    assert "read_tool_output" in by_id["old-1"]["content"]
    assert by_id["old-1"].get("_projected_compacted") is True

    # Untouched results must still render their original content.
    assert by_id["fresh-1"]["content"] == "FRESH CONTENT"
    assert by_id["fresh-1"].get("_projected_compacted", False) is False


def test_unrecoverable_results_are_ineligible_and_replay_inline() -> None:
    from cognis.core.context import events_to_messages

    events = [
        {
            "type": "tool_call",
            "data": {"name": "read", "call_id": "old-1", "arguments": {"file_path": "a.py"}},
        },
        {
            "type": "tool_result",
            "data": {"call_id": "old-1", "name": "read", "result": "ORIGINAL CONTENT"},
        },
    ]

    assert prune_candidate_from_event_data(events[1]["data"]) is None
    messages = events_to_messages(events)
    tool_message = next(message for message in messages if message.get("role") == "tool")

    assert tool_message["content"] == "ORIGINAL CONTENT"
    assert tool_message.get("_projected_compacted", False) is False


def test_replayed_protected_results_survive_critical_projection() -> None:
    """Replay retains the protection consumed by the canonical projection policy."""

    from cognis.core.context import events_to_messages

    events = [
        {
            "type": "tool_call",
            "data": {"name": "skill_load", "call_id": "skill-1", "arguments": {"skill_id": "s"}},
        },
        {
            "type": "tool_result",
            "data": {
                "call_id": "skill-1",
                "name": "skill_load",
                "result": "PROTECTED CONTENT" * 1000,
                "protect_from_pruning": True,
            },
        },
    ]

    messages = events_to_messages(events)
    protected = next(message for message in messages if message.get("role") == "tool")
    assert protected["_protected_tool_output"] is True
    messages = project_messages(
        messages,
        preserve_recent_completed_tool_groups=0,
        pressure_mode=PressureMode.critical,
        required_savings_tokens=100_000,
        allow_unrecoverable_projection=True,
    ).messages
    tool_message = next(m for m in messages if m.get("role") == "tool")

    assert tool_message["content"] == "PROTECTED CONTENT" * 1000
    assert tool_message.get("_projected_compacted", False) is False
