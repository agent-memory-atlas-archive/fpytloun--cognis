"""Concise recovery markers retain handles, protocol shape and replay identity."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from cognis.core.context import events_to_messages
from cognis.core.context_projection import (
    apply_projection_decisions,
    build_compacted_tool_result_placeholder,
    compact_tool_result,
    project_messages,
    projection_decision_batches,
    projection_decisions_from_diff,
)
from cognis.core.message_markers import PROJECTED_COMPACTED
from cognis.core.session_cache import SessionCache
from cognis.core.tool_output_presentation import build_recovery_hint
from cognis.core.truncation import middle_truncate
from cognis.models.session import SessionEvent
from cognis.providers.llm.message_projection import project_messages_for_provider
from tests.unit.test_context_delivery import _EventStore, _projection_runtime

CALL_ID = "call_880b32cb46e14f5ea60b1840601e1acc"
SOURCE_ID = "call_e7a82b31ebdc4c87a9cefe1d41c95612"


def _result(**extra: object) -> dict:
    return {
        "role": "tool",
        "tool_call_id": CALL_ID,
        "_tool_name": "read",
        "_recovery_call_id": CALL_ID,
        "content": "read output\n" * 2000,
        **extra,
    }


def test_short_marker_has_one_handle_and_less_than_half_legacy_size() -> None:
    message = _result()
    legacy = build_compacted_tool_result_placeholder(message, rendering_policy_version=1)
    current = build_compacted_tool_result_placeholder(message)

    assert current.count(CALL_ID) == 1
    assert f"read_tool_output(call_id={CALL_ID!r})" in current
    assert "Recover only if needed" in current
    assert "search_tool_output" not in current
    assert len(current) < len(legacy) // 2
    assert message == _result()


def test_version_one_placeholder_remains_byte_identical() -> None:
    text = build_compacted_tool_result_placeholder(
        _result(_output_size=24_000, _anchor_names=["overview"]),
        rendering_policy_version=1,
    )
    assert text == (
        "[Tool output omitted from prompt. Tool: read. "
        f"Original call_id: {CALL_ID}. Original output size: 24,000 chars. "
        f"Recover with call_id {CALL_ID!r}: "
        f"read_tool_output(call_id={CALL_ID!r}), "
        f"search_tool_output(call_id={CALL_ID!r}, pattern='error|timeout|keyword'), "
        f"list_tool_output_anchors(call_id={CALL_ID!r}), "
        f"read_tool_output_anchor(call_id={CALL_ID!r}, anchor='overview'). "
        "Only recover if a specific missing detail is needed.]"
    )


def test_short_marker_preserves_source_and_only_authorized_artifact_refs() -> None:
    text = build_compacted_tool_result_placeholder(
        _result(
            _source_call_id=SOURCE_ID,
            _anchor_names=["media:1"],
            _tool_output_presentation={
                "lazy_artifact_refs": [
                    f"tool_artifact:{CALL_ID}:media:1",
                    f"tool_artifact:{SOURCE_ID}:media:1",
                ],
            },
        )
    )
    assert f"derived from source call_id '{SOURCE_ID}'" in text
    assert f"artifact_read: tool_artifact:{CALL_ID}:media:1" in text
    assert f"tool_artifact:{SOURCE_ID}:media:1" not in text
    assert "Anchors: media:1." in text


@pytest.mark.parametrize("handle", [None, "", "  "])
def test_missing_saved_handle_never_promises_recovery(handle: str | None) -> None:
    text = build_compacted_tool_result_placeholder(
        _result(_recovery_call_id=handle, _producer_truncated=True)
    )
    assert "No saved output handle is available" in text
    assert "diagnostic only" in text
    assert "read_tool_output(" not in text


def test_shared_hint_sanitizes_anchors_and_caps_the_inline_preview() -> None:
    text = build_recovery_hint(
        CALL_ID,
        anchor_names=["overview /\n", "overview /", *[f"section:{i}" for i in range(8)]],
    )
    assert text.count(CALL_ID) == 1
    assert "Anchors: overview, section:0, section:1, section:2, section:3, +4 more." in text
    assert "\n" not in text
    assert "section:7" not in text


def test_anchor_count_without_names_does_not_invent_an_anchor() -> None:
    text = build_recovery_hint(CALL_ID, anchors_available=True, anchor_count=7)
    assert "Anchors available." in text
    assert "anchor=" not in text
    assert text.count(CALL_ID) == 1


def test_middle_truncation_uses_the_same_single_handle_hint() -> None:
    text, truncated = middle_truncate(
        "H" * 1000 + "M" * 4000 + "T" * 1000,
        700,
        call_id=CALL_ID,
        anchors=["summary"],
    )
    assert truncated
    assert text.startswith("H")
    assert text.endswith("T")
    assert len(text) <= 700
    assert text.count(CALL_ID) == 1
    assert build_recovery_hint(CALL_ID, anchor_names=["summary"]) in text


def test_projection_keeps_all_call_result_slots_and_records_version_two() -> None:
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": CALL_ID,
                    "type": "function",
                    "function": {"name": "read", "arguments": "{}"},
                }
            ],
        },
        _result(),
        {"role": "user", "content": "continue"},
    ]
    original = deepcopy(messages)
    projection = project_messages(messages, preserve_recent_completed_tool_groups=0)
    decisions = projection_decisions_from_diff(messages, projection.messages)
    assert decisions == {
        CALL_ID: [{"operation": "compact_result", "rendering_policy_version": 2, "parameters": {}}]
    }
    assert len(projection.messages) == len(messages)
    assert projection.messages[0] == messages[0]
    assert projection.messages[1]["tool_call_id"] == CALL_ID
    assert projection.messages[2] == messages[2]
    assert messages == original
    replayed = apply_projection_decisions(messages, decisions)
    assert replayed[1]["content"] == projection.messages[1]["content"]


def test_legacy_marker_is_not_reclassified_or_rewritten_as_version_two() -> None:
    source = _result()
    call = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": CALL_ID,
                "type": "function",
                "function": {"name": "read", "arguments": "{}"},
            }
        ],
    }
    legacy = compact_tool_result(source, rendering_policy_version=1)
    decisions = projection_decisions_from_diff([call, source], [call, legacy])
    assert decisions[CALL_ID][0]["rendering_policy_version"] == 1
    projected = project_messages([call, legacy], preserve_recent_completed_tool_groups=0)
    assert projected.messages[1]["content"] == legacy["content"]
    assert projection_decisions_from_diff([call, source], projected.messages) == decisions
    # Old accepted in-memory markers have no explicit internal version.
    legacy.pop("_compact_result_rendering_version")
    assert projection_decisions_from_diff([source], [legacy]) == decisions


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [1, 2])
async def test_versioned_placeholder_survives_delivery_and_cold_cache(version: int) -> None:
    store = _EventStore()
    await store.record_events(
        events=[
            SessionEvent(
                type="tool_call",
                data={"call_id": CALL_ID, "name": "read", "arguments": {"path": "/repo"}},
            ),
            SessionEvent(
                type="tool_result",
                data={
                    "call_id": CALL_ID,
                    "name": "read",
                    "result": "historical output\n" * 2000,
                    "recovery_call_id": CALL_ID,
                    "has_full_output": True,
                },
            ),
        ],
        idempotency_key=f"concise_initial_v{version}",
    )
    session, agent, cache, assembler = await _projection_runtime(store)
    cold = SessionCache(store)
    try:
        original = events_to_messages(store.events)
        accepted = [original[0], compact_tool_result(original[1], rendering_policy_version=version)]
        decisions = projection_decisions_from_diff(original, accepted)
        await assembler.persist_projection_decisions(
            session=session, agent=agent, decisions=decisions
        )
        writes = len(store.writes)
        await assembler.persist_projection_decisions(
            session=session, agent=agent, decisions=decisions
        )
        assert len(store.writes) == writes
        assert (
            projection_decision_batches(decisions)[0]["decisions"][0]["rendering_policy_version"]
            == version
        )
        await cold.refresh(session)
        replayed = events_to_messages(
            cold.get_events_since_compaction(session.session_id),
            projection_decisions=cold.get_projection_decisions(session.session_id),
        )
        assert replayed[1][PROJECTED_COMPACTED] is True
        for provider, api in (
            (SimpleNamespace(config={"preset": "anthropic"}), "chat"),
            (None, "responses"),
        ):
            assert (
                project_messages_for_provider(accepted, provider=provider, llm_api=api).messages
                == project_messages_for_provider(replayed, provider=provider, llm_api=api).messages
            )
    finally:
        await cold.aclose()
        await cache.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [3, True, "2", [], None])
async def test_cache_rejects_unknown_or_malformed_rendering_versions(version: object) -> None:
    store = _EventStore()
    session, _, cache, _ = await _projection_runtime(store)
    try:
        await store.record_events(
            events=[
                SessionEvent(
                    type="lifecycle",
                    data={
                        "event": "context_projection",
                        "decisions": [
                            {
                                "call_id": CALL_ID,
                                "operation": "compact_result",
                                "rendering_policy_version": version,
                                "parameters": {},
                            },
                            {
                                "call_id": SOURCE_ID,
                                "operation": "omit_tool_group",
                                "rendering_policy_version": 2,
                                "parameters": {},
                            },
                        ],
                    },
                )
            ],
            idempotency_key="concise_unsupported_version",
        )
        await cache.refresh(session)
        assert cache.get_projection_decisions(session.session_id) == {}
    finally:
        await cache.aclose()
