import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from pydantic_core import SchemaValidator, core_schema

from cognis.models.tool import ToolMutationKind
from cognis.models.video import VideoRequest
from cognis.tools.builtin.video import handle_video_tool, video_tools


def test_video_tools_are_declared_and_do_not_wrap_local_processing():
    from cognis.tools.introspection import audit_tool_descriptors

    tools = {tool.name: tool for tool in video_tools()}
    assert audit_tool_descriptors(list(tools.values())) == []
    assert "video_process" not in tools and "video_inspect" not in tools
    assert tools["video_models"].read_only
    assert tools["video_job_get"].read_only
    for name in (
        "video_generate",
        "video_edit",
        "video_extend",
        "video_analyze",
        "video_job_cancel",
        "video_job_recover",
    ):
        assert not tools[name].read_only
        assert tools[name].native_operations[0].mutation_kind != ToolMutationKind.READ
        assert tools[name].category == "video"


@pytest.mark.parametrize("tool_name", ["video_generate", "video_edit", "video_extend"])
def test_video_cost_schema_uses_portable_regex_and_retains_numeric_bounds(tool_name: str) -> None:
    tool = next(tool for tool in video_tools() if tool.name == tool_name)
    schema = tool.parameters
    cost_schema = schema["$defs"]["VideoRequest"]["properties"]["max_cost_usd"]
    numeric_schema, string_schema, null_schema = cost_schema["anyOf"]
    assert null_schema == {"type": "null"}
    assert "max_cost_usd" not in schema["$defs"]["VideoRequest"]["required"]
    assert numeric_schema == {"type": "number", "exclusiveMinimum": 0, "maximum": 1000}
    # pydantic-core uses Rust regex: unsupported lookarounds fail at compilation.
    pattern_validator = SchemaValidator(core_schema.str_schema(pattern=string_schema["pattern"]))
    for value in ["1", "0.25", ".25", "1.", "+2", "1e-3", "1000"]:
        assert pattern_validator.validate_python(value) == value
    for value in ["", ".", "+", "NaN", "Infinity", "USD 1"]:
        with pytest.raises(ValidationError):
            pattern_validator.validate_python(value)
    validator = Draft202012Validator(schema)
    validator.validate({"request": {"prompt": "A waterfall"}, "idempotency_key": "no-cap"})
    for cost in [1, 0.25, "0.25", "1e-3"]:
        validator.validate(
            {
                "request": {"prompt": "A waterfall", "max_cost_usd": cost},
                "idempotency_key": "cost-schema-check",
            }
        )
    for cost in [0, -1, 1001]:
        assert not validator.is_valid(
            {
                "request": {"prompt": "A waterfall", "max_cost_usd": cost},
                "idempotency_key": "cost-schema-check",
            }
        )


@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_video_cost_json_schema_is_portable_in_both_modes(mode: str) -> None:
    schema = VideoRequest.model_json_schema(mode=mode)["properties"]["max_cost_usd"]
    for alternative in schema.get("anyOf", [schema]):
        if alternative.get("type") == "string":
            SchemaValidator(core_schema.str_schema(pattern=alternative["pattern"]))


@pytest.mark.parametrize("cost", ["0.1234567890123456789", "1e-3", 1, 0.25, "1000"])
def test_video_cost_retains_decimal_validation_and_roundtrip(cost: str | int | float) -> None:
    request = VideoRequest(prompt="A waterfall", max_cost_usd=cost)
    assert isinstance(request.max_cost_usd, Decimal)
    assert request.max_cost_usd == Decimal(str(cost))
    assert VideoRequest.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize("cost", [0, -1, "1000.0001", "NaN", "Infinity", "-Infinity", "", "."])
@pytest.mark.asyncio
async def test_invalid_video_cost_never_reaches_service(cost: str | int) -> None:
    service = SimpleNamespace(create=AsyncMock())
    result = await handle_video_tool(
        "video_generate",
        {
            "request": {"prompt": "A waterfall", "max_cost_usd": cost},
            "idempotency_key": "invalid-cost-check",
        },
        service=service,
        owner="owner@test",
        conversation_id="video-conversation",
    )
    assert result.is_error
    service.create.assert_not_called()


@pytest.mark.asyncio
async def test_tool_dispatch_binds_conversation_and_owner():
    service = SimpleNamespace(create=AsyncMock(return_value={"status": "queued"}))
    result = await handle_video_tool(
        "video_generate",
        {
            "request": {"prompt": "A waterfall", "max_cost_usd": "2"},
            "idempotency_key": "first-render",
        },
        service=service,
        owner="owner@test",
        conversation_id="video-conversation",
    )
    assert json.loads(result.output)["status"] == "queued"
    owner, request = service.create.call_args.args
    assert owner == "owner@test" and request.conversation_id == "video-conversation"


@pytest.mark.asyncio
async def test_edit_cannot_sneak_generation():
    service = SimpleNamespace(create=AsyncMock())
    result = await handle_video_tool(
        "video_edit",
        {
            "request": {"prompt": "A waterfall", "max_cost_usd": "2"},
            "idempotency_key": "first-render",
        },
        service=service,
        owner="owner@test",
        conversation_id="video-conversation",
    )
    assert result.is_error
    service.create.assert_not_called()
