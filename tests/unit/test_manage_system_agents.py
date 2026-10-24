"""manage_agents coverage for shipped system agents and user-owned secondary agents."""

from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio

from cognis.core import system_agent_overrides
from cognis.core.agent_management import AgentManagementDependencies
from cognis.core.agent_registry import SYSTEM_AGENTS, AgentRegistry
from cognis.core.system_agent_overrides import SystemAgentOverrideError
from cognis.models.tool import ToolDefinition
from cognis.ownership import SYSTEM_USER_EMAIL
from cognis.runtime_context import RuntimeAccessContext
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import Base
from cognis.store.queries import (
    create_agent,
    create_user,
    get_agent,
    get_system_agent_override,
    upsert_system_agent_override,
)
from cognis.tools.builtin.agent_management import MANAGE_AGENTS_TOOL, handle_agent_management_tool
from cognis.tools.introspection import validate_available_tool_call_with_context
from cognis.tools.native_validation import NativeValidationContext

OWNER = "owner@example.com"
OTHER = "other@example.com"


def _assignable() -> list[ToolDefinition]:
    from cognis.api.runtime_support import static_tool_definitions

    wanted = {"read", "grep", "web_fetch", "manage_agents"}
    tools = [
        tool for tool in static_tool_definitions(knowledgebase_enabled=True) if tool.name in wanted
    ]
    assert {tool.name for tool in tools} == wanted
    return tools


ASSIGNABLE = _assignable()


@pytest_asyncio.fixture
async def deps(tmp_path: Any) -> Any:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/system-agents.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        for email in (OWNER, OTHER, SYSTEM_USER_EMAIL):
            await create_user(session, email=email, name=email, password_hash="x", role="user")
        await create_agent(
            session, agent_id="manager", name="Manager", owner_email=OWNER, status="active"
        )
        await create_agent(
            session, agent_id="lead", name="Lead", owner_email=OWNER, status="active"
        )
        await create_agent(
            session,
            agent_id="helper",
            name="Helper",
            owner_email=OWNER,
            status="active",
            agent_type="secondary",
        )
        await session.commit()
    try:
        yield AgentManagementDependencies(session_factory=factory, assignable_tools=ASSIGNABLE)
    finally:
        await engine.dispose()


async def call(
    deps: AgentManagementDependencies, arguments: dict[str, Any], *, actor: str = OWNER
) -> tuple[bool, Any]:
    result = await handle_agent_management_tool(
        tool_name="manage_agents",
        deps=deps,
        user_email=actor,
        current_agent_id="manager",
        runtime_access=RuntimeAccessContext(
            user_email=actor,
            agent_id="manager",
            agent_owner_email=actor,
            agent_type="primary",
        ),
        arguments=arguments,
    )
    if result.is_error:
        return False, result.output
    return True, json.loads(result.output)


async def effective(deps: AgentManagementDependencies, agent_id: str, owner: str = OWNER) -> Any:
    return await AgentRegistry(deps.session_factory).get(
        agent_id, owner_email=owner, include_disabled=True
    )


@pytest.mark.asyncio
async def test_list_and_get_expose_overridable_system_agents(deps: Any) -> None:
    ok, payload = await call(deps, {"action": "list"})
    assert ok, payload
    assert {item["agent_id"] for item in payload["agents"]} == {"manager", "lead", "helper"}
    system_ids = {item["agent_id"] for item in payload["system_agents"]}
    assert "system:explore" in system_ids
    assert not any(SYSTEM_AGENTS[agent_id].hidden for agent_id in system_ids)
    explore = next(i for i in payload["system_agents"] if i["agent_id"] == "system:explore")
    assert explore["management_mode"] == "overrides"
    assert explore["has_overrides"] is False

    ok, payload = await call(deps, {"action": "get", "agent_id": "system:explore"})
    assert ok, payload
    system_agent = payload["system_agent"]
    assert system_agent["override"] is None
    assert system_agent["override_updated_at"] == ""
    assert system_agent["shipped"]["tools"] == SYSTEM_AGENTS["system:explore"].tools
    assert system_agent["effective"]["agent_id"] == "system:explore"


@pytest.mark.asyncio
async def test_override_update_patch_semantics_and_revision(deps: Any) -> None:
    ok, payload = await call(
        deps,
        {
            "action": "system_overrides_update",
            "agent_id": "system:explore",
            "expected_updated_at": "",
            "overrides": {
                "llm_config": {"reasoning_effort": "high"},
                "tools": {"builtin_tools": ["read", "grep", "web_fetch"]},
            },
        },
    )
    assert ok, payload
    revision = payload["system_agent"]["override_updated_at"]
    assert revision
    agent = await effective(deps, "system:explore")
    assert agent.llm_config.reasoning_effort == "high"
    assert agent.tools == {"builtin_tools": ["read", "grep", "web_fetch"]}
    # Overrides are per user.
    other = await effective(deps, "system:explore", owner=OTHER)
    assert other.llm_config.reasoning_effort == "low"

    # Stale revision ("no override") is rejected without mutation.
    ok, error = await call(
        deps,
        {
            "action": "system_overrides_update",
            "agent_id": "system:explore",
            "expected_updated_at": "",
            "overrides": {"llm_config": None},
        },
    )
    assert not ok and "conflict" in error

    # Omitted fields keep their override; null restores the shipped value.
    ok, payload = await call(
        deps,
        {
            "action": "system_overrides_update",
            "agent_id": "system:explore",
            "expected_updated_at": revision,
            "overrides": {"llm_config": None},
        },
    )
    assert ok, payload
    agent = await effective(deps, "system:explore")
    assert agent.llm_config.reasoning_effort == "low"
    assert agent.tools == {"builtin_tools": ["read", "grep", "web_fetch"]}


