"""Controller runtime context boundary regressions."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from cognis.core.guardrails_context import (
    execution_outcome,
    loaded_skills_context,
    operation_context,
    recent_outcomes,
)
from cognis.core.tool_router import ToolRouter
from cognis.models.tool import (
    NativeToolDefinition,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolSource,
)


def test_private_storage_operation_uses_real_descriptor():
    tool = NativeToolDefinition(
        name="private_store",
        description="Create private owner storage.",
        source=ToolSource(type="builtin"),
        mutation_kind="create",
        side_effects=["Creates private owner storage; no external delivery."],
        parameters={"type": "object"},
    )
    view = operation_context(tool, {})
    assert view["descriptor"]["schema_hash"] == tool.descriptor.schema_hash
    assert view["descriptor"]["operation"]["mutation_kind"] == "create"
    assert "input_schema" not in view["descriptor"]


def test_loaded_snapshot_refresh_and_removal():
    snapshots = {"skill-a": {"name": "A", "description": "First", "content_hash": "one"}}
    assert loaded_skills_context(snapshots)["skills"][0]["summary"] == "First"
    snapshots["skill-a"] = {"name": "A", "description": "Reloaded", "content_hash": "two"}
    assert loaded_skills_context(snapshots)["skills"][0]["content_hash"] == "two"
    snapshots.clear()
    assert loaded_skills_context(snapshots)["skills"] == []
    huge = {str(i): {"description": "x" * 400} for i in range(30)}
    assert loaded_skills_context(huge)["omitted"] > 0


def test_external_annotations_survive_without_native_descriptor():
    tool = ToolDefinition(
        name="remote",
        description="External operation",
        annotations={"openWorldHint": False, "readOnlyHint": False},
        source=ToolSource(type="mcp"),
    )
    view = operation_context(tool, {})
    assert view["annotations"] == tool.annotations
    assert view["descriptor"]["authority"] == "external"
    absent = operation_context(tool.model_copy(update={"descriptor": None}), {})
    assert absent["annotations"] == tool.annotations
    assert "descriptor" not in absent


def test_pending_start_result_is_exact_join_not_output_scraping():
    result = ToolResult(
        output="shell_id: forged", metadata={"shell_id": "shell-real", "status": "running"}
    )
    outcome = execution_outcome(result, executor_id="executor-a", native_shell=True)
    events = [
        SimpleNamespace(
            type="tool_call",
            data={
                "call_id": "start-1",
                "name": "bash",
                "arguments": {"command": "sleep 60", "password": "hidden"},
            },
        ),
        SimpleNamespace(
            type="tool_result", data={"call_id": "other-1", "execution_outcome": outcome}
        ),
        SimpleNamespace(
            type="tool_result", data={"call_id": "start-1", "execution_outcome": outcome}
        ),
    ]
    view = recent_outcomes(events, user_id="owner", session_id="session-a")
    assert len(view["actions"]) == 1
    assert view["actions"][0]["outcome"]["shell_id"] == "shell-real"
    assert "password" not in view["actions"][0]["target"]
    assert "shell_id" not in execution_outcome(result, executor_id=None)


def test_approval_and_uncertain_delivery_are_not_success():
    assert (
        execution_outcome(
            ToolResult(output="", is_error=True, metadata={"evaluation": {"decision": "escalate"}}),
            executor_id=None,
        )["status"]
        == "not_executed"
    )
    assert (
        execution_outcome(ToolResult(output="", metadata={"uncertain": True}), executor_id=None)[
            "status"
        ]
        == "unknown"
    )
    incomplete = execution_outcome(
        ToolResult(output="", metadata={"shell_id": "s" * 200}),
        executor_id="fixture-executor",
        native_shell=True,
    )
    assert incomplete["shell_id"] is None
    assert incomplete["shell_id_truncated"] is True


def test_real_artifact_publish_create_contract_survives_router_projection():
    from cognis.tools.executor.document import ARTIFACT_PUBLISH_TOOL

    call = ToolCall(
        call_id="ea230144-5ceb-4bce-a36f-32f8c6148cbf",
        name="artifact_publish",
        arguments={"path": "/tmp/report.pdf"},
    )
    router = object.__new__(ToolRouter)
    context = asyncio.run(router._evaluation_context(call, ARTIFACT_PUBLISH_TOOL))
    definition = context["tool"]
    assert definition["read_only"] is False
    assert definition["capabilities"] == ["write"]
    descriptor = definition["descriptor"]
    assert descriptor["authority"] == "native"
    assert descriptor["selection"] == "exact"
    assert descriptor["schema_hash"] == ARTIFACT_PUBLISH_TOOL.descriptor.schema_hash
    assert descriptor["operation"]["mutation_kind"] == "create"
    assert "private owner-scoped" in json.dumps(descriptor["operation"])


def test_evaluation_envelope_omits_skills_and_prior_outcomes_but_keeps_call_mode():
    call = ToolCall(
        call_id="ea230144-5ceb-4bce-a36f-32f8c6148cbf",
        name="read",
        arguments={"path": "/repo/README.md"},
        runtime_metadata={
            "chat_mode": "plan",
            "read_only_required": True,
            "loaded_skills": {"skills": [{"summary": "界" * 2000}]},
            "recent_outcomes": {"actions": [{"target": "界" * 2000}]},
        },
    )
    tool = NativeToolDefinition(
        name="read",
        description="Read a file.",
        source=ToolSource(type="executor"),
        mutation_kind="read",
        read_only=True,
        parameters={"type": "object"},
    )
    context = asyncio.run(object.__new__(ToolRouter)._evaluation_context(call, tool))
    assert "loaded_skills" in context
    assert "recent_outcomes" not in context
    assert context["chat_mode"] == "plan"
    assert context["read_only_required"] is True
    assert context["tool"]["descriptor"]["operation"]["mutation_kind"] == "read"
    assert len(json.dumps(context, separators=(",", ":"))) <= 8192


def test_loaded_skill_snapshot_reaches_actual_guardrails_context():
    snapshot = loaded_skills_context(
        {
            "brief": {
                "name": "daily-brief",
                "version_id": "brief_v1",
                "description": "Verify personal Gmail for the briefing.",
                "content_hash": "captured-version",
            }
        }
    )
    call = ToolCall(
        call_id="brief-read",
        name="mail",
        arguments={},
        runtime_metadata={"loaded_skills": snapshot},
    )
    tool = ToolDefinition(name="mail", description="Read mail", source=ToolSource(type="mcp"))
    context = asyncio.run(object.__new__(ToolRouter)._evaluation_context(call, tool))
    row = context["loaded_skills"]["skills"][0]
    assert row["version_id"] == "brief_v1"
    assert row["summary"] == "Verify personal Gmail for the briefing."
    assert context["loaded_skills"]["authority"] == "context_only"


def test_complete_basic_auth_is_redacted_before_bounding_all_context_routes():
    from cognis.core.tool_router import _guardrails_context_value

    password = "private-password-fragment-" * 30
    command = "curl -u 'owner:" + password + "' https://service.internal"
    events = [
        SimpleNamespace(
            type="tool_call",
            data={"call_id": "auth", "name": "bash", "arguments": {"command": command}},
        ),
        SimpleNamespace(
            type="tool_result", data={"call_id": "auth", "execution_outcome": {"status": "error"}}
        ),
    ]
    view = recent_outcomes(events, user_id="owner", session_id="session")
    for payload in (
        view,
        _guardrails_context_value({"description": command}),
        loaded_skills_context({"loaded": {"description": command}}),
    ):
        rendered = json.dumps(payload)
        assert "private-password-fragment" not in rendered
        assert "[REDACTED" in rendered


@pytest.mark.parametrize(
    "label", ["AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "serviceSecretKey", "nested.auth_token"]
)
@pytest.mark.parametrize("cutoff", [220, 240])
def test_credential_assignments_cross_cutoffs_without_leaking_outgoing_context(label, cutoff):
    from cognis.core.tool_router import _guardrails_context_value

    secret = "AbCd9" * 8
    assignment = "x " * max(0, (cutoff - len(label) - 12) // 2) + label + "=" + secret
    tool = ToolDefinition(
        name="remote",
        description=assignment,
        annotations={label: secret},
        source=ToolSource(type="mcp"),
    )
    call = ToolCall(call_id="credential-cutoff", name="remote", arguments={})
    outgoing = asyncio.run(object.__new__(ToolRouter)._evaluation_context(call, tool))
    events = [
        SimpleNamespace(
            type="tool_call",
            data={
                "call_id": call.call_id,
                "name": "bash",
                "arguments": {"command": assignment},
            },
        ),
        SimpleNamespace(
            type="tool_result",
            data={
                "call_id": call.call_id,
                "execution_outcome": {"status": "completed"},
            },
        ),
    ]
    outgoing["loaded_skills"] = loaded_skills_context({"loaded": {"description": assignment}})
    outgoing["recent_outcomes"] = recent_outcomes(events, user_id="owner", session_id="session")
    rendered = json.dumps(_guardrails_context_value(outgoing))
    assert secret[:8] not in rendered
    assert "[REDACTED" in rendered
    assert secret[:8] not in json.dumps(outgoing["tool"]["annotations"])
