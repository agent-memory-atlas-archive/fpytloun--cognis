from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import sqlalchemy as sa

from cognis.core.agent_loop import AgentLoop
from cognis.core.remember_queue import RememberRetryQueue
from cognis.core.trusted_evidence import (
    EVIDENCE_QUEUE_KIND,
    ORDINARY_ASSISTANT_QUEUE_KIND,
    TRUSTED_EVIDENCE_ADMISSION_KEY,
    build_evidence_admission,
    build_evidence_event_binding,
    build_marker,
    deterministic_queue_id,
    event_hash,
)
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import Agent, Base, Conversation, RememberQueueRow, Session, User

ADMISSION_KEY = b"remember-queue-reconciliation-test-key"


@pytest.mark.asyncio
async def test_idle_queue_never_reads_session_history(tmp_path: Path) -> None:
    engine, factory = await _database(tmp_path)
    reader = SimpleNamespace(read_events=AsyncMock(side_effect=AssertionError("history scan")))
    queue = RememberRetryQueue(
        object(), session_factory=factory, event_reader=reader, recovery_interval_seconds=0.01
    )
    try:
        await queue.start()
        await asyncio.sleep(0.05)
        await queue.stop()
        reader.read_events.assert_not_awaited()
        assert not hasattr(queue, "_reconciliation_task")
        assert not hasattr(queue, "_ledger_repair_task")
    finally:
        await queue.stop()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status, queued", [(409, False), (422, False), (429, True), (503, True)])
async def test_provider_errors_only_retry_transient_failures(status: int, queued: bool) -> None:
    response = httpx.Response(status, request=httpx.Request("POST", "http://mnemory/remember"))
    worker = SimpleNamespace(
        remember=AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "provider failure", request=response.request, response=response
            )
        )
    )
    queue = RememberRetryQueue(worker)
    await queue.enqueue(
        {
            "session_id": "session-1",
            "user_email": "user@example.com",
            "messages": [{"role": "assistant", "content": "remember"}],
        }
    )
    items = await queue._collect_ready_in_memory()
    await queue._process(items[0], asyncio.Semaphore(1))
    worker.remember.assert_awaited_once()
    assert bool(queue._items) is queued


async def _database(
    tmp_path: Path,
    *,
    session_count: int = 1,
) -> tuple[Any, Any]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/remember-reconciliation.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        session.add(User(email="user@example.com"))
        await session.flush()
        session.add(
            Agent(
                agent_id="agent-1",
                owner_email="user@example.com",
                name="Reconciliation agent",
            )
        )
        session.add(
            Conversation(
                conversation_id="conversation-1",
                user_email="user@example.com",
                agent_id="agent-1",
                context_type="chat",
            )
        )
        session.add_all(
            [
                Session(
                    session_id=f"session-{index}",
                    conversation_id="conversation-1",
                    user_email="user@example.com",
                    agent_id="agent-1",
                    intaris_session_id=f"intaris-{index}",
                    mnemory_session_id=f"mnemory-{index}",
                )
                for index in range(1, session_count + 1)
            ]
        )
        await session.commit()
    return engine, factory


def _marked_user_event(index: int = 1) -> dict[str, Any]:
    content = "repair this append"
    intaris_session_id = f"intaris-{index}"
    cognis_session_id = f"session-{index}"
    turn_id = f"turn-{index}"
    binding = build_evidence_event_binding(
        intaris_session_id=intaris_session_id,
        cognis_session_id=cognis_session_id,
        conversation_id="conversation-1",
        turn_id=turn_id,
        user_id="user@example.com",
        owner_id="user@example.com",
        source="user_input",
        role="user",
        prompt_visibility="user_visible",
        prompt_provenance={"kind": "user_authored"},
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        attachment_refs_value=[],
    )
    admission = build_evidence_admission(
        key=ADMISSION_KEY,
        admitted=True,
        owner_id="user@example.com",
        policy_fingerprint="0123456789abcdef",
        event_binding=binding,
        max_attempts=8,
        max_age_seconds=3600,
    )
    marker = build_marker(
        content=content,
        source="user_input",
        role="user",
        prompt_visibility="user_visible",
        prompt_provenance={"kind": "user_authored"},
        user_id="user@example.com",
        owner_id="user@example.com",
        intaris_session_id=intaris_session_id,
        cognis_session_id=cognis_session_id,
        conversation_id="conversation-1",
        turn_id=turn_id,
        attachment_refs_value=[],
        admission=admission,
        admission_key=ADMISSION_KEY,
    )
    return {
        "seq": 1,
        "type": "user_message",
        "data": {
            "source": "user_input",
            "role": "user",
            "prompt_visibility": "user_visible",
            "prompt_provenance": {"kind": "user_authored"},
            "user_visible_content": content,
            "attachments": [],
            "turn_id": turn_id,
            "trusted_evidence": marker,
        },
    }


