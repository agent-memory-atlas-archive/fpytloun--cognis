from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import schema as sa_schema
from sqlalchemy.ext.asyncio import create_async_engine

from cognis import json_codec as json
from cognis.bootstrap import run_schema_bootstrap
from cognis.core.executor_management import ExecutorManagementDependencies
from cognis.core.management_access import ManagementActor
from cognis.core.settings_management import SettingsManagement
from cognis.core.step_profile_management import StepProfileManagement
from cognis.core.step_profiles import StepProfileRegistry
from cognis.core.system_management import (
    SystemManagementDependencies,
    _safe_configuration,
    handle_system_management_tool,
)
from cognis.core.system_skills import get_system_skill_default
from cognis.models.config import ModelInfo
from cognis.ownership import SYSTEM_USER_EMAIL
from cognis.runtime_context import RuntimeAccessContext
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import Base
from cognis.store.queries import create_llm_provider, create_user, upsert_setting
from cognis.tools.builtin.system_management import system_management_tools
from cognis.tools.introspection import audit_tool_descriptors

EMAIL = "admin@example.com"
ACCESS = RuntimeAccessContext(user_email=EMAIL, agent_id="primary", agent_owner_email=EMAIL)


@pytest.fixture
async def deps(tmp_path: Path):
    postgres_url = os.environ.get("COGNIS_MANAGEMENT_TEST_POSTGRES_URL")
    admin = None
    schema_name = None
    if postgres_url:
        schema_name = f"management_{uuid.uuid4().hex}"
        admin = create_async_engine(postgres_url)
        async with admin.begin() as connection:
            await connection.execute(sa_schema.CreateSchema(schema_name))
        engine = create_async_engine(
            postgres_url, connect_args={"server_settings": {"search_path": schema_name}}
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    else:
        engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/management.db")
        await run_schema_bootstrap(engine)
    factory = create_session_factory(engine)
    async with factory() as session:
        if postgres_url:
            await create_user(
                session, email=SYSTEM_USER_EMAIL, name="System", role="admin", password_hash="hash"
            )
        await create_user(session, email=EMAIL, name="Admin", role="admin", password_hash="hash")
        await create_user(session, email="other@example.com", name="Other", password_hash="hash")
        for provider_id, owner in (
            ("global-provider", SYSTEM_USER_EMAIL),
            ("private-provider", "other@example.com"),
        ):
            await create_llm_provider(
                session,
                provider_id=provider_id,
                display_name=provider_id,
                location="controller",
                backend="litellm",
                owner_email=owner,
                config={"api_key": "sensitive-test-value"},
            )
        await upsert_setting(
            session,
            key="web.search_backend",
            value="direct",
            category="web",
        )
        await upsert_setting(
            session, key="session.compaction_threshold", value=0.75, category="session"
        )
        await session.commit()
    llm = SimpleNamespace(
        invalidate_runtime_capability_cache_for_provider=Mock(),
        inference_plan=AsyncMock(),
        resolve_model_reference=AsyncMock(return_value=("chat-model", "global-provider")),
        get_model_info=AsyncMock(
            return_value=ModelInfo(model_id="chat-model", display_name="Chat model")
        ),
        test_provider=AsyncMock(return_value={"ok": True}),
        discover_models=AsyncMock(return_value=["chat-model"]),
    )
    executor_deps = ExecutorManagementDependencies(
        session_factory=factory,
        websocket=None,
        fence=AsyncMock(),
        reconfigure=Mock(),
        trigger_reconcile=Mock(),
        sign_token=Mock(),
    )
    yield SystemManagementDependencies(
        session_factory=factory,
        llm=llm,
        settings=SettingsManagement(factory, asyncio.Lock(), AsyncMock()),
        executors=executor_deps,
        provider_monitor=SimpleNamespace(
            get=AsyncMock(return_value={"healthy": True}),
            invalidate=AsyncMock(),
        ),
        provider_test_cooldowns={},
        provider_test_results={},
        step_profiles=StepProfileManagement(factory, StepProfileRegistry(factory)),
    )
    await engine.dispose()
    if admin is not None:
        async with admin.begin() as connection:
            await connection.execute(sa_schema.DropSchema(schema_name, cascade=True))
        await admin.dispose()


async def call(deps, name, action, **kwargs):
    return await handle_system_management_tool(
        name=name,
        arguments={"action": action, **kwargs},
        deps=deps,
        access=ACCESS,
    )


def test_native_contracts_and_corresponding_system_skills():
    definitions = system_management_tools()
    assert not audit_tool_descriptors(definitions)
    assert len(definitions) == 4
    for definition in definitions:
        assert definition.non_bypassable
    for domain in ("provider", "route", "settings", "executor"):
        assert get_system_skill_default(f"cognis-{domain}-manager") is not None


@pytest.mark.parametrize(
    "access",
    [
        None,
        replace(ACCESS, task_id="task-owned"),
        replace(ACCESS, parent_session_id="parent"),
        replace(ACCESS, agent_owner_email="other@example.com"),
        replace(ACCESS, agent_type="delegate"),
    ],
)
async def test_context_denial_precedes_dispatch(deps, access):
    result = await handle_system_management_tool(
        name="manage_providers",
        arguments={"action": "delete"},
        deps=deps,
        access=access,
    )
    assert result.is_error
    assert result.metadata["code"] == "system_management_context_denied"


async def test_provider_read_redaction_and_private_resource_isolation(deps):
    result = await call(deps, "manage_providers", "list")
    assert not result.is_error
    assert "sensitive-test-value" not in result.output
    assert "private-provider" not in result.output
    denied = await call(deps, "manage_providers", "get", provider_id="private-provider")
    assert denied.is_error
    assert denied.metadata["status_code"] == 404


async def test_provider_preview_update_and_stale_write(deps):
    current = json.loads(
        (await call(deps, "manage_providers", "get", provider_id="global-provider")).output
    )
    args = dict(
        provider_id="global-provider",
        expected_updated_at=current["updated_at"],
        payload={"display_name": "Updated"},
    )
    preview = await call(deps, "manage_providers", "update", preview=True, **args)
    assert not preview.is_error
    assert (
        json.loads(
            (await call(deps, "manage_providers", "get", provider_id="global-provider")).output
        )["display_name"]
        == "global-provider"
    )
    updated = await call(deps, "manage_providers", "update", **args)
    assert not updated.is_error
    stale = await call(deps, "manage_providers", "update", **args)
    assert stale.is_error
    assert stale.metadata["status_code"] == 409
    deps.llm.invalidate_runtime_capability_cache_for_provider.assert_called_once()


async def test_concurrent_provider_updates_have_one_winner(deps):
    current = json.loads(
        (await call(deps, "manage_providers", "get", provider_id="global-provider")).output
    )

    async def update(name):
        return await call(
            deps,
            "manage_providers",
            "update",
            provider_id="global-provider",
            expected_updated_at=current["updated_at"],
            payload={"display_name": name},
        )

    results = await asyncio.gather(update("First"), update("Second"))
    assert sum(not result.is_error for result in results) == 1
    assert next(result for result in results if result.is_error).metadata["status_code"] == 409


async def test_provider_create_rejects_literals_without_echoing_them(deps):
    result = await call(
        deps,
        "manage_providers",
        "create",
        payload={
            "provider_id": "new-provider",
            "display_name": "New",
            "config": {"api_key": "do-not-echo-this"},
        },
    )
    assert result.is_error
    assert "do-not-echo-this" not in result.output


async def test_provider_probe_does_not_save_discovery_and_test_has_cooldown(deps):
    discovered = await call(
        deps, "manage_providers", "discover_models", provider_id="global-provider"
    )
    assert not discovered.is_error
    first = await call(deps, "manage_providers", "test", provider_id="global-provider")
    assert not first.is_error
    second = await call(deps, "manage_providers", "test", provider_id="global-provider")
    assert second.is_error
    assert second.metadata["status_code"] == 429
    deps.llm.test_provider.assert_awaited_once()


async def test_named_custom_route_create_update_revision_and_delete(deps):
    config = {
        "name": "fast-chat",
        "targets": [{"provider_id": "global-provider", "model": "chat-model"}],
    }
    preview = await call(deps, "manage_routes", "named_create", config=config, preview=True)
    assert not preview.is_error
    assert json.loads((await call(deps, "manage_routes", "named_list")).output)["routes"] == []
    created = await call(deps, "manage_routes", "named_create", config=config)
    assert not created.is_error
    route = json.loads(created.output)
    assert route["reference"] == "cognis/fast-chat"
    updated = await call(
        deps,
        "manage_routes",
        "named_update",
        route_id=route["route_id"],
        expected_revision=route["revision"],
        config=config,
    )
    assert not updated.is_error
    stale = await call(
        deps,
        "manage_routes",
        "named_delete",
        route_id=route["route_id"],
        expected_revision=route["revision"],
    )
    assert stale.is_error
    deleted = await call(
        deps,
        "manage_routes",
        "named_delete",
        route_id=route["route_id"],
        expected_revision=json.loads(updated.output)["revision"],
    )
    assert not deleted.is_error


async def test_binding_patch_preserves_omitted_bindings_and_conflicts(deps):
    original = json.loads((await call(deps, "manage_routes", "bindings_get")).output)
    updated = await call(
        deps,
        "manage_routes",
        "bindings_update",
        expected_revision=original["revision"],
        bindings={"compaction": {"model": "__same_session_model__"}},
    )
    assert not updated.is_error
    current = json.loads(updated.output)
    assert current["bindings"]["compaction"]["model"] == "__same_session_model__"
    stale = await call(
        deps,
        "manage_routes",
        "bindings_reset",
        task_types=["compaction"],
        expected_revision=original["revision"],
    )
    assert stale.is_error
    reset = await call(
        deps,
        "manage_routes",
        "bindings_reset",
        task_types=["compaction"],
        expected_revision=current["revision"],
    )
    assert not reset.is_error
    assert json.loads(reset.output)["bindings"]["compaction"]["model"] is None


async def test_setting_preview_apply_and_stale_write(deps):
    current = json.loads(
        (await call(deps, "manage_settings", "get", key="web.search_backend")).output
    )
    args = dict(key=current["key"], expected_updated_at=current["updated_at"], value="direct")
    preview = await call(deps, "manage_settings", "update", preview=True, **args)
    assert not preview.is_error
    deps.settings.apply.assert_not_awaited()
    updated = await call(deps, "manage_settings", "update", **args)
    assert not updated.is_error
    stale = await call(deps, "manage_settings", "update", **args)
    assert stale.is_error


async def test_settings_hot_apply_failure_restores_durable_state(deps):
    deps.settings.apply.side_effect = [RuntimeError("failed"), None]
    async with deps.session_factory() as session:
        from cognis.store.queries import get_setting

        row = await get_setting(session, "session.compaction_threshold")
    with pytest.raises(HTTPException) as caught:
        await deps.settings.put(
            key="session.compaction_threshold",
            value=0.8,
            updated_by=EMAIL,
            expected_updated_at=row.updated_at.isoformat(),
        )
    assert caught.value.status_code == 500
    current = json.loads(
        (await call(deps, "manage_settings", "get", key="session.compaction_threshold")).output
    )
    assert current["value"] == 0.75


async def test_executor_create_preview_update_and_delete(deps):
    payload = {"executor_id": "remote-test", "name": "Remote", "executor_type": "websocket"}
    preview = await call(deps, "manage_executors", "create", payload=payload, preview=True)
    assert not preview.is_error
    assert json.loads((await call(deps, "manage_executors", "list")).output) == []
    created = await call(deps, "manage_executors", "create", payload=payload)
    assert not created.is_error
    current = json.loads(
        (await call(deps, "manage_executors", "get", executor_id="remote-test")).output
    )
    updated = await call(
        deps,
        "manage_executors",
        "update",
        executor_id="remote-test",
        expected_updated_at=current["updated_at"],
        payload={"name": "Renamed"},
    )
    assert not updated.is_error
    stale = await call(
        deps,
        "manage_executors",
        "delete",
        executor_id="remote-test",
        expected_updated_at=current["updated_at"],
    )
    assert stale.is_error
    latest = json.loads(
        (await call(deps, "manage_executors", "get", executor_id="remote-test")).output
    )
    deleted = await call(
        deps,
        "manage_executors",
        "delete",
        executor_id="remote-test",
        expected_updated_at=latest["updated_at"],
    )
    assert not deleted.is_error
    deps.executors.fence.assert_awaited_once_with("remote-test")


@pytest.mark.parametrize(
    "value",
    [
        {"api_key": "literal"},
        {"env": {"API_TOKEN": "literal"}},
        {"base_url": "https://user:pass@provider.test"},
        {"base_url": "https://provider.test?key=literal"},
    ],
)
def test_secret_configuration_rejected(value):
    with pytest.raises(ValueError):
        _safe_configuration(value, writing=True)


def test_admin_cannot_manage_another_users_private_resources():
    with pytest.raises(HTTPException) as caught:
        ManagementActor(EMAIL, "admin").require_owner("other@example.com")
    assert caught.value.status_code == 404


async def test_web_update_validates_readiness_and_propagates_after_commit(deps):
    finalize = AsyncMock()
    object.__setattr__(deps.settings, "finalize_web", finalize)
    current = json.loads(
        (await call(deps, "manage_settings", "get", key="web.search_backend")).output
    )
    denied = await call(
        deps,
        "manage_settings",
        "web_update",
        key="web.search_backend",
        value="tavily",
        expected_updated_at=current["updated_at"],
    )
    assert denied.is_error and denied.metadata["status_code"] == 400
    finalize.assert_not_awaited()
    updated = await call(
        deps,
        "manage_settings",
        "web_update",
        key="web.search_backend",
        value="direct",
        expected_updated_at=current["updated_at"],
    )
    assert not updated.is_error
    finalize.assert_awaited_once()


async def test_web_update_finishes_propagation_before_cancellation(deps):
    committed = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def finalize():
        committed.set()
        await release.wait()
        finished.set()

    object.__setattr__(deps.settings, "finalize_web", finalize)
    current = json.loads(
        (await call(deps, "manage_settings", "get", key="web.search_backend")).output
    )
    task = asyncio.create_task(
        call(
            deps,
            "manage_settings",
            "web_update",
            key="web.search_backend",
            value="direct",
            expected_updated_at=current["updated_at"],
        )
    )
    await asyncio.wait_for(committed.wait(), 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()


async def test_profile_snapshot_ignores_stale_local_registry_and_protects_revision(deps):
    original = json.loads((await call(deps, "manage_settings", "step_profiles_list")).output)
    created = await call(
        deps,
        "manage_settings",
        "step_profiles_create",
        payload={"profile_id": "custom-review", "name": "Review", "mode": "soft", "config": {}},
        expected_revision=original["revision"],
    )
    assert not created.is_error
    # An unrelated controller worker has a separate stale process-local cache.
    other = replace(
        deps,
        step_profiles=StepProfileManagement(
            deps.session_factory,
            StepProfileRegistry(deps.session_factory),
        ),
    )
    snapshot = json.loads(
        (
            await call(other, "manage_settings", "step_profiles_get", profile_id="custom-review")
        ).output
    )
    assert snapshot["profile"]["name"] == "Review"
    assert snapshot["revision"] != original["revision"]
    stale = await call(
        other,
        "manage_settings",
        "step_profiles_update",
        profile_id="custom-review",
        payload={"name": "Stale", "mode": "soft", "config": {}},
        expected_revision=original["revision"],
    )
    assert stale.is_error and stale.metadata["status_code"] == 409
    reset = await call(
        other,
        "manage_settings",
        "step_profiles_reset",
        profile_id="custom-review",
        expected_revision=snapshot["revision"],
    )
    assert not reset.is_error
    newest = json.loads((await call(other, "manage_settings", "step_profiles_list")).output)
    assert newest["revision"] != original["revision"]  # no absent -> present -> absent ABA


async def test_profile_invalid_mode_is_validation_error(deps):
    from cognis.api.models import StepProfileCreateRequest

    with pytest.raises(HTTPException) as caught:
        await deps.step_profiles.mutate(
            ManagementActor(EMAIL, "admin"),
            "create",
            "invalid-mode",
            StepProfileCreateRequest(profile_id="invalid-mode", mode="not-a-mode", config={}),
        )
    assert caught.value.status_code == 400
