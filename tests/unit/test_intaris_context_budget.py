"""Bound the final protocol envelope, not only individual raw strings."""

import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from cognis.core.tool_router import ToolRouter
from cognis.models.tool import ToolCall, ToolDefinition, ToolSource
from cognis.providers.guardrails.evaluation_context import (
    EvaluationContextTooLarge,
    fit_evaluation_context,
    serialized_size,
)
from cognis.providers.guardrails.intaris import IntarisProvider


def test_unicode_metadata_reproduces_final_serialization_overflow():
    tool = ToolDefinition(
        name="outlook_query",
        description="界" * 900,
        source=ToolSource(type="mcp"),
        parameters={
            "type": "object",
            "properties": {
                f"field_{i}": {"type": "string", "description": "界" * 240} for i in range(12)
            },
        },
    )
    call = ToolCall(
        call_id="local-context-reproduction",
        name=tool.name,
        arguments={"query": "unchanged"},
        runtime_metadata={"chat_mode": "plan", "read_only_required": True},
    )
    context = asyncio.run(object.__new__(ToolRouter)._evaluation_context(call, tool))
    # Individual values fit their limits; the complete escaped object does not.
    assert len(context["tool"]["description"]) == 900
    assert len(json.dumps(context, separators=(",", ":"))) > 8192
    assert call.arguments == {"query": "unchanged"}
    fitted = fit_evaluation_context(context)
    assert serialized_size(fitted) <= 8192
    assert fitted["read_only_required"] is True
    assert fitted["chat_mode"] == "plan"


@pytest.mark.parametrize("text", ["界" * 4000, "😀" * 4000, '"\\\n' * 4000, "a" * 16000])
def test_final_fit_preserves_head_tail_and_protected_facts(text):
    context = {
        "tool_call_id": "local-original-call",
        "read_only_required": True,
        "chat_mode": "plan",
        "minimum_outcome": "escalate",
        "approval_call_id": "local-original-receipt",
        "tool": {
            "id": "local-executor-tool",
            "description": "HEAD" + text + "TAIL",
            "descriptor": {
                "schema_hash": "unchanged-hash",
                "selection": "exact",
                "operation": {"mutation_kind": "write", "side_effects": ["disk write"]},
            },
        },
    }
    before = copy.deepcopy(context)
    fitted = fit_evaluation_context(context)
    assert context == before
    assert serialized_size(fitted) <= 8192
    assert fitted["tool"]["description"].startswith("HEAD")
    assert fitted["tool"]["description"].endswith("TAIL")
    assert "[TRUNCATED]" in fitted["tool"]["description"]
    for key in (
        "tool_call_id",
        "read_only_required",
        "chat_mode",
        "minimum_outcome",
        "approval_call_id",
    ):
        assert fitted[key] == before[key]
    assert fitted["tool"]["descriptor"] == before["tool"]["descriptor"]
    assert fit_evaluation_context(fitted) == fitted


def test_oversize_protected_fields_not_dropped_to_fit():
    with pytest.raises(EvaluationContextTooLarge) as caught:
        fit_evaluation_context({"constraints": "FORBIDDEN_PRIVATE_EVIDENCE" * 1000})
    assert "FORBIDDEN_PRIVATE_EVIDENCE" not in str(caught.value)
    assert fit_evaluation_context(None) is None
    small = {"read_only_required": True}
    assert fit_evaluation_context(small) is small


def test_multiple_descriptions_share_budget_without_erasing_head_tail():
    properties = {f"field_{i}": {"description": "HEAD" + "界" * 900 + "TAIL"} for i in range(12)}
    context = {
        "tool": {"parameters_summary": {"properties": properties}},
        "read_only_required": True,
    }
    fitted = fit_evaluation_context(context)
    assert serialized_size(fitted) <= 8192
    for item in fitted["tool"]["parameters_summary"]["properties"].values():
        assert item["description"].startswith("HEAD")
        assert item["description"].endswith("TAIL")


@pytest.mark.asyncio
async def test_provider_fits_after_added_floor_and_never_mutates_arguments():
    seen = []

    def respond(request):
        body = json.loads(request.content)
        seen.append(body)
        assert serialized_size(body["context"]) <= 8192
        return httpx.Response(
            200,
            json={
                "call_id": "local-response",
                "decision": "escalate",
                "reasoning": "test",
                "risk": "low",
                "path": "test",
                "minimum_outcome": "escalate",
            },
        )

    provider = IntarisProvider(
        "http://intaris.test", SimpleNamespace(sign_service_jwt=lambda *a, **kw: "signed-token")
    )
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="http://intaris.test", transport=httpx.MockTransport(respond)
    )
    arguments = {"content": "ACTION_BODY_MUST_REMAIN" * 100}
    context = {"minimum_outcome": "escalate", "tool": {"description": "界" * 3000}}
    before = copy.deepcopy(context)
    try:
        await provider.evaluate("local-session", "write", arguments, context)
        assert seen[0]["args"] == arguments
        assert seen[0]["minimum_outcome"] == "escalate"
        assert context == before
        with pytest.raises(EvaluationContextTooLarge):
            await provider.evaluate(
                "local-session", "write", arguments, {"constraints": "界" * 3000}
            )
        assert len(seen) == 1
    finally:
        await provider.client.aclose()