@pytest.mark.asyncio
async def test_claims_alternate_between_ready_ordinary_and_evidence_work(
    tmp_path: Path,
) -> None:
    engine, factory = await _database(tmp_path)
    queue = RememberRetryQueue(object(), session_factory=factory, max_concurrent=1)
    await queue.enqueue(
        {
            "item_id": "evidence-item",
            "queue_kind": EVIDENCE_QUEUE_KIND,
            "session_id": "mnemory-1",
            "user_email": "user@example.com",
        }
    )
    await queue.enqueue(
        {
            "item_id": "ordinary-item",
            "session_id": "mnemory-1",
            "user_email": "user@example.com",
        }
    )

    ordinary = await queue._claim_due_durable_items(1)
    assert [item.item_id for item in ordinary] == ["ordinary-item"]
    async with factory() as session:
        row = await session.get(RememberQueueRow, "ordinary-item")
        assert row is not None
        row.status = "completed"
        row.lease_token = None
        row.lease_expires_at = None
        await session.commit()

    evidence = await queue._claim_due_durable_items(1)
    assert [item.item_id for item in evidence] == ["evidence-item"]
    await engine.dispose()


def _assistant_identity_payload(
    *,
    evidence_hash: str,
    assistant_hash: str,
) -> dict[str, Any]:
    evidence_id = deterministic_queue_id(EVIDENCE_QUEUE_KIND, evidence_hash)
    return {
        "session_id": "mnemory-1",
        "cognis_session_id": "session-1",
        "intaris_session_id": "intaris-1",
        "conversation_id": "conversation-1",
        "turn_id": "turn-1",
        "user_email": "user@example.com",
        "owner_email": "user@example.com",
        "agent_owner_email": "user@example.com",
        "agent_id": "agent-1",
        "policy_agent_id": "agent-1",
        "originating_memory_backend": "mnemory",
        "originating_agent_profile_id": None,
        "memory_policy_fingerprint": "policy-fingerprint",
        "queue_kind": ORDINARY_ASSISTANT_QUEUE_KIND,
        "item_id": deterministic_queue_id(
            ORDINARY_ASSISTANT_QUEUE_KIND,
            evidence_hash,
            assistant_hash,
        ),
        "event_hash": evidence_hash,
        "depends_on": evidence_id,
        "include_user_message": False,
        "user_event_seq": None,
        "assistant_event_seq": 2,
        "assistant_event_hash": assistant_hash,
    }


async def _seed_failed_pre_dispatch_assistant(
    factory: Any,
    payload: dict[str, Any],
) -> None:
    evidence_id = str(payload["depends_on"])
    evidence_payload = {
        key: value
        for key, value in payload.items()
        if key
        in {
            "session_id",
            "cognis_session_id",
            "intaris_session_id",
            "conversation_id",
            "turn_id",
            "user_email",
            "owner_email",
            "agent_owner_email",
            "agent_id",
            "policy_agent_id",
            "originating_memory_backend",
            "originating_agent_profile_id",
            "memory_policy_fingerprint",
            "event_hash",
        }
    }
    evidence_payload["queue_kind"] = EVIDENCE_QUEUE_KIND
    malformed_payload = dict(payload)
    malformed_payload.pop("event_hash")
    async with factory() as session:
        session.add_all(
            [
                RememberQueueRow(
                    item_id=evidence_id,
                    session_id=str(payload["session_id"]),
                    user_email=str(payload["user_email"]),
                    agent_id=str(payload["agent_id"]),
                    payload=evidence_payload,
                    status="accepted",
                    attempts=1,
                    next_retry_at=datetime.now(UTC),
                ),
                RememberQueueRow(
                    item_id=str(payload["item_id"]),
                    session_id=str(payload["session_id"]),
                    user_email=str(payload["user_email"]),
                    agent_id=str(payload["agent_id"]),
                    payload=malformed_payload,
                    status="failed",
                    attempts=1,
                    next_retry_at=datetime.now(UTC),
                    last_error="ordinary remember assertion conflict",
                ),
            ]
        )
        await session.commit()


