from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from cognis.api.app import create_app
from cognis.store.models import (
    Conversation,
    ManagedConversationLink,
    NotificationRow,
    Schedule,
    Session,
    Task,
)
from cognis.store.queries import create_agent, create_user


def test_navigation_summary_is_complete_owner_scoped_and_live(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COGNIS_HOST", "127.0.0.1")
    now = datetime.now(UTC)
    with TestClient(create_app()) as client:

        async def seed() -> None:
            async with client.app.state.session_factory() as db:
                for email in ("owner@example.com", "other@example.com"):
                    await create_user(db, email=email, name=email, password_hash="unused")
                    await create_agent(db, agent_id=f"agent-{email}", owner_email=email, name=email)
                    for index in range(510 if email.startswith("owner") else 1):
                        db.add(
                            Conversation(
                                conversation_id=f"conv-{email}-{index}",
                                user_email=email,
                                agent_id=f"agent-{email}",
                                context_type="web",
                                last_message_at=now,
                                status="active",
                            )
                        )
                        db.add(
                            Task(
                                task_id=f"task-{email}-{index}",
                                title="Waiting",
                                created_by=email,
                                agent_id=f"agent-{email}",
                                status="paused",
                            )
                        )
                        db.add(
                            Schedule(
                                schedule_id=f"sched-{email}-{index}",
                                name="Failed schedule",
                                schedule_type="interval",
                                interval_seconds=60,
                                agent_id=f"agent-{email}",
                                task_template={},
                                created_by=email,
                                last_run_status="failed",
                                enabled=True,
                            )
                        )
                db.add(
                    Conversation(
                        conversation_id="archived",
                        user_email="owner@example.com",
                        agent_id="agent-owner@example.com",
                        context_type="web",
                        last_message_at=now,
                        status="archived",
                    )
                )
                db.add(
                    Conversation(
                        conversation_id="observed",
                        user_email="owner@example.com",
                        agent_id="agent-owner@example.com",
                        context_type="web",
                        active_session_id="observed-session",
                        last_read_at=now,
                    )
                )
                await db.flush()
                db.add(
                    Session(
                        session_id="observed-session",
                        conversation_id="observed",
                        user_email="owner@example.com",
                        agent_id="agent-owner@example.com",
                        status="failed",
                        updated_at=now - timedelta(seconds=1),
                    )
                )
                for index, notification_type in enumerate(
                    ["escalation", "escalation", "agent_question"]
                ):
                    db.add(
                        NotificationRow(
                            notification_id=f"pending-{index}",
                            user_email="owner@example.com",
                            conversation_id="observed",
                            notification_type=notification_type,
                            status="pending",
                        )
                    )
                db.add(
                    Schedule(
                        schedule_id="auto-disabled",
                        name="Disabled",
                        schedule_type="interval",
                        agent_id="agent-owner@example.com",
                        task_template={},
                        created_by="owner@example.com",
                        enabled=False,
                        disabled_reason="auto_consecutive_failures:3",
                        last_run_status="failed",
                    )
                )
                await db.commit()

        client.portal.call(seed)
        token = client.app.state.auth_provider.sign_access_token(
            "owner@example.com", "Owner", "admin"
        )
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/dashboard/navigation-summary").status_code == 401
        response = client.get("/api/v1/dashboard/navigation-summary", headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["tasks"] == 510
        assert data["schedules"] == 511
        assert data["dashboard"]["total"] == 511
        assert data["dashboard"]["truncated"] is False
        assert sum(group["count"] for group in data["chat_groups"]) == 511
        observed = next(group for group in data["chat_groups"] if group["session_observed"])
        assert observed["pending_notification_types"] == ["escalation"]
        assert observed["count"] == 1
        assert observed["has_unread"] is False
        assert "other@example.com" not in response.text
        assert "conv-" not in response.text

        issue = next(
            issue
            for issue in client.get("/api/v1/dashboard/issues", headers=headers).json()["issues"]
            if issue["resource"]["id"] == "auto-disabled"
        )
        assert (
            client.post(
                "/api/v1/dashboard/issues/schedules/auto-disabled/dismiss",
                headers=headers,
                json={"incident_token": issue["dismiss_token"]},
            ).status_code
            == 200
        )

        async def recover() -> None:
            async with client.app.state.session_factory() as db:
                schedule = await db.get(Schedule, "sched-owner@example.com-0")
                assert schedule is not None
                schedule.last_run_status = "completed"
                task = await db.get(Task, "task-owner@example.com-0")
                assert task is not None
                task.status = "running"
                notification = await db.get(NotificationRow, "pending-0")
                assert notification is not None
                notification.status = "resolved"
                notification = await db.get(NotificationRow, "pending-1")
                assert notification is not None
                notification.status = "resolved"
                await db.commit()

        client.portal.call(recover)
        data = client.get("/api/v1/dashboard/navigation-summary", headers=headers).json()
        assert data["tasks"] == 509
        assert data["schedules"] == 509
        observed = next(group for group in data["chat_groups"] if group["session_observed"])
        assert observed["pending_notification_types"] == []


def test_chat_badge_excludes_internal_execution_history_and_its_attention(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COGNIS_HOST", "127.0.0.1")
    now = datetime.now(UTC)
    with TestClient(create_app()) as client:

        async def seed() -> None:
            async with client.app.state.session_factory() as db:
                await create_user(
                    db, email="owner@example.com", name="Owner", password_hash="unused"
                )
                await create_agent(
                    db, agent_id="agent-owner", owner_email="owner@example.com", name="Owner"
                )
                for index in range(5236):
                    db.add(
                        Conversation(
                            conversation_id=f"workflow-history-{index}",
                            user_email="owner@example.com",
                            agent_id="agent-owner",
                            context_type="task",
                            last_message_at=now,
                            active_session_id="internal-paused" if index == 0 else None,
                        )
                    )
                db.add(
                    Conversation(
                        conversation_id="control-chat",
                        user_email="owner@example.com",
                        agent_id="agent-owner",
                        context_type="web",
                        context_data={"kind": "task_control"},
                        last_message_at=now,
                    )
                )
                await db.flush()
                db.add(
                    Session(
                        session_id="internal-paused",
                        conversation_id="workflow-history-0",
                        user_email="owner@example.com",
                        agent_id="agent-owner",
                        status="paused",
                    )
                )
                for conversation_id in ("workflow-history-0", "control-chat"):
                    db.add(
                        NotificationRow(
                            notification_id=f"notification-{conversation_id}",
                            conversation_id=conversation_id,
                            user_email="owner@example.com",
                            notification_type="question",
                            status="pending",
                        )
                    )
                await db.commit()

        client.portal.call(seed)
        token = client.app.state.auth_provider.sign_access_token(
            "owner@example.com", "Owner", "admin"
        )
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get("/api/v1/dashboard/navigation-summary", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["chat_groups"] == []

        async def seed_chats() -> None:
            async with client.app.state.session_factory() as db:
                for context_type, kind in (
                    ("web", None),
                    ("signal", None),
                    ("web", "agent_direct"),
                    ("agent_work", "managed_agent_conversation"),
                ):
                    db.add(
                        Conversation(
                            conversation_id=f"chat-{context_type}-{kind}",
                            user_email="owner@example.com",
                            agent_id="agent-owner",
                            context_type=context_type,
                            context_data={"kind": kind},
                            last_message_at=now,
                        )
                    )
                await db.commit()

        client.portal.call(seed_chats)
        groups = client.get("/api/v1/dashboard/navigation-summary", headers=headers).json()[
            "chat_groups"
        ]
        assert sum(group["count"] for group in groups) == 1
        assert all(group["has_unread"] for group in groups)
        assert all(not group["pending_notification_types"] for group in groups)
        assert all(group["active_session_status"] is None for group in groups)


def test_navigation_activity_uses_sidebar_runtime_and_background_owners(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COGNIS_HOST", "127.0.0.1")
    now = datetime.now(UTC)
    with TestClient(create_app()) as client:

        async def seed() -> None:
            async with client.app.state.session_factory() as db:
                await create_user(
                    db, email="owner@example.com", name="Owner", password_hash="unused"
                )
                await create_agent(
                    db, agent_id="agent-owner", owner_email="owner@example.com", name="Owner"
                )
                for conversation_id in ("running", "background", "unread", "paused-background"):
                    db.add(
                        Conversation(
                            conversation_id=conversation_id,
                            user_email="owner@example.com",
                            agent_id="agent-owner",
                            context_type="web",
                            last_message_at=now,
                        )
                    )
                await db.commit()

        client.portal.call(seed)
        scheduler = client.app.state.turn_scheduler
        monkeypatch.setattr(
            scheduler,
            "durable_running_turn_states",
            AsyncMock(return_value={"running": {"turn_id": "turn-running"}}),
        )
        from cognis.api.routes import conversations

        monkeypatch.setattr(conversations, "_active_background_shells", AsyncMock(return_value=[]))
        background = AsyncMock(
            return_value=SimpleNamespace(
                items=[
                    SimpleNamespace(
                        kind="background_command",
                        status="running",
                        controller_conversation_id="background",
                    ),
                    SimpleNamespace(
                        kind="task", status="paused", controller_conversation_id="paused-background"
                    ),
                ]
            )
        )
        monkeypatch.setattr(conversations, "_background_work_projection", background)
        token = client.app.state.auth_provider.sign_access_token(
            "owner@example.com", "Owner", "admin"
        )
        response = client.get(
            "/api/v1/dashboard/navigation-summary", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200, response.text
        groups = response.json()["chat_groups"]
        assert sum(group["count"] for group in groups if group["is_active"]) == 2
        assert sum(group["count"] for group in groups if not group["is_active"]) == 2
        assert all(group["has_unread"] for group in groups)
        scheduler.durable_running_turn_states.assert_awaited()
        background.assert_awaited_once()


def test_navigation_activity_matches_real_managed_and_attached_task_projection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COGNIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COGNIS_HOST", "127.0.0.1")
    now = datetime.now(UTC)
    with TestClient(create_app()) as client:

        async def seed() -> None:
            async with client.app.state.session_factory() as db:
                await create_user(
                    db, email="owner@example.com", name="Owner", password_hash="unused"
                )
                await create_agent(
                    db, agent_id="agent-owner", owner_email="owner@example.com", name="Owner"
                )
                for conversation_id in (
                    "controller",
                    "target-queued",
                    "target-waiting",
                    "task-owner",
                    "idle",
                ):
                    db.add(
                        Conversation(
                            conversation_id=conversation_id,
                            user_email="owner@example.com",
                            agent_id="agent-owner",
                            active_session_id="controller-session"
                            if conversation_id == "controller"
                            else None,
                            context_type="agent_work"
                            if conversation_id.startswith("target-")
                            else "web",
                            context_data={"kind": "managed_agent_conversation"}
                            if conversation_id.startswith("target-")
                            else {},
                            last_message_at=now,
                        )
                    )
                await db.flush()
                db.add(
                    Session(
                        session_id="controller-session",
                        conversation_id="controller",
                        user_email="owner@example.com",
                        agent_id="agent-owner",
                        status="completed",
                        activity_scope_id="controller-scope",
                    )
                )
                await db.flush()
                for state in ("queued", "waiting"):
                    db.add(
                        ManagedConversationLink(
                            link_id=f"managed-{state}",
                            user_email="owner@example.com",
                            controller_agent_id="agent-owner",
                            controller_conversation_id="controller",
                            controller_session_id="controller-session",
                            target_agent_id="agent-owner",
                            target_conversation_id=f"target-{state}",
                            conversation_state="open",
                            turn_state=state,
                        )
                    )
                db.add(
                    Task(
                        task_id="attached-task",
                        title="Attached task",
                        created_by="owner@example.com",
                        agent_id="agent-owner",
                        status="running",
                        source_type="chat",
                        source_ref="task-owner",
                        source_session_id="task-source-session",
                    )
                )
                await db.commit()

        client.portal.call(seed)
        token = client.app.state.auth_provider.sign_access_token(
            "owner@example.com", "Owner", "admin"
        )
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get("/api/v1/dashboard/navigation-summary", headers=headers)
        assert response.status_code == 200, response.text
        groups = response.json()["chat_groups"]
        assert sum(group["count"] for group in groups if group["is_active"]) == 2
        assert sum(group["count"] for group in groups if not group["is_active"]) == 1
        assert all(group["has_unread"] for group in groups)
        sidebar = client.get("/api/v1/conversations/sidebar", headers=headers)
        assert sidebar.status_code == 200, sidebar.text
        background = sidebar.json()["background_work"]["items"]
        assert any(
            item["kind"] == "task" and item["controller_conversation_id"] == "task-owner"
            for item in background
        )
        assert any(
            item["kind"] == "managed_conversation" and item["status"] == "queued"
            for item in background
        )
