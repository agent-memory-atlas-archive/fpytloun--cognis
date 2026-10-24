from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import Mock

import pytest

from cognis.tools import introspection
from cognis.tools.builtin.schedule import MANAGE_SCHEDULES_TOOL
from cognis.tools.registry import RegisteredTool, ToolRegistry


@pytest.fixture(autouse=True)
def clear_successful_audits():
    with introspection._registration_audit_lock:
        introspection._registration_audits.clear()
    yield
    with introspection._registration_audit_lock:
        introspection._registration_audits.clear()


def register(tool):
    registry = ToolRegistry()
    registry.register(RegisteredTool(definition=tool))
    return registry


def count_audits(monkeypatch):
    audit = Mock(wraps=introspection.audit_tool_descriptors)
    monkeypatch.setattr(introspection, "audit_tool_descriptors", audit)
    return audit


def test_identical_definitions_reuse_success_but_explicit_audits_are_fresh(monkeypatch):
    audit = count_audits(monkeypatch)
    register(MANAGE_SCHEDULES_TOOL)
    register(deepcopy(MANAGE_SCHEDULES_TOOL))
    assert audit.call_count == 1
    assert introspection.audit_tool_descriptors([MANAGE_SCHEDULES_TOOL]) == []
    assert audit.call_count == 2


@pytest.mark.parametrize("field", ["parameters", "examples", "hash", "metadata"])
def test_mutated_contract_cannot_reuse_declared_hash(monkeypatch, field):
    audit = count_audits(monkeypatch)
    tool = deepcopy(MANAGE_SCHEDULES_TOOL)
    register(tool)
    original_hash = tool.descriptor.schema_hash
    if field == "parameters":
        tool.parameters["additionalProperties"] = "invalid schema value"
    elif field == "examples":
        tool.descriptor.operations[0].examples[0]["action"] = "not-a-declared-operation"
    elif field == "hash":
        tool.descriptor.schema_hash = "not-a-hash"
    else:
        tool.description += " Changed description."
    if field == "metadata":
        register(tool)
    else:
        with pytest.raises(ValueError, match="Invalid native tool contract"):
            register(tool)
    if field != "hash":
        assert tool.descriptor.schema_hash == original_hash
    assert audit.call_count == 2


def test_validator_catalog_change_forces_audit(monkeypatch):
    audit = count_audits(monkeypatch)
    register(MANAGE_SCHEDULES_TOOL)
    current = introspection.registered_native_validator_ids()
    monkeypatch.setattr(
        introspection,
        "registered_native_validator_ids",
        lambda: current | {"test_catalog_revision"},
    )
    register(MANAGE_SCHEDULES_TOOL)
    assert audit.call_count == 2


def test_failed_audits_are_never_reused(monkeypatch):
    audit = Mock(return_value=["a concrete invalid contract"])
    monkeypatch.setattr(introspection, "audit_tool_descriptors", audit)
    for _ in range(2):
        with pytest.raises(ValueError, match="Invalid native tool contract"):
            register(MANAGE_SCHEDULES_TOOL)
    assert audit.call_count == 2
    assert not introspection._registration_audits


def test_mutation_during_audit_does_not_poison_success_cache(monkeypatch):
    tool = deepcopy(MANAGE_SCHEDULES_TOOL)
    audit = Mock(
        side_effect=lambda _: setattr(tool, "description", tool.description + " changed") or []
    )
    monkeypatch.setattr(introspection, "audit_tool_descriptors", audit)
    register(tool)
    register(tool)
    assert audit.call_count == 2
    assert not introspection._registration_audits


@pytest.mark.parametrize("value", [(1, 2), {1: "integer key"}, b"bytes"])
def test_json_coercible_values_cannot_alias_a_cached_json_contract(monkeypatch, value):
    tool = deepcopy(MANAGE_SCHEDULES_TOOL)
    tool.parameters["x-test"] = value
    audit = Mock(return_value=[])
    monkeypatch.setattr(introspection, "audit_tool_descriptors", audit)
    register(tool)
    register(tool)
    assert audit.call_count == 2
    assert not introspection._registration_audits


def test_registration_cache_does_not_cache_argument_validation():
    register(MANAGE_SCHEDULES_TOOL)
    valid = introspection.validate_available_tool_call(
        [MANAGE_SCHEDULES_TOOL],
        MANAGE_SCHEDULES_TOOL.name,
        MANAGE_SCHEDULES_TOOL.descriptor.operations[0].examples[0],
    )
    assert valid["valid"]
    invalid = introspection.validate_available_tool_call(
        [MANAGE_SCHEDULES_TOOL],
        MANAGE_SCHEDULES_TOOL.name,
        {"action": "not-a-declared-operation"},
    )
    assert not invalid["valid"]


def test_cache_is_bounded_digest_only_and_evicts_lru(monkeypatch):
    monkeypatch.setattr(introspection, "_REGISTRATION_AUDIT_LIMIT", 2)
    audit = count_audits(monkeypatch)
    first = deepcopy(MANAGE_SCHEDULES_TOOL)
    second = first.model_copy(update={"description": "Second contract"})
    third = first.model_copy(update={"description": "Third contract"})
    for tool in [first, second, first, third]:
        register(tool)
    assert audit.call_count == 3
    assert len(introspection._registration_audits) == 2
    assert all(
        isinstance(key, bytes) and len(key) == 32 and value is None
        for key, value in introspection._registration_audits.items()
    )
    register(second)
    assert audit.call_count == 4


def test_registry_duplicate_merge_and_mutation_checks_still_apply():
    registry = register(deepcopy(MANAGE_SCHEDULES_TOOL))
    with pytest.raises(ValueError, match="Duplicate tool registration"):
        registry.register(RegisteredTool(definition=MANAGE_SCHEDULES_TOOL))
    with pytest.raises(ValueError, match="same source"):
        registry.merge(register(MANAGE_SCHEDULES_TOOL))
    registry.get(MANAGE_SCHEDULES_TOOL.name).definition.parameters["title"] = "Changed"
    with pytest.raises(ValueError, match="Invalid native tool contract"):
        ToolRegistry().merge(registry)


def test_concurrent_registry_creation_keeps_cache_valid_and_bounded():
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: register(MANAGE_SCHEDULES_TOOL), range(20)))
    assert len(results) == 20
    assert len(introspection._registration_audits) == 1
