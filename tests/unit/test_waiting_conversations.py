import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import schema as sa_schema
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cognis.api.app import create_app
from cognis.store.models import Base, Conversation, NotificationRow
from cognis.store.queries import create_agent, create_user, list_conversations


def test_waiting_candidates_are_complete_scoped_and_independent_of_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COGNIS_HOST", "127.0.0.1")
    now = datetime.now(UTC)
    with TestClient(create_app()) as client:

        async def seed() -> None:
            async with client.app.state.session_factory() as db:
                for email in ("owner@example.com", "other@example.com"):
                    await create_user(db, email=email, name="Owner", password_hash="unused")
                    await create_agent(db, agent_id=email, owner_email=email, name="Owner")
                for i in range(70):
                    db.add(
                        Conversation(
                            conversation_id=f"recent-{i:03}",
                            user_email="owner@example.com",
                            agent_id="owner@example.com",
                            context_type="web",
                            last_message_at=now,
                            last_read_at=now,
                        )
                    )
                for i, context in enumerate(("web", "matrix", "signal", "agent_work")):
                    db.add(
                        Conversation(
                            conversation_id=f"old-{i}",
                            title=f"Old {context}",
                            user_email="owner@example.com",
                            agent_id="owner@example.com",
                            context_type=context,
                            last_message_at=now - timedelta(days=90),
                            context_data={"kind": "managed_agent_conversation"}
                            if context == "agent_work"
                            else {},
                        )
                    )
                for cid, owner, context, data, status in (
                    ("internal", "owner@example.com", "task", {}, "active"),
                    ("control", "owner@example.com", "web", {"kind": "task_control"}, "active"),
                    ("direct", "owner@example.com", "web", {"kind": "agent_direct"}, "active"),
                    ("archived", "owner@example.com", "web", {}, "archived"),
                    ("foreign", "other@example.com", "web", {}, "active"),
                ):
                    db.add(
                        Conversation(
                            conversation_id=cid,
                            user_email=owner,
                            agent_id=owner,
                            context_type=context,
                            context_data=data,
                            status=status,
                            last_message_at=now,
                        )
                    )
                db.add(
                    Conversation(
                        conversation_id="read-question",
                        user_email="owner@example.com",
                        agent_id="owner@example.com",
                        context_type="web",
                        last_message_at=None,
                        last_read_at=now,
                    )
                )
                await db.flush()
                db.add(
                    NotificationRow(
                        notification_id="question-read",
                        conversation_id="read-question",
                        user_email="owner@example.com",
                        notification_type="step_question",
                        status="pending",
                    )
                )
                await db.commit()

        client.portal.call(seed)
        token = client.app.state.auth_provider.sign_access_token(
            "owner@example.com", "Owner", "admin"
        )
        headers = {"Authorization": f"Bearer {token}"}
        history = client.get("/api/v1/conversations?limit=50", headers=headers).json()
        assert not any(row["conversation_id"].startswith("old-") for row in history["items"])
        ids: set[str] = set()
        cursor = None
        while True:
            response = client.get(
                "/api/v1/conversations/waiting",
                headers=headers,
                params={
                    "limit": 1,
                    **({"cursor": cursor} if cursor else {}),
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["active_conversation_ids"] == []
            page = body["conversations"]
            ids.update(item["conversation_id"] for item in page["items"])
            if not page["has_more"]:
                break
            cursor = page["cursor"]
            assert cursor
        assert ids == {"old-0", "read-question"}
        scoped = client.get(
            "/api/v1/conversations/waiting?context_type=matrix", headers=headers
        ).json()
        assert [row["conversation_id"] for row in scoped["conversations"]["items"]] == ["old-1"]
        summary = client.get("/api/v1/dashboard/navigation-summary", headers=headers).json()
        assert sum(
            g["count"]
            for g in summary["chat_groups"]
            if g["has_unread"] or "step_question" in g["pending_notification_types"]
        ) == len(ids)
        assert client.post("/api/v1/conversations/old-0/read", headers=headers).status_code == 200
        remaining = client.get("/api/v1/conversations/waiting", headers=headers).json()
        assert "old-0" not in {
            row["conversation_id"] for row in remaining["conversations"]["items"]
        }
        invalid_cursor = client.get(
            "/api/v1/conversations/waiting",
            headers=headers,
            params={
                "cursor": history["cursor"],
            },
        )
        assert invalid_cursor.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_waiting_null_message_timestamp_keyset_is_portable(
    tmp_path: Path, backend: str
) -> None:
    admin = None
    schema = None
    if backend == "postgres":
        url = os.getenv("COGNIS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("COGNIS_TEST_POSTGRES_URL is not configured")
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        schema = f"waiting_keyset_{uuid4().hex}"
        admin = create_async_engine(url)
        async with admin.begin() as connection:
            await connection.execute(sa_schema.CreateSchema(schema))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'waiting.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(UTC)
        async with sessions() as db:
            await create_user(db, email="owner@example.com", name="Owner", password_hash="unused")
            await create_agent(db, agent_id="owner", owner_email="owner@example.com", name="Owner")
            for index, last in enumerate((now, None, None)):
                db.add(
                    Conversation(
                        conversation_id=f"candidate-{index}",
                        user_email="owner@example.com",
                        agent_id="owner",
                        context_type="web",
                        last_message_at=last,
                        created_at=now - timedelta(days=index + 1),
                    )
                )
            await db.flush()
            for index in (1, 2):
                db.add(
                    NotificationRow(
                        notification_id=f"gate-{index}",
                        conversation_id=f"candidate-{index}",
                        user_email="owner@example.com",
                        notification_type="gate",
                        status="pending",
                    )
                )
            await db.commit()
            ids = []
            after = None
            while True:
                items = await list_conversations(
                    db,
                    user_email="owner@example.com",
                    include_agent_direct=False,
                    waiting_candidates=True,
                    limit=1,
                    cursor_id=after,
                )
                if not items:
                    break
                after = items[0].conversation_id
                assert after not in ids
                ids.append(after)
            assert ids == ["candidate-0", "candidate-1", "candidate-2"]
    finally:
        await engine.dispose()
        if admin is not None:
            async with admin.begin() as connection:
                await connection.execute(sa_schema.DropSchema(schema, cascade=True))
            await admin.dispose()
