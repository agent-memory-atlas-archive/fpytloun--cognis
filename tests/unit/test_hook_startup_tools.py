"""Startup hints use the existing filtered inventory, not additional grants."""

from types import SimpleNamespace

import pytest

from cognis.core.agent_loop import AgentLoop
from cognis.core.hooks import hook_startup_tool_names
from cognis.models.agent import AgentDefinition, AgentPermissions
from cognis.models.workflow import StepDefinition
from cognis.tools.builtin.skill_management import skill_management_tools
from cognis.tools.registry import RegisteredTool, ToolRegistry


def _session(hook_id="system:self-improvement", mode="hook", internal=True):
    return SimpleNamespace(
        delegation_mode=mode,
        delegation_metadata={"hook_id": hook_id, "internal": internal},
    )


@pytest.mark.parametrize("mode,internal", [("delegate", True), ("hook", False), (None, True)])
def test_non_hook_sessions_never_receive_startup_hints(mode, internal):
    assert not hook_startup_tool_names(_session(mode=mode, internal=internal))


@pytest.mark.parametrize("hook_id", ["custom-hook", None, []])
def test_unknown_hooks_do_not_get_inferred_or_blanket_tools(hook_id):
    assert not hook_startup_tool_names(_session(hook_id=hook_id))


def test_bundled_hint_sets_are_bounded_and_deterministic():
    assert hook_startup_tool_names(_session()) == frozenset(
        {"skill_list", "skill_get", "skill_load", "skill_patch", "skill_write"}
    )
    assert hook_startup_tool_names(_session("system:memory-consolidation")) == frozenset(
        {"memory_search", "memory_recent", "memory_add"}
    )


@pytest.mark.parametrize("denied", [False, True])
@pytest.mark.parametrize("step_denied", [False, True])
def test_hook_startup_promotion_uses_permission_filtered_registry(denied, step_denied):
    registry = ToolRegistry()
    for tool in skill_management_tools():
        if tool.name in ("skill_get", "skill_patch"):
            registry.register(RegisteredTool(definition=tool))
    agent = AgentDefinition(
        agent_id="hook-agent",
        owner_email="owner@test.local",
        name="Hook",
        permissions=AgentPermissions(
            denied_tools=["skill_patch"] if denied else [],
        ),
    )
    ctx = SimpleNamespace(
        agent=agent,
        session=_session(),
        tool_registry=registry,
        step_definition=StepDefinition(
            name="hook",
            type="run",
            step_profile={"tool_overrides": {"exclude": ["skill_patch"] if step_denied else []}},
        ),
    )
    loop = object.__new__(AgentLoop)
    promoted = loop._get_initial_promoted_tool_ids(ctx)
    assert "builtin:skill_get" in promoted
    assert ("builtin:skill_patch" in promoted) is not (denied or step_denied)
    assert loop._get_initial_promoted_tool_ids(ctx) == promoted