@pytest.mark.asyncio
async def test_dispatch_remember_persists_assistant_source_event_hash() -> None:
    event = _marked_user_event()
    admission = event["data"]["trusted_evidence"][TRUSTED_EVIDENCE_ADMISSION_KEY]
    remember_queue = SimpleNamespace(enqueue=AsyncMock())
    loop = SimpleNamespace(
        remember_queue=remember_queue,
        trusted_evidence_admission_key=ADMISSION_KEY,
    )
    ctx = SimpleNamespace(
        memory_policy=SimpleNamespace(
            auto_remember=True,
            backend_id="mnemory",
            profile_id=None,
            policy_fingerprint="policy-fingerprint",
        ),
        session=SimpleNamespace(
            mnemory_session_id="mnemory-1",
            session_id="session-1",
            intaris_session_id="intaris-1",
            user_email="user@example.com",
            agent_id="agent-1",
        ),
        conversation=SimpleNamespace(conversation_id="conversation-1"),
        agent=SimpleNamespace(owner_email="user@example.com"),
        turn_id="turn-1",
        trusted_evidence_admission=admission,
        remember_evidence_event_hash="evidence-event-hash",
        remember_user_event_seq=1,
        remember_assistant_event_seq=2,
        remember_assistant_event_hash="assistant-event-hash",
    )

    await AgentLoop._dispatch_remember(loop, ctx, ["answer"])

    payload = remember_queue.enqueue.await_args.args[0]
    assert payload["event_hash"] == "evidence-event-hash"
    assert payload["item_id"] == deterministic_queue_id(
        ORDINARY_ASSISTANT_QUEUE_KIND,
        "evidence-event-hash",
        "assistant-event-hash",
    )


