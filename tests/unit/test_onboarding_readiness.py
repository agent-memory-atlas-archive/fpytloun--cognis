from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cognis.core import onboarding
from cognis.models.config import ModelInfo
from cognis.ownership import SYSTEM_USER_EMAIL
from cognis.providers.llm.routing import EMBEDDING_ROUTES


@pytest.fixture
def configured(monkeypatch):
    executor = SimpleNamespace(
        runtime_state="active",
        applied_config_version=2,
        desired_config_version=2,
        observed_tools=["list_directory"],
    )
    agent = SimpleNamespace(
        status="active",
        agent_type="primary",
        execution={"executor_id": "connected-workstation"},
        llm_config={"model": "openai/gpt-oss-120b", "provider_id": "starter"},
    )
    monkeypatch.setattr(onboarding, "load_executor_policy", AsyncMock(return_value=None))
    monkeypatch.setattr(onboarding, "list_executors", AsyncMock(return_value=[executor]))
    monkeypatch.setattr(
        onboarding, "list_agent_readiness_snapshots", AsyncMock(return_value=[agent])
    )
    state = AsyncMock(return_value={})
    monkeypatch.setattr(onboarding, "get_user_ui_state_value", state)
    monkeypatch.setattr(onboarding, "is_executor_row_usable", lambda *a, **kw: True)
    monkeypatch.setattr(onboarding, "select_executor_for_agent", lambda *a, **kw: executor)
    unavailable = set()
    incorrect = {}
    calls = []

    async def resolve(model, *, task_type, explicit_provider_id, acting_user_email):
        calls.append((task_type, acting_user_email))
        if task_type in unavailable:
            raise ValueError("No active model available")
        return task_type, "starter"

    async def info(model, **kwargs):
        if model in incorrect:
            return incorrect[model]
        return ModelInfo(
            model_id=model,
            supports_embedding=model in EMBEDDING_ROUTES,
            supports_image_generation=model == "image_generation",
            model_mode="systemone" if model == "intaris_evaluation" else None,
        )

    llm = SimpleNamespace(resolve_model_target=resolve, get_model_info=info)

    @asynccontextmanager
    async def sessions():
        yield None

    return SimpleNamespace(
        executor=executor,
        agent=agent,
        llm=llm,
        sessions=sessions,
        state=state,
        unavailable=unavailable,
        incorrect=incorrect,
        calls=calls,
    )


async def test_readiness_uses_companion_scope_and_accepts_jev_only_for_evaluation(configured):
    ready = await onboarding.configuration_readiness(
        configured.sessions, configured.llm, "owner@localhost"
    )
    assert ready["companion_routes_configured"]
    assert ready["executor_tools_configured"]
    assert ready["agent_ready"]
    assert ("mnemory_extraction", SYSTEM_USER_EMAIL) in configured.calls
    assert ("default", "owner@localhost") in configured.calls
    configured.incorrect["intaris_judge"] = ModelInfo(
        model_id="typesafe/jev-1.13", model_mode="systemone"
    )
    ready = await onboarding.configuration_readiness(
        configured.sessions, configured.llm, "owner@localhost"
    )
    assert not ready["companion_routes_configured"]


@pytest.mark.parametrize("broken", ["stale_config", "no_tools", "disconnected", "draft_agent"])
async def test_records_alone_never_make_agent_ready(configured, broken):
    if broken == "stale_config":
        configured.executor.applied_config_version = 1
    elif broken == "no_tools":
        configured.executor.observed_tools = []
    elif broken == "disconnected":
        configured.executor.runtime_state = "disconnected"
    else:
        configured.agent.status = "draft"
    ready = await onboarding.configuration_readiness(
        configured.sessions, configured.llm, "owner@localhost"
    )
    assert not ready["agent_ready"]


async def test_optional_images_do_not_block_and_dismissal_survives_degradation(configured):
    configured.state.return_value = {"status": "dismissed"}
    configured.unavailable.add("image_generation")
    ready = await onboarding.configuration_readiness(
        configured.sessions, configured.llm, "owner@localhost"
    )
    assert ready["agent_ready"]
    assert ready["companion_routes_configured"]
    assert not ready["image_generation_configured"]
    configured.unavailable.add("default")
    configured.unavailable.add("mnemory_embedding")
    ready = await onboarding.configuration_readiness(
        configured.sessions, configured.llm, "owner@localhost"
    )
    assert not ready["agent_ready"]
    assert not ready["companion_routes_configured"]
    assert not ready["onboarding_pending"]


async def test_chat_model_does_not_satisfy_embedding_route(configured):
    configured.incorrect["mnemory_embedding"] = ModelInfo(model_id="openai/gpt-oss-20b")
    ready = await onboarding.configuration_readiness(
        configured.sessions, configured.llm, "owner@localhost"
    )
    assert not ready["companion_routes_configured"]


async def test_readiness_reuses_only_the_current_owners_request_snapshot(configured, monkeypatch):
    snapshots = AsyncMock(side_effect=AssertionError("duplicate agent read"))
    monkeypatch.setattr(onboarding, "list_agent_readiness_snapshots", snapshots)
    configured.agent.owner_email = "owner@localhost"
    ready = await onboarding.configuration_readiness(
        configured.sessions, configured.llm, "owner@localhost", agents=[configured.agent]
    )
    assert ready["agent_ready"]
    snapshots.assert_not_awaited()
    with pytest.raises(ValueError, match="owner"):
        await onboarding.configuration_readiness(
            configured.sessions, configured.llm, "other@localhost", agents=[configured.agent]
        )
