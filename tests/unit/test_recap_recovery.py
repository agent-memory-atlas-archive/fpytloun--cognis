"""Recently due recaps survive rolling controller restarts without backfilling old chats."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cognis.core.recap import RecapService
from cognis.core.session import _to_conversation_model, _to_session_model
from cognis.models.session import EventAppendResult
from cognis.store.coordination import DatabaseLeaseStore
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import Agent, Base, Conversation, Session, User, UserUiState
from cognis.store.queries import list_recent_web_recap_candidates


@pytest.mark.anyio
async def test_recovery_candidates_are_recent_active_web_chats_with_enabled_preferences(
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/recap.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    now = datetime.now(UTC)
    try:
        async with factory() as db:
            for suffix in ("due", "channel", "recent", "old", "off"):
                db.add(User(email=f"{suffix}@example.org"))
            await db.flush()
            db.add(Agent(agent_id="agent-recap", owner_email="due@example.org", name="Recap"))
            await db.flush()
            for suffix, context_type, age in (
                ("due", "web", 10),
                ("channel", "signal", 10),
                ("recent", "web", 1),
                ("old", "web", 240),
                ("off", "web", 10),
            ):
                user_email = f"{suffix}@example.org"
                db.add(
                    Conversation(
                        conversation_id=f"conv-{suffix}",
                        user_email=user_email,
                        agent_id="agent-recap",
                        context_type=context_type,
                        context_ref=f"{context_type}:{suffix}",
                        status="active",
                        active_session_id=f"sess-{suffix}",
                        last_message_at=now - timedelta(minutes=age),
                    )
                )
                db.add(
                    UserUiState(
                        user_email=user_email,
                        key="ui.preferences",
                        value={"chat": {"auto_recap": suffix != "off"}},
                        updated_at=now - timedelta(days=1),
                    )
                )
            await db.flush()
            db.add(
                Session(
                    session_id="sess-due",
                    conversation_id="conv-due",
                    user_email="due@example.org",
                    agent_id="agent-recap",
                )
            )
            await db.commit()
        async with factory() as db:
            candidates = await list_recent_web_recap_candidates(
                db,
                since=now - timedelta(hours=2),
                until=now - timedelta(minutes=5),
            )
        assert [conversation_id for conversation_id, _last, _pref in candidates] == ["conv-due"]
        async with factory() as db:
            db.add_all(
                Conversation(
                    conversation_id=f"conv-busy-{index}",
                    user_email="due@example.org",
                    agent_id="agent-recap",
                    context_type="web",
                    status="active",
                    active_session_id="sess-due",
                    last_message_at=now - timedelta(minutes=6),
                )
                for index in range(205)
            )
            await db.commit()
        async with factory() as db:
            older = await list_recent_web_recap_candidates(
                db,
                since=now - timedelta(hours=2),
                until=now - timedelta(minutes=5),
                offset=200,
            )
        assert "conv-due" in {conversation_id for conversation_id, _, _ in older}
        providers = SimpleNamespace(
            guardrails=SimpleNamespace(
                read_events=AsyncMock(
                    return_value=SimpleNamespace(
                        events=[
                            {
                                "seq": 1,
                                "type": "user_message",
                                "data": {"turn_id": "fix", "content": "Fix rendering"},
                            },
                            {
                                "seq": 2,
                                "type": "tool_result",
                                "data": {
                                    "turn_id": "fix",
                                    "file_diffs": [{"path": "src/render.py", "diff": "+fix\n"}],
                                },
                            },
                            {
                                "seq": 3,
                                "type": "assistant_message",
                                "data": {"turn_id": "fix", "content": "Fixed rendering."},
                            },
                        ]
                    )
                ),
                record_events=AsyncMock(
                    return_value=EventAppendResult(ok=True, count=1, first_seq=4, last_seq=4)
                ),
            ),
            llm=SimpleNamespace(
                generate=AsyncMock(
                    return_value={
                        "choices": [
                            {
                                "message": {
                                    "content": ('{"publish": true, "summary": "Fixed rendering."}')
                                }
                            }
                        ]
                    }
                )
            ),
        )
        recap = RecapService(
            session_factory=factory,
            providers=providers,
            scheduler=SimpleNamespace(
                durable_running_turn_state=AsyncMock(return_value=None),
                get_queued_messages=AsyncMock(return_value=[]),
                has_active_turn=lambda _id: False,
                queued_count=lambda _id: 0,
                cluster_signals=SimpleNamespace(publish_chat_change=AsyncMock()),
            ),
            session_cache=SimpleNamespace(append_recorded_events=AsyncMock()),
            event_bus=SimpleNamespace(subscribe=MagicMock()),
            lease_store=DatabaseLeaseStore(factory),
        )
        assert (
            await recap._auto_if_idle(
                "conv-due", expected_activity=candidates[0][1].replace(tzinfo=UTC)
            )
            == "Fixed rendering."
        )
        providers.guardrails.record_events.assert_awaited_once()
        held = await recap._lease_store.acquire(
            "conversation-recap:conv-due", "another-pod", ttl_seconds=120
        )
        assert held is not None
        try:
            assert (
                await recap._auto_if_idle(
                    "conv-due", expected_activity=candidates[0][1].replace(tzinfo=UTC)
                )
                == "Recap is already being generated."
            )
            providers.llm.generate.assert_awaited_once()
        finally:
            await recap._lease_store.release(held)
        async with factory() as db:
            conversation_row = await db.get(Conversation, "conv-due")
            session_row = await db.get(Session, "sess-due")
            assert conversation_row is not None and session_row is not None
            snapshot = _to_conversation_model(conversation_row)
            active_session = _to_session_model(session_row)
            conversation_row.last_message_at = now
            await db.commit()
        assert not await recap._auto_still_idle(snapshot, active_session)
        recap._scheduler.get_queued_messages.return_value = [{"queue_id": "queued-turn"}]
        assert not await recap._auto_still_idle(snapshot, active_session)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_recovery_sweeps_after_restart_without_repeating_same_activity(monkeypatch) -> None:
    now = datetime.now(UTC)
    activity = now - timedelta(minutes=10)
    candidates = [
        ("conv-due", activity, activity - timedelta(days=1)),
        ("conv-newly-enabled", activity, activity + timedelta(minutes=1)),
    ]
    monkeypatch.setattr(
        "cognis.core.recap.list_recent_web_recap_candidates",
        AsyncMock(return_value=candidates),
    )

    def service() -> RecapService:
        return RecapService(
            session_factory=MagicMock(),
            providers=SimpleNamespace(),
            scheduler=SimpleNamespace(),
            session_cache=SimpleNamespace(),
            event_bus=SimpleNamespace(subscribe=MagicMock()),
        )

    first = service()
    first._auto_if_idle = AsyncMock(return_value="Nothing worth recapping yet.")
    await first._scan_recent()
    await first._scan_recent()
    first._auto_if_idle.assert_awaited_once_with("conv-due", expected_activity=activity)

    restarted = service()
    restarted._auto_if_idle = AsyncMock(return_value="Nothing worth recapping yet.")
    await restarted._scan_recent()
    restarted._auto_if_idle.assert_awaited_once_with("conv-due", expected_activity=activity)


@pytest.mark.anyio
async def test_recovery_retries_lost_lease_and_scans_past_first_page(monkeypatch) -> None:
    activity = datetime.now(UTC) - timedelta(minutes=10)
    page = [(f"conv-{index}", activity, None) for index in range(200)]
    query = AsyncMock(
        side_effect=[page, [("conv-older", activity, None)], page, [("conv-older", activity, None)]]
    )
    monkeypatch.setattr("cognis.core.recap.list_recent_web_recap_candidates", query)
    service = RecapService(
        session_factory=MagicMock(),
        providers=SimpleNamespace(),
        scheduler=SimpleNamespace(),
        session_cache=SimpleNamespace(),
        event_bus=SimpleNamespace(subscribe=MagicMock()),
    )
    service._auto_if_idle = AsyncMock(
        side_effect=lambda conversation_id, **_kwargs: (
            "Recap ownership changed before publication."
            if conversation_id == "conv-older"
            else "Nothing worth recapping yet."
        )
    )
    await service._scan_recent()
    await service._scan_recent()
    assert service._auto_if_idle.await_count == 202
    assert [call.kwargs["offset"] for call in query.await_args_list] == [0, 200, 0, 200]


@pytest.mark.anyio
async def test_recovery_retries_after_cooldown_without_another_message(monkeypatch) -> None:
    activity = datetime.now(UTC) - timedelta(minutes=10)
    monkeypatch.setattr(
        "cognis.core.recap.list_recent_web_recap_candidates",
        AsyncMock(return_value=[("conv-due", activity, None)]),
    )
    service = RecapService(
        session_factory=MagicMock(),
        providers=SimpleNamespace(),
        scheduler=SimpleNamespace(),
        session_cache=SimpleNamespace(),
        event_bus=SimpleNamespace(subscribe=MagicMock()),
    )
    service._auto_if_idle = AsyncMock(
        side_effect=["Recap cooldown is active.", "Completed work recap."]
    )
    await service._scan_recent()
    await service._scan_recent()
    assert service._auto_if_idle.await_count == 2
    service._auto_if_idle.assert_awaited_with("conv-due", expected_activity=activity)
    await service._scan_recent()
    assert service._auto_if_idle.await_count == 2
