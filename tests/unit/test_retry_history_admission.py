"""Retry execution IDs must resolve a durable original user admission."""

from __future__ import annotations

import pytest

from cognis.core.canonical_history import CanonicalHistoryUnavailable
from cognis.core.session_cache import CachedEvent, CanonicalContextSnapshot


def user(turn: str = "original", seq: int = 1) -> CachedEvent:
    return CachedEvent(
        seq=seq, type="user_message", data={"turn_id": turn, "content": "Keep constraints"}
    )


def retry(turn: str = "retry", source: str = "original", seq: int = 2) -> CachedEvent:
    return CachedEvent(
        seq=seq,
        type="system_message",
        data={
            "event": "system_notice",
            "kind": "model_recovery",
            "scope": "turn",
            "turn_id": turn,
            "retry_source_turn_id": source,
            "retry_reason": "manual_retry",
        },
    )


def snapshot(events: list[CachedEvent]) -> CanonicalContextSnapshot:
    return CanonicalContextSnapshot(
        events=events,
        prefix_entries=[],
        last_compaction_summary=None,
        last_event_seq=max((event.seq for event in events), default=0),
        last_compaction_seq=0,
        projection_revision=0,
    )


def test_original_retry_and_repeated_retry_require_original_admission() -> None:
    history = snapshot([user(), retry(), retry("again", "retry", 3)])
    for turn in ("original", "retry", "again"):
        history.require_turn(turn, user_event=True, profile_switch=False)
    assert len([event for event in history.events if event.type == "user_message"]) == 1


def test_equivalent_duplicate_and_self_recovery_notices_preserve_admission() -> None:
    history = snapshot(
        [
            user(),
            retry(seq=2),
            retry(seq=3),
            retry(source="retry", seq=4),
        ]
    )

    history.require_turn("retry", user_event=True, profile_switch=False)


@pytest.mark.parametrize(
    "events",
    [
        [retry()],
        [user("unrelated"), retry()],
        [user(), retry(source="missing")],
        [user(), retry(source="retry")],
        [
            user(),
            retry(),
            CachedEvent(
                seq=3,
                type="system_message",
                data={**retry(seq=3).data, "retry_source_turn_id": ["original"]},
            ),
        ],
        [
            user(),
            retry(),
            CachedEvent(
                seq=3,
                type="system_message",
                data={**retry(seq=3).data, "retry_source_turn_id": None},
            ),
        ],
        [user(), retry(source="again"), retry("again", "retry", 3)],
        [user(seq=3), retry()],
        [user(), retry(), retry(source="other", seq=3)],
        [user(), CachedEvent(seq=2, type="tool_result", data=retry().data)],
        [
            user(),
            CachedEvent(
                seq=2,
                type="user_message",
                data={"turn_id": "other", "retry_source_turn_id": "original"},
            ),
        ],
    ],
)
def test_missing_ambiguous_or_noncausal_lineage_fails_closed(events: list[CachedEvent]) -> None:
    with pytest.raises(CanonicalHistoryUnavailable, match="Current user instruction"):
        snapshot(events).require_turn("retry", user_event=True, profile_switch=False)


def test_profile_boundary_still_belongs_to_retry_execution() -> None:
    with pytest.raises(CanonicalHistoryUnavailable, match="Profile switch is missing"):
        snapshot([user(), retry()]).require_turn("retry", user_event=True, profile_switch=True)

    switches = [
        CachedEvent(
            seq=3,
            type="lifecycle",
            data={
                "turn_id": "original",
                "kind": "agent_profile_changed",
                "call_id": "switch",
            },
        ),
        CachedEvent(seq=4, type="tool_call", data={"turn_id": "original", "call_id": "switch"}),
        CachedEvent(seq=5, type="tool_result", data={"turn_id": "original", "call_id": "switch"}),
    ]
    history = snapshot([user(), retry(), *switches])
    with pytest.raises(CanonicalHistoryUnavailable, match="Profile switch is missing"):
        history.require_turn("retry", user_event=True, profile_switch=True)
    for event in switches:
        event.data["turn_id"] = "retry"
    history.require_turn("retry", user_event=True, profile_switch=True)


@pytest.mark.parametrize(
    "key,value",
    [
        ("event", "turn_initiated"),
        ("kind", "notice"),
        ("scope", "session"),
        ("retry_source_turn_id", ""),
        ("retry_source_turn_id", ["original"]),
    ],
)
def test_unrecognized_notice_cannot_authorize_retry(key: str, value: object) -> None:
    notice = retry()
    notice.data[key] = value
    with pytest.raises(CanonicalHistoryUnavailable):
        snapshot([user(), notice]).require_turn("retry", user_event=True, profile_switch=False)
