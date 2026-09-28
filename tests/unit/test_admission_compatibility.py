"""Legacy fixtures use the published, unversioned descriptor, not the new helper."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import schema as sa_schema
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from cognis.core.trusted_evidence import (
    build_evidence_admission,
    build_evidence_event_binding,
    serialize_evidence_admission,
)
from cognis.store.database import create_session_factory
from cognis.store.direct_turns import (
    DirectTurnAdmissionRejected,
    DirectTurnConflictError,
    DirectTurnStore,
)
from cognis.store.models import Base, DirectTurnRequestRow
from cognis.store.queries import create_agent, create_conversation, create_user


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _evidence(fingerprint):
    return serialize_evidence_admission(
        build_evidence_admission(
            key=b"",
            admitted=False,
            owner_id=None,
            policy_fingerprint=fingerprint,
            event_binding=build_evidence_event_binding(
                intaris_session_id="stream-1",
                cognis_session_id="session-1",
                conversation_id="conv-a",
                turn_id="turn-1",
                user_id="user@example.com",
                owner_id="user@example.com",
                source="user_input",
                role="user",
                prompt_visibility="user_visible",
                prompt_provenance={"kind": "user_authored"},
                content_hash=hashlib.sha256(b"request").hexdigest(),
                attachment_refs_value=[],
            ),
        )
    )


@pytest_asyncio.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.integration)])
async def admission_db(request, tmp_path):
    admin = None
    schema = None
    if request.param == "postgres":
        url = os.environ.get("COGNIS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("COGNIS_TEST_POSTGRES_URL is not configured")
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        admin = create_async_engine(url)
        schema = f"admission_compat_{uuid.uuid4().hex}"
        async with admin.begin() as connection:
            await connection.execute(sa_schema.CreateSchema(schema))
        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": f'"{schema}"'}}
        )
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compat.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            await create_user(session, email="user@example.com", name="User", password_hash="hash")
            await create_agent(
                session,
                agent_id="agent-1",
                owner_email="user@example.com",
                name="Agent",
                status="active",
            )
            await create_conversation(
                session,
                user_email="user@example.com",
                agent_id="agent-1",
                context_type="web",
                conversation_id="conv-a",
            )
            await session.commit()
        yield factory, DirectTurnStore(factory)
    finally:
        await engine.dispose()
        if admin is not None:
            async with admin.begin() as connection:
                await connection.execute(sa_schema.DropSchema(schema, cascade=True))
            await admin.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("completed", [False, True])
@pytest.mark.parametrize("generated", [False, True])
async def test_exact_legacy_and_new_replay_matrix(admission_db, legacy, completed, generated):
    factory, store = admission_db
    payload = {
        "schema_version": 1,
        "content": "request",
        "attachments": [],
        "channel_delivery": None,
        "metadata": {
            "user_message_metadata": {"ts": "2026-01-01T00:00:00Z", "sender": "Alice"},
            "trusted_evidence_admission": _evidence("before"),
        },
    }
    args = dict(
        conversation_id="conv-a",
        session_id=None,
        agent_id="agent-1",
        user_id="user@example.com",
        idempotency_scope="web:conv-a:user@example.com",
        idempotency_key="compatibility",
        generated_user_message_metadata=generated,
    )
    if legacy:
        legacy_payload = copy.deepcopy(payload)
        legacy_payload["metadata"].pop("trusted_evidence_admission")
        descriptor = {
            "conversation_id": args["conversation_id"],
            "agent_id": args["agent_id"],
            "user_id": args["user_id"],
            "payload_version": 1,
            "payload": legacy_payload,
        }
        # Seed exactly the published v0.17.0 row format. No origin is persisted
        # or inferred: generated/explicit here describe the incoming caller.
        async with factory() as session:
            row = DirectTurnRequestRow(
                request_id=f"dtr_{uuid.uuid4().hex}",
                turn_id=f"turn_{uuid.uuid4().hex}",
                **{k: v for k, v in args.items() if k != "generated_user_message_metadata"},
                admission_hash=_hash(descriptor),
                payload_hash=_hash(payload),
                payload_version=1,
                payload=payload,
                status="completed" if completed else "queued",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                attempt_count=0,
            )
            session.add(row)
            await session.commit()
        first = row
    else:
        first = (await store.admit(**args, payload=payload)).request
        if completed:
            # Fixture setup only; production replay must never change state.
            async with factory() as session:
                row = (
                    await session.execute(
                        select(DirectTurnRequestRow).where(
                            DirectTurnRequestRow.request_id == first.request_id
                        )
                    )
                ).scalar_one()
                row.status = "completed"
                await session.commit()
    original_hash = first.admission_hash
    replays = await asyncio.gather(*(store.admit(**args, payload=payload) for _ in range(4)))
    assert all(not r.created and r.request.request_id == first.request_id for r in replays)
    assert all(r.request.admission_hash == original_hash for r in replays)

    calls = []

    async def reject_guard(session):
        return False

    async def participant(session, row, created):
        calls.append((row.request_id, created))

    with pytest.raises(DirectTurnAdmissionRejected):
        await store.admit(
            **args,
            payload=payload,
            admission_guard=reject_guard,
            transaction_participant=participant,
        )
    assert calls == []
    await store.admit(**args, payload=payload, transaction_participant=participant)
    assert calls == [(first.request_id, False)]

    async def rejecting_participant(session, row, created):
        assert not created
        row.status = "failed"
        await session.flush()
        raise DirectTurnAdmissionRejected("test participant rejected replay")

    with pytest.raises(DirectTurnAdmissionRejected):
        await store.admit(**args, payload=payload, transaction_participant=rejecting_participant)

    for changed in ("ts", "sender", "content", "origin", "evidence"):
        candidate = copy.deepcopy(payload)
        candidate_args = dict(args)
        if changed == "ts":
            candidate["metadata"]["user_message_metadata"]["ts"] = "2026-01-01T00:00:01Z"
        elif changed == "sender":
            candidate["metadata"]["user_message_metadata"]["sender"] = "Bob"
        elif changed == "content":
            candidate["content"] = "another request"
        elif changed == "origin":
            candidate_args["generated_user_message_metadata"] = not generated
        else:
            candidate["metadata"]["trusted_evidence_admission"] = _evidence("after")
        allowed = (
            (not legacy and generated and changed == "ts")
            or (legacy and changed == "origin")
            or changed == "evidence"
        )
        if allowed:
            replay = await store.admit(**candidate_args, payload=candidate)
            assert not replay.created
            assert replay.request.payload == payload
        else:
            with pytest.raises(DirectTurnConflictError):
                await store.admit(**candidate_args, payload=candidate)
    async with factory() as session:
        rows = (await session.execute(select(DirectTurnRequestRow))).scalars().all()
        assert len(rows) == 1
        assert rows[0].admission_hash == original_hash
        assert rows[0].payload_hash == _hash(payload)
        assert rows[0].payload == payload
        assert rows[0].status == ("completed" if completed else "queued")


@pytest.mark.asyncio
@pytest.mark.parametrize("generated", [False, True])
async def test_new_concurrent_admission_has_one_winner(admission_db, generated):
    factory, store = admission_db
    args = dict(
        conversation_id="conv-a",
        session_id=None,
        agent_id="agent-1",
        user_id="user@example.com",
        idempotency_scope="concurrency",
        idempotency_key="same-request",
        generated_user_message_metadata=generated,
        payload={
            "schema_version": 1,
            "content": "",
            "attachments": [],
            "metadata": {"user_message_metadata": {"ts": "2026-01-01T00:00:00Z"}},
        },
    )
    results = await asyncio.gather(*(store.admit(**args) for _ in range(4)))
    assert sum(r.created for r in results) == 1
    assert len({r.request.request_id for r in results}) == 1
