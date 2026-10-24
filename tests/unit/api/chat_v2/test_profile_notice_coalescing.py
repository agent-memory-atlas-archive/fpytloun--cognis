from cognis.api.chat_v2.event_store import RawSessionEvent
from cognis.api.chat_v2.normalizer import normalize_session_events
from cognis.api.chat_v2.projector import project_timeline


def notice(seq: int, profile: str, notice_id: str, session_id: str = "sess-1") -> RawSessionEvent:
    return RawSessionEvent(
        store_id="intaris",
        session_id=session_id,
        seq=seq,
        type="lifecycle",
        data={
            "event": "system_notice",
            "command": "/profile",
            "kind": "command_result",
            "resolved_agent_profile_id": profile,
            "notice_id": notice_id,
            "message": f"Selected {profile}",
            "content": f"Selected {profile}",
        },
    )


def project(raw: list[RawSessionEvent]):
    return project_timeline(normalize_session_events(raw).events).timeline.items


def test_legacy_click_notices_update_one_card_in_place_with_all_audit_refs() -> None:
    first = notice(1, "worker", "command:profile:first")
    initial = project([first])[0]
    final = project(
        [
            first,
            notice(2, "critical", "command:profile:second"),
            notice(3, "smart", "command:profile:third"),
        ]
    )
    assert len(final) == 1
    assert final[0].id == initial.id
    assert final[0].sort_key == initial.sort_key
    assert final[0].content == "Selected smart"
    assert [ref.seq for ref in final[0].source_refs] == [1, 2, 3]
    assert (
        project([first, notice(2, "critical", "command:profile:first")])[0].content
        == "Selected critical"
    )


def test_message_admission_freezes_prior_card_and_other_commands_do_not_coalesce() -> None:
    raw = [
        notice(1, "worker", "command:profile:first"),
        notice(2, "critical", "command:profile:second"),
    ]
    raw.append(
        RawSessionEvent(
            store_id="intaris",
            session_id="sess-1",
            seq=3,
            type="user_message",
            data={"content": "go", "turn_id": "turn-1"},
        )
    )
    raw.append(notice(4, "smart", "command:profile:third"))
    raw.append(
        RawSessionEvent(
            store_id="intaris",
            session_id="sess-1",
            seq=5,
            type="lifecycle",
            data={
                "event": "system_notice",
                "command": "/model",
                "notice_id": "command:model:first",
                "message": "Model changed",
            },
        )
    )
    raw.append(notice(6, "worker", "command:profile:fourth"))
    items = project(raw)
    profiles = [item for item in items if item.id.startswith("system:command:profile:")]
    assert [item.content for item in profiles] == ["Selected critical", "Selected worker"]
    assert len(items) == 4


def test_session_rotation_and_profile_queries_are_not_folded() -> None:
    raw = [
        notice(1, "worker", "command:profile:first"),
        notice(2, "critical", "command:profile:second", "sess-2"),
    ]
    raw.append(
        RawSessionEvent(
            store_id="intaris",
            session_id="sess-2",
            seq=3,
            type="lifecycle",
            data={
                "event": "system_notice",
                "command": "/profile",
                "notice_id": "command:profile:query",
                "message": "Available profiles",
            },
        )
    )
    assert len(project(raw)) == 3


def test_assistant_boundary_and_projection_does_not_mutate_normalized_audit() -> None:
    raw = [notice(1, "worker", "command:profile:first")]
    raw.append(
        RawSessionEvent(
            store_id="intaris",
            session_id="sess-1",
            seq=2,
            type="assistant_message",
            data={"message_id": "reply-1", "content": "done"},
        )
    )
    raw.extend(
        [
            notice(3, "smart", "command:profile:second"),
            notice(4, "critical", "command:profile:third"),
        ]
    )
    events = normalize_session_events(raw).events
    original = [event.model_dump() for event in events]
    items = project_timeline(events).timeline.items
    profiles = [item for item in items if item.id.startswith("system:command:profile:")]
    assert [item.content for item in profiles] == ["Selected worker", "Selected critical"]
    assert [event.model_dump() for event in events] == original