@pytest.mark.asyncio
async def test_override_rejects_privilege_expansion(deps: Any) -> None:
    for tools, expected in (
        ({"builtin_tools": ["read", "write"]}, "caller-effective assignable inventory"),
        ({"builtin_tools": ["read", "manage_agents"]}, "cannot be granted"),
        ({"builtin_tools": ["read"], "opt_in_builtin_tools": ["manage_mcp"]}, "Unsupported"),
        ({"builtin_tools": ["read"], "mcp_servers": []}, "Unsupported"),
        # Omitting builtin_tools would enable every default-on builtin.
        ({}, "explicit list"),
        ({"allow_tools": ["read"]}, "explicit list"),
    ):
        ok, error = await call(
            deps,
            {
                "action": "system_overrides_update",
                "agent_id": "system:explore",
                "overrides": {"tools": tools},
            },
        )
        assert not ok and expected in error, error
    ok, error = await call(
        deps,
        {
            "action": "system_overrides_update",
            "agent_id": "system:explore",
            "overrides": {"skills": {"items": [{"skill_id": "does-not-exist"}]}},
        },
    )
    assert not ok and "Invalid skill_id" in error
    for skills, expected in (
        ({"items": [{"skill_id": "x", "tool_names": ["write"]}]}, "Unsupported skill assignment"),
        ({"items": [], "_attached_skill_tool_ids": ["builtin:write"]}, "Unsupported"),
    ):
        ok, error = await call(
            deps,
            {
                "action": "system_overrides_update",
                "agent_id": "system:explore",
                "overrides": {"skills": skills},
            },
        )
        assert not ok and expected in error, error
    ok, error = await call(
        deps,
        {
            "action": "system_overrides_update",
            "agent_id": "system:explore",
            "overrides": {"llm_config": {"reasoning_effort": "turbo"}},
        },
    )
    assert not ok and "llm_config" in error
    ok, error = await call(
        deps,
        {
            "action": "system_overrides_update",
            "agent_id": "system:explore",
            "overrides": {"permissions": {"allowed_knowledgebases": ["kb-missing"]}},
        },
    )
    assert not ok and "allowed_knowledgebases" in error
    ok, error = await call(
        deps,
        {
            "action": "system_overrides_update",
            "agent_id": "system:explore",
            "overrides": {"system_prompt": "x"},
        },
    )
    assert not ok and "runtime tuning fields" in error
    async with deps.session_factory() as session:
        assert (
            await get_system_agent_override(session, owner_email=OWNER, agent_id="system:explore")
            is None
        )


@pytest.mark.asyncio
async def test_disable_enable_reset_and_read_only_internal_agents(deps: Any) -> None:
    ok, payload = await call(deps, {"action": "system_disable", "agent_id": "system:research"})
    assert ok and payload["status"] == "disabled", payload
    assert (await effective(deps, "system:research")).disabled is True
    assert (
        await AgentRegistry(deps.session_factory).get("system:research", owner_email=OWNER)
    ) is None

    ok, payload = await call(
        deps,
        {
            "action": "system_overrides_update",
            "agent_id": "system:research",
            "overrides": {"llm_config": {"reasoning_effort": "high"}},
        },
    )
    assert ok, payload
    assert payload["system_agent"]["disabled"] is True  # Update preserves disabled state.

    ok, payload = await call(deps, {"action": "system_enable", "agent_id": "system:research"})
    assert ok and payload["system_agent"]["disabled"] is False
    assert (await effective(deps, "system:research")).llm_config.reasoning_effort == "high"

    ok, payload = await call(
        deps, {"action": "system_overrides_reset", "agent_id": "system:research"}
    )
    assert ok and payload["status"] == "reset"
    assert payload["system_agent"]["override"] is None
    ok, payload = await call(
        deps, {"action": "system_overrides_reset", "agent_id": "system:research"}
    )
    assert ok and payload["status"] == "unchanged"

    for action in ("system_disable", "system_overrides_reset"):
        ok, error = await call(deps, {"action": action, "agent_id": "system:compaction"})
        assert not ok and "read-only" in error
    ok, error = await call(deps, {"action": "system_disable", "agent_id": "helper"})
    assert not ok and "System agent not found" in error


