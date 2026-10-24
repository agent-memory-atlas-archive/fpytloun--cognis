from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cognis.api.app import create_app
from cognis.store.models import Conversation, ManagedConversationLink, NotificationRow
from cognis.store.queries import create_agent, create_user


def test_topic_attention_excludes_hidden_surfaces_until_channel_filter_is_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COGNIS_HOST", "127.0.0.1")
    now = datetime.now(UTC)
    excluded = [
        ("matrix", "matrix", {}, None),
        ("signal", "signal", {}, None),
        ("slack", "slack", {}, None),
        ("task-history", "task", {}, None),
        ("managed-context", "agent_work", {}, None),
        ("managed-web", "web", {"kind": "managed_agent_conversation"}, None),
        ("agent-work-web", "web", {"kind": "agent_work"}, None),
        ("control", "web", {"kind": "task_control"}, None),
        ("direct", "web", {"kind": "agent_direct"}, None),
        ("main", "web", {"kind": "main"}, None),
        ("external", "web", {"kind": "external"}, None),
        ("channel", "web", {"kind": "channel"}, None),
        ("legacy-direct", "web", {}, "web:agent_direct:riker"),
        ("legacy-main", "web", {}, "web:user:owner:default"),
        ("normalized-kind", "web", {"kind": " Channel "}, None),
        ("managed-link", "web", {}, None),
    ]
    with TestClient(create_app()) as client:

        async def seed() -> None:
            async with client.app.state.session_factory() as db:
                for owner in ("owner@example.com", "foreign@example.com"):
                    await create_user(db, email=owner, name="Owner", password_hash="unused")
                    await create_agent(db, agent_id=owner, owner_email=owner, name="Owner")
                for cid, context, data, ref in excluded:
                    db.add(
                        Conversation(
                            conversation_id=cid,
                            user_email="owner@example.com",
                            agent_id="owner@example.com",
                            context_type=context,
                            context_data=data,
                            context_ref=ref,
                            last_message_at=now,
                        )
                    )
                db.add(
                    Conversation(
                        conversation_id="read-controller",
                        user_email="owner@example.com",
                        agent_id="owner@example.com",
                        context_type="web",
                        last_message_at=now,
                        last_read_at=now,
                    )
                )
                await db.flush()
                db.add(
                    ManagedConversationLink(
                        link_id="managed-target-link",
                        user_email="owner@example.com",
                        controller_agent_id="owner@example.com",
                        controller_conversation_id="read-controller",
                        target_agent_id="owner@example.com",
                        target_conversation_id="managed-link",
                        conversation_state="open",
                        turn_state="idle",
                    )
                )
                for cid, _, _, _ in excluded:
                    db.add(
                        NotificationRow(
                            notification_id=f"gate-{cid}",
                            conversation_id=cid,
                            user_email="owner@example.com",
                            notification_type="gate",
                            status="pending",
                        )
                    )
                await db.commit()

        client.portal.call(seed)
        token = client.app.state.auth_provider.sign_access_token(
            "owner@example.com", "Owner", "admin"
        )
        headers = {"Authorization": f"Bearer {token}"}

        def unread_count() -> int:
            response = client.get("/api/v1/dashboard/navigation-summary", headers=headers)
            assert response.status_code == 200, response.text
            groups = response.json()["chat_groups"]
            assert all(not row["pending_notification_types"] for row in groups)
            return sum(row["count"] for row in groups if row["has_unread"])

        assert unread_count() == 0
        for query in ("", "?context_type=web"):
            response = client.get(f"/api/v1/conversations/waiting{query}", headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["conversations"]["items"] == []
        explicit = client.get("/api/v1/conversations/waiting?context_type=matrix", headers=headers)
        assert explicit.status_code == 200, explicit.text
        assert [row["conversation_id"] for row in explicit.json()["conversations"]["items"]] == [
            "matrix"
        ]
        assert unread_count() == 0  # Explicit channel views do not broaden the global topic badge.

        async def seed_topics() -> None:
            async with client.app.state.session_factory() as db:
                for cid, owner, status in (
                    ("topic-unread", "owner@example.com", "active"),
                    ("topic-gate", "owner@example.com", "active"),
                    ("topic-archived", "owner@example.com", "archived"),
                    ("topic-foreign", "foreign@example.com", "active"),
                ):
                    db.add(
                        Conversation(
                            conversation_id=cid,
                            user_email=owner,
                            agent_id=owner,
                            context_type="web",
                            status=status,
                            last_message_at=now,
                            last_read_at=now if cid == "topic-gate" else None,
                        )
                    )
                await db.flush()
                # Another owner's metadata must not hide an owned topic.
                db.add(
                    ManagedConversationLink(
                        link_id="foreign-topic-link",
                        user_email="foreign@example.com",
                        controller_agent_id="foreign@example.com",
                        controller_conversation_id="topic-foreign",
                        target_agent_id="owner@example.com",
                        target_conversation_id="topic-unread",
                        conversation_state="open",
                        turn_state="idle",
                    )
                )
                db.add(
                    NotificationRow(
                        notification_id="gate-topic",
                        conversation_id="topic-gate",
                        user_email="owner@example.com",
                        notification_type="gate",
                        status="pending",
                    )
                )
                await db.commit()

        client.portal.call(seed_topics)
        response = client.get("/api/v1/conversations/waiting?limit=1", headers=headers)
        topic_cursor = response.json()["conversations"]["cursor"]
        assert topic_cursor
        for params in (
            {"cursor": topic_cursor, "context_type": "matrix"},
            {"cursor": topic_cursor, "context_types": ["web", "matrix"]},
        ):
            rejected = client.get("/api/v1/conversations/waiting", params=params, headers=headers)
            assert rejected.status_code == 400
        web_page = client.get(
            "/api/v1/conversations/waiting?limit=1&context_type=web", headers=headers
        ).json()["conversations"]
        assert web_page["cursor"]
        assert (
            client.get(
                "/api/v1/conversations/waiting",
                params={"cursor": web_page["cursor"], "context_type": "signal"},
                headers=headers,
            ).status_code
            == 400
        )
        ids = set()
        while True:
            assert response.status_code == 200, response.text
            page = response.json()["conversations"]
            ids.update(row["conversation_id"] for row in page["items"])
            if not page["has_more"]:
                break
            response = client.get(
                "/api/v1/conversations/waiting",
                params={"limit": 1, "cursor": page["cursor"]},
                headers=headers,
            )
        assert ids == {"topic-unread", "topic-gate"}
        summary = client.get("/api/v1/dashboard/navigation-summary", headers=headers).json()
        contributing = [
            g for g in summary["chat_groups"] if g["has_unread"] or g["pending_notification_types"]
        ]
        assert sum(g["count"] for g in contributing) == len(ids)
        assert any(g["pending_notification_types"] == ["gate"] for g in contributing)
