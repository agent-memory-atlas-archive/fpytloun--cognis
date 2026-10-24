from __future__ import annotations

from copy import deepcopy
from unittest.mock import Mock

import pytest

from cognis.models.tool import ToolDefinition, ToolSource, stable_tool_id
from cognis.tools import introspection
from cognis.tools.builtin.schedule import MANAGE_SCHEDULES_TOOL
from cognis.tools.registry import RegisteredTool, ToolRegistry


def setup_registry():
    first = deepcopy(MANAGE_SCHEDULES_TOOL)
    second = first.model_copy(update={"name": "another_schedule_tool"}, deep=True)
    registry = ToolRegistry()
    registry.register_many([RegisteredTool(first), RegisteredTool(second)])
    overrides = {
        stable_tool_id(first): first.model_copy(
            update={"description": first.description + " Classified annotation."}, deep=True
        )
    }
    return registry, overrides, first, second


def test_construction_has_no_audit_sweep_and_lookup_audits_only_selected(monkeypatch):
    registry, overrides, first, second = setup_registry()
    audit = Mock(wraps=introspection.audit_tool_registration)
    monkeypatch.setattr(introspection, "audit_tool_registration", audit)
    view = registry.with_definition_overrides(overrides)
    assert isinstance(view, ToolRegistry)
    audit.assert_not_called()
    registered = view.get(first.name)
    assert registered.definition.description.endswith(" Classified annotation.")
    assert not registry.get(first.name).definition.description.endswith(" Classified annotation.")
    assert audit.call_count == 1
    assert view.get(second.name).definition is second
    assert audit.call_count == 2
    assert view.get("absent") is None
    assert audit.call_count == 2


def test_mutation_removal_and_current_handler_are_not_cached():
    registry, overrides, first, _ = setup_registry()
    view = registry.with_definition_overrides(overrides)
    replacement = overrides[stable_tool_id(first)]
    replacement.description += " Changed."
    assert view.get(first.name).definition.description.endswith(" Changed.")
    first_handler = Mock()
    second_handler = Mock()
    registry.get(first.name).handler = first_handler
    assert view.get(first.name).handler is first_handler
    registry.get(first.name).handler = second_handler
    assert view.get(first.name).handler is second_handler
    overrides.clear()
    assert view.get(first.name).definition is first
    # No negative lookup caching: newly registered tools are visible as well.
    third = first.model_copy(update={"name": "third_schedule_tool"}, deep=True)
    assert view.get(third.name) is None
    registry.register(RegisteredTool(third))
    assert view.get(third.name).definition is third


@pytest.mark.parametrize("operation", ["get", "items", "list_tools", "export"])
def test_invalid_effective_definition_never_falls_back(operation):
    registry, overrides, first, _ = setup_registry()
    view = registry.with_definition_overrides(overrides)
    overrides[stable_tool_id(first)].descriptor.schema_hash = "changed-without-validation"
    with pytest.raises(ValueError, match="Invalid native tool contract"):
        getattr(view, operation)(first.name) if operation == "get" else getattr(view, operation)()


def test_unrelated_invalid_definition_is_rejected_on_use_or_full_enumeration():
    registry, overrides, first, second = setup_registry()
    view = registry.with_definition_overrides(overrides)
    second.descriptor.schema_hash = "changed-without-validation"
    assert view.get(first.name).definition.description.endswith(" Classified annotation.")
    with pytest.raises(ValueError, match="Invalid native tool contract"):
        view.get(second.name)
    with pytest.raises(ValueError, match="Invalid native tool contract"):
        view.export()


def test_export_order_and_merge_match_eager_registry():
    registry, overrides, _, _ = setup_registry()
    eager = ToolRegistry()
    for item in registry.items():
        eager.register(
            RegisteredTool(
                overrides.get(stable_tool_id(item.definition), item.definition), item.handler
            )
        )
    view = registry.with_definition_overrides(overrides)
    assert view.export() == eager.export()
    assert [t.definition.name for t in view.items()] == [t.definition.name for t in eager.items()]
    assert view.merge().export() == eager.merge().export()
    with pytest.raises(ValueError, match="same source"):
        view.merge(registry)
    with pytest.raises(TypeError, match="read-only"):
        view.register(RegisteredTool(MANAGE_SCHEDULES_TOOL))
    with pytest.raises(TypeError, match="read-only"):
        view.register_many([])


def test_no_matching_overrides_returns_original():
    registry, _, first, _ = setup_registry()
    assert registry.with_definition_overrides({}) is registry
    assert registry.with_definition_overrides({"unrelated-stable-id": first}) is registry


def test_name_remapping_retains_eager_registration_and_collision_checks():
    registry, overrides, first, second = setup_registry()
    replacement = overrides[stable_tool_id(first)]
    replacement.name = "renamed_schedule_tool"
    renamed = registry.with_definition_overrides(overrides)
    assert renamed.get(first.name) is None
    assert renamed.get(replacement.name).definition is replacement
    replacement.name = second.name
    with pytest.raises(ValueError, match="Duplicate tool registration"):
        registry.with_definition_overrides(overrides)


def test_source_change_after_creation_fails_closed():
    registry, overrides, first, _ = setup_registry()
    view = registry.with_definition_overrides(overrides)
    overrides[stable_tool_id(first)].source = ToolSource(type="executor")
    with pytest.raises(ValueError, match="identity changed"):
        view.get(first.name)


def test_name_change_after_creation_fails_closed():
    registry, overrides, first, _ = setup_registry()
    view = registry.with_definition_overrides(overrides)
    overrides[stable_tool_id(first)].name = "renamed_after_view"
    with pytest.raises(ValueError, match="identity changed"):
        view.get(first.name)


def test_base_and_new_context_registry_do_not_share_state():
    registry, overrides, first, _ = setup_registry()
    previous = registry.with_definition_overrides(overrides)
    newer_registry = ToolRegistry()
    newer = newer_registry.with_definition_overrides(overrides)
    assert previous.get(first.name) is not None
    assert newer.get(first.name) is None
    assert newer.export() == []


@pytest.mark.parametrize("source_type", ["local_mcp", "intaris_mcp"])
def test_external_classification_and_revocation_are_read_through(source_type):
    original = ToolDefinition(
        name="mcp__integration__read",
        description="Read external information",
        parameters={"type": "object"},
        source=ToolSource(type=source_type, server_name="integration", raw_tool_name="read"),
    )
    registry = ToolRegistry()
    registry.register(RegisteredTool(original))
    classifications = {
        stable_tool_id(original): original.model_copy(
            update={"read_only": True, "non_bypassable": False, "classification_status": "ready"},
            deep=True,
        )
    }
    view = registry.with_definition_overrides(classifications)
    assert view.get(original.name).definition.non_bypassable is False
    classifications[stable_tool_id(original)].non_bypassable = True
    classifications[stable_tool_id(original)].read_only = False
    assert view.get(original.name).definition.non_bypassable is True
    assert view.get(original.name).definition.read_only is False
    classifications.clear()
    assert view.get(original.name).definition is original
