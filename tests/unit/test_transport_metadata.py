"""Internal request metadata must not reach Chat/Responses upstream SDKs."""

from unittest.mock import AsyncMock

import pytest

from cognis.providers.llm import transport


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,sdk",
    [
        ("completion", "acompletion"),
        ("responses", "aresponses"),
    ],
)
@pytest.mark.parametrize("stream", [False, True])
async def test_transport_strips_internal_namespaces_without_mutating_input(
    monkeypatch,
    operation,
    sdk,
    stream,
):
    call = AsyncMock(return_value={"id": "response-transport-test"})
    monkeypatch.setattr(transport.litellm, sdk, call)
    kwargs = {
        "model": "litellm_proxy/openai/gpt-oss-120b",
        "stream": stream,
        "cognis_llm_request_id": "chatcmpl-transport-test",
        "cognis_session_id": "session-transport-test",
        "_cognis_executor_affinity_id": "executor-transport-test",
        "_cognis_trace_context": {"operation": "test"},
        "cognis_llm_api": "responses",
        "reasoning_effort": "low",
        "metadata": {"application": "inference-test"},
    }
    result = await getattr(transport.LiteLLMTransport(), operation)(**kwargs)
    assert result == {"id": "response-transport-test"}
    sent = call.call_args.kwargs
    assert sent == {
        "model": kwargs["model"],
        "stream": stream,
        "reasoning_effort": "low",
        "metadata": kwargs["metadata"],
    }
    assert kwargs["cognis_llm_request_id"] == "chatcmpl-transport-test"


def test_shared_filter_and_codex_keep_original_metadata():
    from copy import deepcopy

    from cognis.providers.llm.codex_transport import _codex_payload

    kwargs = {
        "model": "gpt-5",
        "input": "test",
        "stream": False,
        "cognis_llm_request_id": "chatcmpl-codex-test",
        "_cognis_trace_context": {"operation": "test"},
    }
    original = deepcopy(kwargs)
    assert transport.strip_controller_transport_kwargs(kwargs) == {
        "model": "gpt-5",
        "input": "test",
        "stream": False,
    }
    payload, stream = _codex_payload(kwargs)
    assert payload == {"model": "gpt-5", "input": "test", "stream": False, "store": False}
    assert stream is False
    assert kwargs == original