@pytest.mark.asyncio
async def test_owned_agent_actions_redirect_system_agents(deps: Any) -> None:
    ok, error = await call(
        deps, {"action": "update", "agent_id": "system:explore", "description": "x"}
    )
    assert not ok and "system_overrides_update" in error


@pytest.mark.asyncio
async def test_schema_accepts_system_override_operations(deps: Any) -> None:
    context = NativeValidationContext(
        actor_email=OWNER, current_agent_id="manager", agent_management_deps=deps
    )
    valid = await validate_available_tool_call_with_context(
        [MANAGE_AGENTS_TOOL],
        "manage_agents",
        {
            "action": "system_overrides_update",
            "agent_id": "system:explore",
            "overrides": {"llm_config": {"reasoning_effort": "medium"}},
        },
        context=context,
    )
    assert valid["valid"], valid
    invalid = await validate_available_tool_call_with_context(
        [MANAGE_AGENTS_TOOL],
        "manage_agents",
        {
            "action": "system_overrides_update",
            "agent_id": "system:compaction",
            "overrides": {"llm_config": {"reasoning_effort": "medium"}},
        },
        context=context,
    )
    assert not invalid["valid"]


@pytest.mark.asyncio
async def test_secondary_agent_lifecycle(deps: Any) -> None:
    ok, payload = await call(
        deps, {"action": "create", "name": "Reviewer", "agent_type": "secondary"}
    )
    assert ok, payload
    agent_id = payload["agent"]["agent_id"]
    async with deps.session_factory() as session:
        row = await get_agent(session, agent_id)
    assert row is not None and row.agent_type == "secondary"
    assert "builtin:manage_agents" not in row.tools["allow_tools"]
    assert "builtin:manage_agents" not in row.tools["builtin_tools"]

    ok, payload = await call(deps, {"action": "tools_get", "agent_id": agent_id})
    assert ok, payload
    reasons = {error["reason"] for error in payload["tools"]["validation"]["errors"]}
    assert "secondary agents cannot manage agents" not in reasons
    ok, payload = await call(
        deps, {"action": "update", "agent_id": agent_id, "system_prompt": "Review diffs."}
    )
    assert ok, payload
    ok, payload = await call(
        deps,
        {
            "action": "runtime_profiles_create",
            "agent_id": agent_id,
            "profile_id": "fast",
            "profile": {"description": "Fast"},
        },
    )
    assert ok, payload

    ok, payload = await call(
        deps,
        {"action": "bindings_set", "agent_id": "lead", "secondary_agent_ids": [agent_id]},
    )
    assert ok and payload["secondary_agent_ids"] == [agent_id], payload
    for target, ids, expected in (
        ("lead", ["manager"], "not a secondary agent"),
        ("lead", ["system:explore"], "without a binding"),
        (agent_id, ["helper"], "only be set on primary agents"),
    ):
        ok, error = await call(
            deps, {"action": "bindings_set", "agent_id": target, "secondary_agent_ids": ids}
        )
        assert not ok and expected in error, error

    ok, payload = await call(deps, {"action": "archive", "agent_id": agent_id})
    assert ok and payload["agent"]["status"] == "archived"


@pytest.mark.asyncio
async def test_revision_checks_cover_reset_disable_and_insert_race(
    deps: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, payload = await call(
        deps,
        {
            "action": "system_disable",
            "agent_id": "system:architect",
            "expected_updated_at": "",
        },
    )
    assert ok, payload
    revision = payload["system_agent"]["override_updated_at"]
    for action in ("system_enable", "system_overrides_reset"):
        ok, error = await call(
            deps, {"action": action, "agent_id": "system:architect", "expected_updated_at": ""}
        )
        assert not ok and "conflict" in error, error
    ok, payload = await call(
        deps,
        {
            "action": "system_overrides_reset",
            "agent_id": "system:architect",
            "expected_updated_at": revision,
        },
    )
    assert ok and payload["status"] == "reset"

    # A writer that observed no row must not overwrite a concurrently inserted one.
    async with deps.session_factory() as session:
        await upsert_system_agent_override(
            session,
            owner_email=OWNER,
            agent_id="system:architect",
            llm_config_override={"reasoning_effort": "high"},
        )
        await session.commit()

    async def _stale_read(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(system_agent_overrides, "get_system_agent_override", _stale_read)
    async with deps.session_factory() as session:
        with pytest.raises(SystemAgentOverrideError) as raised:
            await system_agent_overrides.set_system_agent_disabled(
                session,
                base=SYSTEM_AGENTS["system:architect"],
                owner_email=OWNER,
                disabled=True,
            )
    assert raised.value.code == "conflict"
    async with deps.session_factory() as session:
        assert not await system_agent_overrides.reset_system_agent_override(
            session,
            base=SYSTEM_AGENTS["system:architect"],
            owner_email=OWNER,
            expected_updated_at="",
        )
        await session.commit()
    agent = await effective(deps, "system:architect")
    assert agent.llm_config.reasoning_effort == "high"
    assert agent.disabled is False
