"""Approval targeting through the real durable notification owner."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cognis.core.agent_loop import PauseResolution, PauseWaiter, PendingPause
from cognis.core.commands import CommandDispatcher, CommandResult
from cognis.core.legacy_approvals import resolve_legacy_approval
from cognis.core.notifications import NotificationService
from cognis.providers.guardrails.resolution_errors import ResolutionRejected
from cognis.store.models import Agent, Base, NotificationRow, User


@pytest.fixture
async def approvals(tmp_path):
    postgres_url = os.environ.get("COGNIS_APPROVAL_TEST_POSTGRES_URL")
    admin = None
    schema = None
    if postgres_url:
        admin = create_async_engine(postgres_url)
        schema = f"approval_test_{uuid.uuid4().hex}"
        async with admin.begin() as connection:
            await connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine = create_async_engine(
            postgres_url, connect_args={"server_settings": {"search_path": schema}}
        )
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'approvals.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add_all([User(email="owner"), User(email="other")])
        await db.flush()
        db.add(Agent(agent_id="agent", owner_email="owner", name="Approval test agent"))
        await db.commit()
    service = NotificationService(
        session_factory=factory,
        event_bus=SimpleNamespace(publish=AsyncMock()),
        providers=SimpleNamespace(guardrails=SimpleNamespace(submit_decision=AsyncMock())),
        pause_waiter=PauseWaiter(),
    )

    async def add(identifier, *, owner="owner", conversation="chat", expired=False, managed=None):
        now = datetime.now(UTC)
        async with factory() as session:
            session.add(
                NotificationRow(
                    notification_id=identifier,
                    notification_type="escalation",
                    user_email=owner,
                    conversation_id=conversation,
                    payload={
                        "call_id": identifier,
                        "tool_name": "manage_agents",
                        "arguments_display": {"action": "tools_get", "agent_id": "riker"},
                        **({"managed_origin_conversation_id": managed} if managed else {}),
                    },
                    status="pending",
                    revision=1,
                    created_at=now,
                    expires_at=now + timedelta(seconds=-1 if expired else 300),
                )
            )
            await session.commit()

    try:
        yield service, factory, add
    finally:
        await engine.dispose()
        if admin is not None:
            async with admin.begin() as connection:
                await connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            await admin.dispose()


@pytest.mark.asyncio
async def test_explicit_command_targets_and_preserves_notes():
    dispatcher = CommandDispatcher(
        session_factory=None,
        session_manager=None,
        session_cache=None,
        compaction_strategy=None,
        providers=None,
        pause_waiter=None,
        notification_service=None,
    )
    dispatcher._handle_approve_deny = AsyncMock(
        return_value=CommandResult(type="system_message", text="Resolved")
    )

    async def parse(text):
        return await dispatcher.dispatch(
            text,
            conversation=SimpleNamespace(conversation_id="chat"),
            session=SimpleNamespace(session_id="session"),
            agent=SimpleNamespace(agent_id="agent"),
            user_email="owner",
        )

    await parse("/approve --id first safe to continue")
    assert dispatcher._handle_approve_deny.call_args.kwargs["target_id"] == "first"
    assert dispatcher._handle_approve_deny.call_args.args[2] == "safe to continue"
    identifier = "05bf9353-8fc4-43fe-a930-161fc21f7074"
    await parse(f"/deny {identifier} not this one")
    assert dispatcher._handle_approve_deny.call_args.kwargs["target_id"] == identifier
    assert dispatcher._handle_approve_deny.call_args.args[2] == "not this one"
    await parse("/approve safe to continue")
    assert dispatcher._handle_approve_deny.call_args.kwargs["target_id"] is None
    assert (await parse("/approve --id")).type == "error"


@pytest.mark.asyncio
async def test_exact_target_resolves_only_one_of_multiple_and_remains_idempotent(approvals):
    service, factory, add = approvals
    await add("first")
    await add("second")
    assert not await service.resolve_escalation(
        "first", "approve", {}, user_email="owner", conversation_id="chat", require_unique=True
    )
    service._providers.guardrails.submit_decision.assert_not_called()
    assert await service.resolve_escalation(
        "second", "approve", {"note": "only this"}, user_email="owner", conversation_id="chat"
    )
    assert await service.resolve_escalation(
        "second", "approve", {"note": "only this"}, user_email="owner", conversation_id="chat"
    )
    assert not await service.resolve_escalation(
        "second", "deny", {}, user_email="owner", conversation_id="chat"
    )
    assert service._providers.guardrails.submit_decision.await_count == 1
    async with factory() as session:
        assert (await session.get(NotificationRow, "first")).status == "pending"
        assert (await session.get(NotificationRow, "second")).resolution["decision"] == "approve"


@pytest.mark.asyncio
async def test_wrong_owner_conversation_unknown_and_expired_never_resolve(approvals):
    service, _, add = approvals
    await add("current")
    await add("expired", expired=True)
    for identifier, owner, chat in [
        ("current", "other", "chat"),
        ("current", "owner", "elsewhere"),
        ("unknown", "owner", "chat"),
        ("expired", "owner", "chat"),
    ]:
        assert not await service.resolve_escalation(
            identifier, "approve", {}, user_email=owner, conversation_id=chat
        )
    service._providers.guardrails.submit_decision.assert_not_called()
    assert await service.resolve_timeout("expired")
    # Local timeout denial must not revive or submit the expired action.
    service._providers.guardrails.submit_decision.assert_not_called()


@pytest.mark.asyncio
async def test_managed_origin_is_eligible_only_for_its_controller(approvals):
    service, _, add = approvals
    await add("child", conversation="child-chat", managed="controller-chat")
    assert await service.find_escalation(
        notification_id="child", user_email="owner", conversation_id="controller-chat"
    )
    assert not await service.resolve_escalation(
        "child", "approve", {}, user_email="owner", conversation_id="other-chat"
    )
    assert await service.resolve_escalation(
        "child", "deny", {}, user_email="owner", conversation_id="controller-chat"
    )


@pytest.mark.asyncio
async def test_dispatcher_rejects_ambiguous_bare_command_and_targets_exact_id(approvals):
    service, factory, add = approvals
    await add("first")
    await add("second")
    dispatcher = CommandDispatcher(
        session_factory=None,
        session_manager=None,
        session_cache=None,
        compaction_strategy=None,
        providers=None,
        notification_service=service,
        pause_waiter=None,
    )
    conversation = SimpleNamespace(conversation_id="chat")
    result = await dispatcher._handle_approve_deny(conversation, True, None, "owner")
    assert result.data["code"] == "escalation_ambiguous"
    assert "--id first" in result.text
    assert "--id second" in result.text
    service._providers.guardrails.submit_decision.assert_not_called()
    result = await dispatcher._handle_approve_deny(
        conversation, False, "only second", "owner", target_id="second"
    )
    assert result.type == "system_message", result
    async with factory() as session:
        assert (await session.get(NotificationRow, "first")).status == "pending"
        assert (await session.get(NotificationRow, "second")).resolution["decision"] == "deny"


@pytest.mark.asyncio
async def test_new_approval_between_selection_and_claim_blocks_bare_resolution(
    approvals, monkeypatch
):
    service, _, add = approvals
    await add("first")
    original = service._actionable_escalation_rows
    admitted = []

    async def insert_after_admission_query(db, **kwargs):
        rows = await original(db, **kwargs)
        admitted.extend(row.notification_id for row in rows)
        await add("concurrent")
        return rows

    monkeypatch.setattr(service, "_actionable_escalation_rows", insert_after_admission_query)
    assert not await service.resolve_escalation(
        "first", "approve", {}, user_email="owner", conversation_id="chat", require_unique=True
    )
    service._providers.guardrails.submit_decision.assert_not_called()
    assert admitted == ["first"]  # Admission passed; the SQL guard rejected the claim.


@pytest.mark.asyncio
async def test_arrival_after_claim_does_not_strand_an_already_submitted_resolution(approvals):
    service, factory, add = approvals
    await add("first")

    async def submit(*args, **kwargs):
        await add("arrived-after-claim")

    service._providers.guardrails.submit_decision.side_effect = submit
    assert await service.resolve_escalation(
        "first", "approve", {}, user_email="owner", conversation_id="chat", require_unique=True
    )
    async with factory() as session:
        assert (await session.get(NotificationRow, "first")).status == "resolved"
        assert (await session.get(NotificationRow, "arrived-after-claim")).status == "pending"


def dispatcher_for(service, waiter):
    return CommandDispatcher(
        session_factory=None,
        session_manager=None,
        session_cache=None,
        compaction_strategy=None,
        providers=service._providers,
        pause_waiter=waiter,
        notification_service=service,
    )


@pytest.mark.asyncio
async def test_mixed_sources_block_bare_but_explicit_durable_target_works(approvals):
    service, _, add = approvals
    await add("durable")
    waiter = service._pause_waiter
    waiter.register(PendingPause(pause_id="local", pause_type="escalation", conversation_id="chat"))
    dispatcher = dispatcher_for(service, waiter)
    result = await dispatcher._handle_approve_deny(
        SimpleNamespace(conversation_id="chat"), True, None, "owner"
    )
    assert result.data["code"] == "escalation_ambiguous"
    service._providers.guardrails.submit_decision.assert_not_called()
    result = await dispatcher._handle_approve_deny(
        SimpleNamespace(conversation_id="chat"), True, None, "owner", target_id="local"
    )
    assert result.data["code"] == "escalation_not_actionable"
    service._providers.guardrails.submit_decision.assert_not_called()
    await add("local")  # Completion of registration does not confer a second submitter.
    result = await dispatcher._handle_approve_deny(
        SimpleNamespace(conversation_id="chat"), True, None, "owner", target_id="local"
    )
    assert result.type == "system_message"
    service._providers.guardrails.submit_decision.assert_awaited_once()


@pytest.mark.asyncio
async def test_durable_and_waiter_mirror_count_once(approvals):
    service, _, add = approvals
    await add("first")
    waiter = service._pause_waiter
    waiter.register(PendingPause(pause_id="first", pause_type="escalation", conversation_id="chat"))
    result = await dispatcher_for(service, waiter)._handle_approve_deny(
        SimpleNamespace(conversation_id="chat"), True, None, "owner"
    )
    assert result.type == "system_message"
    service._providers.guardrails.submit_decision.assert_awaited_once()
    assert waiter.get("first").resolved


@pytest.mark.asyncio
async def test_local_arrival_during_durable_cas_blocks_submission(approvals):
    from sqlalchemy import event

    service, factory, add = approvals
    await add("first")
    waiter = service._pause_waiter
    engine = factory.kw["bind"].sync_engine
    injected = []

    def register_after_claim(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE notifications") and not injected:
            injected.append(True)
            waiter.register(
                PendingPause(
                    pause_id="local-arrival", pause_type="escalation", conversation_id="chat"
                )
            )

    event.listen(engine, "after_cursor_execute", register_after_claim)
    try:
        result = await dispatcher_for(service, waiter)._handle_approve_deny(
            SimpleNamespace(conversation_id="chat"), True, None, "owner"
        )
    finally:
        event.remove(engine, "after_cursor_execute", register_after_claim)
    assert injected == [True]
    assert result.type == "error"
    service._providers.guardrails.submit_decision.assert_not_called()
    async with factory() as db:
        assert (await db.get(NotificationRow, "first")).status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_expiry", [False, True])
async def test_expired_stale_resolving_never_newly_submits(approvals, legacy_expiry):
    service, factory, add = approvals
    await add("stale", expired=True)
    async with factory() as db:
        row = await db.get(NotificationRow, "stale")
        row.status = "resolving"
        row.resolved_at = datetime.now(UTC) - timedelta(minutes=30)
        row.resolution = {"decision": "approve", "state": "submitting"}
        if legacy_expiry:
            row.expires_at = None
            row.created_at = datetime.now(UTC) - timedelta(minutes=30)
            row.payload = {**row.payload, "timeout_seconds": 300}
        await db.commit()
    assert (
        await service.find_escalation(
            notification_id="stale", user_email="owner", conversation_id="chat"
        )
        is None
    )
    assert not await service.resolve_escalation(
        "stale", "approve", {}, user_email="owner", conversation_id="chat"
    )
    assert not await service.resolve("stale", "approve", user_email="owner")
    service._providers.guardrails.submit_decision.assert_not_called()


@pytest.mark.asyncio
async def test_fresh_inflight_completion_and_terminal_retry_survive_expiry(approvals):
    service, factory, add = approvals
    await add("inflight", expired=True)
    async with factory() as db:
        row = await db.get(NotificationRow, "inflight")
        row.status = "resolving"
        row.resolved_at = datetime.now(UTC)
        row.resolution = {"decision": "approve", "state": "submitting"}
        await db.commit()
    assert await service.find_escalation(
        notification_id="inflight", user_email="owner", conversation_id="chat"
    )
    joining = asyncio.create_task(
        service.resolve_escalation(
            "inflight", "approve", {}, user_email="owner", conversation_id="chat"
        )
    )
    await asyncio.sleep(0.02)
    async with factory() as db:
        row = await db.get(NotificationRow, "inflight")
        row.status = "resolved"
        row.resolution = {"decision": "approve", "state": "resolved"}
        await db.commit()
    assert await joining
    assert await service.resolve_escalation(
        "inflight", "approve", {}, user_email="owner", conversation_id="chat"
    )
    service._providers.guardrails.submit_decision.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_competing_decisions_submit_once_and_honor_timeout():
    waiter = PauseWaiter()
    waiter.register(
        PendingPause(pause_id="legacy", pause_type="escalation", conversation_id="chat")
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(*args):
        entered.set()
        await release.wait()

    submit = AsyncMock(side_effect=send)
    first = asyncio.create_task(
        resolve_legacy_approval(
            waiter, "legacy", conversation_id="chat", decision="approve", note=None, submit=submit
        )
    )
    await entered.wait()
    assert not await resolve_legacy_approval(
        waiter, "legacy", conversation_id="chat", decision="deny", note=None, submit=submit
    )
    release.set()
    assert await first
    submit.assert_awaited_once()
    assert (await waiter.wait("legacy", timeout=0.1)).decision == "approve"

    waiter.register(
        PendingPause(pause_id="timeout", pause_type="escalation", conversation_id="chat")
    )
    entered.clear()
    release.clear()
    waiting = asyncio.create_task(waiter.wait("timeout", timeout=0.01))
    resolving = asyncio.create_task(
        resolve_legacy_approval(
            waiter, "timeout", conversation_id="chat", decision="approve", note=None, submit=submit
        )
    )
    await entered.wait()
    with pytest.raises(TimeoutError):
        await waiting
    release.set()
    assert not await resolving
    assert waiter.get("timeout") is None


@pytest.mark.asyncio
async def test_legacy_rejection_and_uncertain_outcome_claim_semantics():
    waiter = PauseWaiter()
    waiter.register(
        PendingPause(pause_id="legacy", pause_type="escalation", conversation_id="chat")
    )
    submit = AsyncMock(side_effect=ResolutionRejected(409, {"detail": "stale_approval"}))
    with pytest.raises(ResolutionRejected):
        await resolve_legacy_approval(
            waiter, "legacy", conversation_id="chat", decision="approve", note=None, submit=submit
        )
    submit.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await resolve_legacy_approval(
            waiter, "legacy", conversation_id="chat", decision="approve", note=None, submit=submit
        )
    submit.side_effect = None
    assert not await resolve_legacy_approval(
        waiter, "legacy", conversation_id="chat", decision="deny", note=None, submit=submit
    )
    assert submit.await_count == 2
    with pytest.raises(ValueError):
        waiter.register(
            PendingPause(pause_id="legacy", pause_type="escalation", conversation_id="chat")
        )
    waiter.clear("legacy")
    waiter.register(
        PendingPause(pause_id="legacy", pause_type="escalation", conversation_id="chat")
    )
    submit.side_effect = ResolutionRejected(409, {"detail": "mandatory_denial"})
    with pytest.raises(ResolutionRejected) as rejected:
        await resolve_legacy_approval(
            waiter, "legacy", conversation_id="chat", decision="approve", note=None, submit=submit
        )
    assert rejected.value.resolved_locally
    assert (await waiter.wait("legacy", timeout=0.1)).decision == "deny"


def test_stale_claim_token_cannot_resolve_replaced_pause():
    waiter = PauseWaiter()
    waiter.register(
        PendingPause(pause_id="legacy", pause_type="escalation", conversation_id="chat")
    )
    claim = waiter.claim_escalation("legacy", conversation_id="chat")
    waiter.clear("legacy")
    waiter.register(
        PendingPause(pause_id="legacy", pause_type="escalation", conversation_id="chat")
    )
    assert not waiter.resolve("legacy", PauseResolution(decision="approve"), claim=claim)


@pytest.mark.asyncio
@pytest.mark.parametrize("arrival", ["durable", "local"])
async def test_bare_join_stale_reclaim_preserves_both_selection_guards(
    approvals, monkeypatch, arrival
):
    import cognis.core.notifications as notifications

    service, factory, add = approvals
    await add("inflight")
    async with factory() as db:
        row = await db.get(NotificationRow, "inflight")
        row.status = "resolving"
        row.resolved_at = datetime.now(UTC)
        row.resolution = {"decision": "approve", "state": "submitting"}
        await db.commit()

    original = service._wait_for_existing_resolution_claim
    joined, continue_wait = asyncio.Event(), asyncio.Event()

    async def pause_join(*args, **kwargs):
        joined.set()
        await continue_wait.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "_wait_for_existing_resolution_claim", pause_join)
    resolving = asyncio.create_task(
        dispatcher_for(service, service._pause_waiter)._handle_approve_deny(
            SimpleNamespace(conversation_id="chat"), True, None, "owner"
        )
    )
    await asyncio.wait_for(joined.wait(), timeout=2)
    if arrival == "durable":
        await add("new-approval")
    else:
        service._pause_waiter.register(
            PendingPause(pause_id="new-approval", pause_type="escalation", conversation_id="chat")
        )
    async with factory() as db:
        row = await db.get(NotificationRow, "inflight")
        row.resolved_at = datetime.now(UTC) - timedelta(
            seconds=notifications._RESOLUTION_CLAIM_SECONDS + 1
        )
        await db.commit()
    continue_wait.set()
    assert (await asyncio.wait_for(resolving, timeout=2)).type == "error"
    service._providers.guardrails.submit_decision.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_rest_owner_binding_and_shared_command_claim(approvals, monkeypatch):
    from fastapi import HTTPException

    from cognis.api.models import EscalationResolveRequest
    from cognis.api.routes import escalations
    from cognis.store.models import Conversation

    service, factory, _ = approvals
    waiter = service._pause_waiter
    async with factory() as db:
        db.add(
            Conversation(
                conversation_id="chat", user_email="owner", agent_id="agent", context_type="web"
            )
        )
        await db.commit()
    waiter.register(
        PendingPause(
            pause_id="escalation:legacy",
            pause_type="escalation",
            conversation_id="chat",
            context={"call_id": "legacy"},
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                notification_service=None,
                pause_waiter=waiter,
                session_factory=factory,
                providers=service._providers,
            )
        )
    )
    monkeypatch.setattr(
        escalations, "require_current_user", lambda req: SimpleNamespace(email="other")
    )
    with pytest.raises(HTTPException) as foreign:
        await escalations.resolve_escalation(
            request, "legacy", EscalationResolveRequest(decision="approve")
        )
    assert foreign.value.status_code == 404
    service._providers.guardrails.submit_decision.assert_not_called()
    monkeypatch.setattr(
        escalations, "require_current_user", lambda req: SimpleNamespace(email="owner")
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def submit(*args):
        entered.set()
        await release.wait()

    service._providers.guardrails.submit_decision.side_effect = submit
    dispatcher = dispatcher_for(service, waiter)
    dispatcher._notification_service = None
    command = asyncio.create_task(
        dispatcher._handle_approve_deny(
            SimpleNamespace(conversation_id="chat"), True, None, "owner", target_id="legacy"
        )
    )
    await entered.wait()
    with pytest.raises(HTTPException) as competing:
        await escalations.resolve_escalation(
            request, "legacy", EscalationResolveRequest(decision="deny")
        )
    assert competing.value.status_code == 409
    release.set()
    assert (await command).type == "system_message"
    service._providers.guardrails.submit_decision.assert_awaited_once_with(
        "legacy", "approve", None
    )