@pytest.mark.asyncio
async def test_reconciliation_repairs_proved_pre_dispatch_assistant_row(
    tmp_path: Path,
) -> None:
    engine, factory = await _database(tmp_path)
    assistant_event = {
        "seq": 2,
        "type": "assistant_message",
        "data": {"turn_id": "turn-1", "content": "answer"},
    }
    assistant_hash = event_hash("intaris-1", 2, assistant_event)
    payload = _assistant_identity_payload(
        evidence_hash="evidence-event-hash",
        assistant_hash=assistant_hash,
    )
    await _seed_failed_pre_dispatch_assistant(factory, payload)

    class Worker:
        def __init__(self) -> None:
            self.calls = 0

        async def remember(self, **_kwargs: object) -> None:
            self.calls += 1

    class Reader:
        async def read_events(self, **_kwargs: object) -> object:
            return SimpleNamespace(events=[assistant_event])

    worker = Worker()
    queue = RememberRetryQueue(
        worker,
        session_factory=factory,
        event_reader=Reader(),
    )

    await queue.enqueue(payload)
    await queue.enqueue(payload)
    claimed = await queue._claim_due_durable_items(1)
    assert len(claimed) == 1
    await queue._process(claimed[0], asyncio.Semaphore(1))

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    sa.select(RememberQueueRow).where(
                        RememberQueueRow.item_id == payload["item_id"]
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert rows[0].attempts == 1
    assert rows[0].last_error is None
    assert rows[0].payload["event_hash"] == "evidence-event-hash"
    assert rows[0].payload["depends_on"] == payload["depends_on"]
    assert worker.calls == 1
    assert await queue._claim_due_durable_items(1) == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_scheduled_reconciliation_leaves_failed_assistant_memory_terminal(
    tmp_path: Path,
) -> None:
    engine, factory = await _database(tmp_path)
    payload = _assistant_identity_payload(
        evidence_hash="evidence-event-hash",
        assistant_hash="assistant-event-hash",
    )
    await _seed_failed_pre_dispatch_assistant(factory, payload)

    class Reader:
        async def read_events(self, **_kwargs: object) -> object:
            return SimpleNamespace(events=[])

    queue = RememberRetryQueue(object(), session_factory=factory, event_reader=Reader())

    await queue.start()
    await queue.stop()

    async with factory() as session:
        row = await session.get(RememberQueueRow, str(payload["item_id"]))
    assert row is not None
    assert row.status == "failed"
    assert row.attempts == 1
    assert row.last_error == "ordinary remember assertion conflict"
    assert "event_hash" not in row.payload
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cognis_session_id", "other-cognis-session"),
        ("intaris_session_id", "other-intaris-session"),
        ("assistant_event_seq", 3),
        ("owner_email", "other@example.com"),
        ("depends_on", "rq_evidence_unrecognized"),
    ],
)
async def test_reconciliation_rejects_unproved_assistant_identity_repairs(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    engine, factory = await _database(tmp_path)
    payload = _assistant_identity_payload(
        evidence_hash="evidence-event-hash",
        assistant_hash="assistant-event-hash",
    )
    await _seed_failed_pre_dispatch_assistant(factory, payload)
    incoming = {**payload, field: value}
    queue = RememberRetryQueue(object(), session_factory=factory)

    with pytest.raises(ValueError, match="deterministic queue identity payload conflict"):
        await queue.enqueue(incoming)

    async with factory() as session:
        row = await session.get(RememberQueueRow, str(payload["item_id"]))
    assert row is not None
    assert row.status == "failed"
    assert row.attempts == 1
    assert "event_hash" not in row.payload
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence_session_id",
    [None, "mnemory-before-adoption", "other-mnemory-session"],
)
async def test_reconciliation_accepts_mutable_evidence_memory_destination(
    tmp_path: Path,
    evidence_session_id: str | None,
) -> None:
    engine, factory = await _database(tmp_path)
    payload = _assistant_identity_payload(
        evidence_hash="evidence-event-hash",
        assistant_hash="assistant-event-hash",
    )
    await _seed_failed_pre_dispatch_assistant(factory, payload)
    async with factory() as session:
        dependency = await session.get(RememberQueueRow, str(payload["depends_on"]))
        assert dependency is not None
        dependency.payload = {
            **dependency.payload,
            "session_id": evidence_session_id,
        }
        dependency.session_id = evidence_session_id or "session-1"
        await session.commit()
    queue = RememberRetryQueue(object(), session_factory=factory)

    await queue.enqueue(payload)

    async with factory() as session:
        row = await session.get(RememberQueueRow, str(payload["item_id"]))
    assert row is not None
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.payload["event_hash"] == "evidence-event-hash"
    assert row.payload["session_id"] == "mnemory-1"
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row_updates",
    [
        {"status": "completed"},
        {"status": "ambiguous"},
        {"attempts": 2},
        {"last_error": "provider outcome unknown"},
        {"lease_token": "active-lease"},
    ],
)
async def test_reconciliation_does_not_retry_completed_or_uncertain_assistant_rows(
    tmp_path: Path,
    row_updates: dict[str, object],
) -> None:
    engine, factory = await _database(tmp_path)
    payload = _assistant_identity_payload(
        evidence_hash="evidence-event-hash",
        assistant_hash="assistant-event-hash",
    )
    await _seed_failed_pre_dispatch_assistant(factory, payload)
    async with factory() as session:
        await session.execute(
            sa.update(RememberQueueRow)
            .where(RememberQueueRow.item_id == payload["item_id"])
            .values(**row_updates)
        )
        await session.commit()
    queue = RememberRetryQueue(object(), session_factory=factory)

    with pytest.raises(ValueError, match="deterministic queue identity payload conflict"):
        await queue.enqueue(payload)

    async with factory() as session:
        row = await session.get(RememberQueueRow, str(payload["item_id"]))
    assert row is not None
    assert row.status == row_updates.get("status", "failed")
    assert row.attempts == row_updates.get("attempts", 1)
    assert row.last_error == row_updates.get("last_error", "ordinary remember assertion conflict")
    assert row.lease_token == row_updates.get("lease_token")
    assert "event_hash" not in row.payload
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cognis_session_id", "other-cognis-session"),
        ("intaris_session_id", "other-intaris-session"),
    ],
)
async def test_reconciliation_rejects_evidence_dependency_source_session_mismatch(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    engine, factory = await _database(tmp_path)
    payload = _assistant_identity_payload(
        evidence_hash="evidence-event-hash",
        assistant_hash="assistant-event-hash",
    )
    await _seed_failed_pre_dispatch_assistant(factory, payload)
    async with factory() as session:
        dependency = await session.get(RememberQueueRow, str(payload["depends_on"]))
        assert dependency is not None
        dependency.payload = {**dependency.payload, field: value}
        await session.commit()
    queue = RememberRetryQueue(object(), session_factory=factory)

    with pytest.raises(ValueError, match="deterministic queue identity payload conflict"):
        await queue.enqueue(payload)

    async with factory() as session:
        row = await session.get(RememberQueueRow, str(payload["item_id"]))
    assert row is not None
    assert row.status == "failed"
    assert row.attempts == 1
    assert "event_hash" not in row.payload
    await engine.dispose()
