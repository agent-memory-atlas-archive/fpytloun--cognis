"""Outcome-only policy updates must reach existing Intaris sessions."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from cognis.core import session as session_module
from cognis.core.session import SessionManager
from cognis.models.session import ConversationContext
from cognis.providers.guardrails.intaris import IntarisProvider
from cognis.store.models import Agent
from tests.unit.test_session_manager import _Cache, _Providers, _session_factory


@pytest.mark.asyncio
@pytest.mark.parametrize("maximum", ["escalate", None])
@pytest.mark.parametrize("yolo", [False, True])
async def test_refresh_outcome_only_policy_and_explicit_removal(
    tmp_path, monkeypatch, maximum, yolo
):
    engine, factory = await _session_factory(tmp_path, capabilities={"maximum_outcome": "escalate"})
    providers = _Providers()
    manager = SessionManager(factory, providers, _Cache())
    try:
        conversation, root = await manager.create_conversation_with_root_session(
            user_email="user@example.com",
            agent_id="agent-1",
            context=ConversationContext(type="web"),
            title="Inspect the parser",
        )
        async with factory() as db:
            row = await db.get(Agent, "agent-1")
            row.capabilities = {"maximum_outcome": maximum}
            await db.commit()
        if yolo:
            # Exercise the canonical conversation override path, not a fake
            # policy maximum supplied by the calling agent.
            from cognis.store import queries

            async with factory() as db:
                stored = await queries.get_conversation(db, conversation.conversation_id)
                stored.context_data = {
                    **(stored.context_data or {}),
                    "maximum_outcome_override": "approve",
                }
                await db.commit()
        monkeypatch.setattr(session_module, "_resolve_runtime_workdir", lambda: None)
        monkeypatch.setattr(session_module, "_project_source_paths", AsyncMock(return_value=[]))
        monkeypatch.setattr(session_module, "_resolve_executor_home", lambda: None)
        build_policy = session_module._intaris_session_policy

        def outcome_only_policy(*args, **kwargs):
            policy = build_policy(*args, **kwargs)
            # Exercise the refresh boundary independently of today's automatic
            # temporary-directory grants.
            policy.pop("allow_paths", None)
            return policy

        monkeypatch.setattr(session_module, "_intaris_session_policy", outcome_only_policy)
        before = len(providers.guardrails.policy_updates)
        result = await manager.refresh_intaris_session_policy(root)
        assert len(providers.guardrails.policy_updates) == before + 1
        assert result["maximum_outcome"] == ("approve" if yolo else maximum)
        assert result["evaluation_policy_version"] == "hybrid_v1"
        assert not result.get("allow_paths")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("maximum", [None, "escalate"])
@pytest.mark.parametrize("drop_clear", [False, True])
async def test_yolo_off_restores_canonical_ceiling_with_real_provider_ack(
    tmp_path, maximum, drop_clear
):
    engine, factory = await _session_factory(tmp_path, capabilities={"maximum_outcome": maximum})
    providers = _Providers()
    manager = SessionManager(factory, providers, _Cache())
    conversation, root = await manager.create_conversation_with_root_session(
        user_email="user@example.com",
        agent_id="agent-1",
        context=ConversationContext(type="web"),
        title="Ceiling lifecycle",
    )
    remote = {"maximum_outcome": maximum}
    requests = []

    def respond(request):
        requests.append(request)
        assert request.headers["X-Agent-Id"] == "agent-1"
        assert request.headers["X-Agent-Owner"] == "user@example.com"
        if request.method == "PATCH":
            patch = json.loads(request.content)["policy"]
            if not (drop_clear and patch.get("maximum_outcome") is None):
                remote.update(patch)
        return httpx.Response(
            200,
            json={
                "session_id": root.intaris_session_id or root.session_id,
                "user_id": root.user_email,
                "agent_id": root.agent_id,
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "policy": dict(remote),
            },
        )

    provider = IntarisProvider(
        "http://intaris.test",
        SimpleNamespace(sign_service_jwt=lambda *args, **kwargs: "test-signature"),
    )
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="http://intaris.test", transport=httpx.MockTransport(respond)
    )
    providers.guardrails = provider
    try:
        await manager.set_conversation_yolo(conversation, root, enabled=True)
        assert remote["maximum_outcome"] == "approve"
        if maximum is None and drop_clear:
            with pytest.raises(ValueError, match="did not acknowledge"):
                await manager.set_conversation_yolo(conversation, root, enabled=False)
            assert remote["maximum_outcome"] == "approve"
            assert conversation.context.platform_data["maximum_outcome_override"] == "approve"
        else:
            await manager.set_conversation_yolo(conversation, root, enabled=False)
            assert remote["maximum_outcome"] == maximum
            assert "maximum_outcome_override" not in conversation.context.platform_data
        patches = [json.loads(r.content)["policy"] for r in requests if r.method == "PATCH"]
        assert patches[-1]["maximum_outcome"] == maximum
    finally:
        await provider.client.aclose()
        await engine.dispose()
