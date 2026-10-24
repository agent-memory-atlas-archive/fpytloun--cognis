from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update

from cognis.core.retry_provider_options import (
    resolve_retry_provider_context,
    retry_provider_options,
)
from cognis.store.database import create_session_factory
from cognis.store.direct_turns import DirectTurnStore
from cognis.store.models import DirectTurnRequestRow
from tests.unit.test_direct_turn_store import _admit, _harness, _lease


@pytest.mark.asyncio
async def test_options_use_visible_exact_models_and_shared_rate_limit_waits(tmp_path: Path) -> None:
    harness = await _harness(tmp_path)
    try:
        request = (await _admit(harness, key="blocked", content="run")).request
        lease = await _lease(harness)
        assert await harness.store.claim(
            request.request_id, lease=lease, controller_id="controller-a", incarnation_id="boot-a"
        )
        assert await harness.store.settle_transient_failure(
            request.request_id,
            lease=lease,
            outcome={
                "retry_target": {
                    "scope": "provider_model",
                    "reason_class": "rate_limit",
                    "provider_id": "blocked",
                    "model": "gpt-5",
                }
            },
            retry_after_seconds=600,
        )
        llm = SimpleNamespace(
            list_model_references=AsyncMock(
                return_value=[
                    {"provider_id": provider, "model_id": model, "provider_display_name": name}
                    for provider, model, name in [
                        ("current", "gpt-5", "Current"),
                        ("blocked", "gpt-5", "Blocked"),
                        ("other-model", "gpt-5-mini", "Other"),
                        ("available", "gpt-5", "Available"),
                        ("available", "gpt-5", "Available"),
                        ("quota", "gpt-5", "Quota"),
                        ("stale", "gpt-5", "Stale"),
                    ]
                ]
            )
        )
        monitor = SimpleNamespace(
            list_visible=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        provider_id=provider,
                        stale=stale,
                        usage=SimpleNamespace(ok=True, allowed=False, limit_reached=True),
                    )
                    for provider, stale in [("quota", False), ("stale", True)]
                ]
            )
        )
        kwargs = dict(
            session_factory=create_session_factory(harness.engine),
            llm=llm,
            monitor=monitor,
            user_email="user@example.com",
            active_turn={
                "status": "waiting",
                "retry_reason": "rate_limit",
                "provider_id": "current",
                "model": "gpt-5",
            },
        )
        options = await retry_provider_options(**kwargs)
        assert [option["provider_id"] for option in options] == ["available", "stale"]
        assert options[0] == {
            "provider_id": "available",
            "display_name": "Available",
            "model": "gpt-5",
        }
        llm.list_model_references.assert_awaited_once_with(acting_user_email="user@example.com")
        # An expired retry deadline is no longer an active cooldown.
        async with create_session_factory(harness.engine)() as db:
            await db.execute(
                update(DirectTurnRequestRow)
                .where(DirectTurnRequestRow.request_id == request.request_id)
                .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await db.commit()
        options = await retry_provider_options(**kwargs)
        assert [option["provider_id"] for option in options] == ["available", "blocked", "stale"]
    finally:
        await harness.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "turn",
    [
        None,
        {"status": "running", "retry_reason": "rate_limit", "model": "gpt-5", "provider_id": "p"},
        {"status": "waiting", "retry_reason": "rate_limit", "model": "gpt-5"},
    ],
)
async def test_non_rate_limit_wait_has_no_options_or_io(turn) -> None:
    llm = SimpleNamespace(list_model_references=AsyncMock())
    assert (
        await retry_provider_options(
            session_factory=None,
            llm=llm,
            monitor=None,
            user_email="user@example.com",
            active_turn=turn,
        )
        == []
    )
    llm.list_model_references.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_context_uses_saved_model_failure_and_rejects_mismatches(monkeypatch) -> None:
    row = SimpleNamespace(
        request_id="request-a", turn_id="turn-a", status="failed", fencing_token=3
    )
    read = AsyncMock(return_value=row)
    monkeypatch.setattr(DirectTurnStore, "get_conversation_runtime_authority_row", read)
    load = AsyncMock(
        return_value=[
            {
                "notice_kind": "model_error",
                "turn_id": "turn-a",
                "provider_id": "anthropic",
                "model": "claude-sonnet-4",
            }
        ]
    )
    kwargs = dict(
        session_factory=None,
        conversation_id="conv-a",
        turn_id="turn-a",
        provider_id="anthropic",
        model="claude-sonnet-4",
        load_failures=load,
    )
    assert (await resolve_retry_provider_context(**kwargs))["model"] == "claude-sonnet-4"
    assert await resolve_retry_provider_context(**{**kwargs, "model": "other-model"}) is None
    load.return_value = []
    assert await resolve_retry_provider_context(**kwargs) is None
    load.return_value = [
        {
            "notice_kind": "model_error",
            "turn_id": "turn-a",
            "provider_id": "anthropic",
            "model": "claude-sonnet-4",
        }
    ]
    read.side_effect = [
        row,
        SimpleNamespace(
            request_id="request-a", turn_id="turn-a", status="running", fencing_token=4
        ),
    ]
    assert await resolve_retry_provider_context(**kwargs) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "completed", "cancelled"])
async def test_same_turn_is_not_actionable_after_retry_resumes(monkeypatch, status) -> None:
    monkeypatch.setattr(
        DirectTurnStore,
        "get_conversation_runtime_authority_row",
        AsyncMock(return_value=SimpleNamespace(turn_id="turn-a", status=status)),
    )
    load = AsyncMock()
    assert (
        await resolve_retry_provider_context(
            session_factory=None,
            conversation_id="conv-a",
            turn_id="turn-a",
            provider_id="anthropic",
            model="claude-sonnet-4",
            load_failures=load,
        )
        is None
    )
    load.assert_not_awaited()
