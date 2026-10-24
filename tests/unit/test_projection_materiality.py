"""Projection must not rewrite history unless the placeholder materially shrinks it."""

from __future__ import annotations

import json

from cognis.core.context_projection import (
    PressureMode,
    apply_projection_decisions,
    build_compacted_tool_result_placeholder,
    compacted_tool_group_anchors,
    compaction_shrinks_tool_result,
    project_messages,
    projection_decisions_from_diff,
)
from cognis.core.message_markers import PROJECTED_COMPACTED
from cognis.core.pruning import prune_tool_outputs

LARGE = "L" * 4_000


def _call(*call_ids: str) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "read", "arguments": json.dumps({"path": call_id})},
            }
            for call_id in call_ids
        ],
    }


def _result(call_id: str, content: str) -> dict[str, object]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": content,
        "_tool_name": "read",
        "_recovery_call_id": call_id,
        "_output_size": len(content),
    }


def test_materiality_threshold_is_half_the_original_text() -> None:
    # Sizes in the same digit range render placeholders of the same length.
    placeholder_length = len(build_compacted_tool_result_placeholder(_result("call", "x" * 600)))

    assert not compaction_shrinks_tool_result(_result("call", "x" * (2 * placeholder_length - 1)))
    assert compaction_shrinks_tool_result(_result("call", "x" * (2 * placeholder_length)))
    assert compaction_shrinks_tool_result({"role": "tool", "content": [{"type": "image"}]})


def test_group_compaction_keeps_small_results_and_records_no_decision_for_them() -> None:
    messages = [
        {"role": "user", "content": "task"},
        _call("small", "large"),
        _result("small", "ok"),
        _result("large", LARGE),
        _call("recent"),
        _result("recent", "recent"),
    ]

    projected = project_messages(
        messages,
        preserve_recent_completed_tool_groups=1,
        pressure_mode=PressureMode.pressure,
    )

    assert projected.messages[2]["content"] == "ok"
    assert PROJECTED_COMPACTED not in projected.messages[2]
    assert "Tool output omitted" in str(projected.messages[3]["content"])
    decisions = projection_decisions_from_diff(messages, projected.messages)
    assert "small" not in decisions
    assert [d["operation"] for d in decisions["large"]] == ["compact_result"]
    # A partially rewritten batch is not reported as a fully compacted group.
    assert compacted_tool_group_anchors(projected.messages) == set()

    def without_estimates(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        return [{k: v for k, v in row.items() if k != "_token_estimate"} for row in rows]

    assert without_estimates(apply_projection_decisions(messages, decisions)) == (
        without_estimates(projected.messages)
    )


def test_repeated_projection_of_a_demoted_mixed_group_is_byte_stable() -> None:
    messages = [
        {"role": "user", "content": "task"},
        _call("small", "large"),
        _result("small", "ok"),
        _result("large", LARGE),
        _call("recent"),
        _result("recent", "recent"),
    ]

    first = project_messages(
        messages, preserve_recent_completed_tool_groups=1, pressure_mode=PressureMode.critical
    )
    second = project_messages(
        first.messages,
        preserve_recent_completed_tool_groups=1,
        pressure_mode=PressureMode.critical,
    )

    assert [m.get("content") for m in second.messages] == [m.get("content") for m in first.messages]


def test_fallback_prune_skips_small_results_and_counts_net_savings() -> None:
    messages = [
        _call("old-small"),
        _result("old-small", "tiny"),
        _call("old-large"),
        _result("old-large", LARGE),
        _call("new"),
        _result("new", "newest"),
    ]

    pruned = prune_tool_outputs(
        messages,
        protect_tokens=0,
        minimum_savings=1,
        pressure_mode=PressureMode.critical,
        token_counter=len,
    )

    assert pruned[1]["content"] == "tiny"
    assert "Tool output omitted" in str(pruned[3]["content"])

    net_savings = len(LARGE) - len(build_compacted_tool_result_placeholder(messages[3]))
    unchanged = prune_tool_outputs(
        messages,
        protect_tokens=0,
        minimum_savings=net_savings + 1,
        pressure_mode=PressureMode.critical,
        token_counter=len,
    )
    assert unchanged == messages


def test_existing_compact_decision_for_a_small_result_remains_authoritative() -> None:
    messages = [_call("small"), _result("small", "ok")]
    decisions = {
        "small": [{"operation": "compact_result", "rendering_policy_version": 1, "parameters": {}}]
    }

    replayed = apply_projection_decisions(messages, decisions)

    assert replayed[1]["content"] == build_compacted_tool_result_placeholder(messages[1])
    assert replayed[1][PROJECTED_COMPACTED] is True
