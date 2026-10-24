"""Controller/router/runner adapter contract with upstream network calls mocked."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cognis.executor.inference import InferenceHandler
from cognis.executor.runner import ExecutorRunner
from cognis.models.tool import ExecutorConfig
from cognis.providers.llm.inference_router import InferenceRouter


@pytest.mark.asyncio
async def test_nonstreaming_embeddings_cross_router_runner_and_backend(monkeypatch):
    runner = ExecutorRunner(ExecutorConfig(executor_id="remote", controller_token="test-token"))
    runner._inference_handler = InferenceHandler()
    runner._send_rpc_result = AsyncMock()
    response = {"data": [{"embedding": [0.1, 0.2], "index": 0}], "usage": {"total_tokens": 2}}
    upstream = AsyncMock(return_value=SimpleNamespace(model_dump=lambda: response))
    monkeypatch.setattr("cognis.executor.backends.litellm.litellm.aembedding", upstream)

    async def rpc_call(*, method, params, timeout):
        assert method == "llm.complete"
        assert params["stream"] is False
        await runner._handle_llm_complete(None, params["request_id"], params)
        return runner._send_rpc_result.call_args.args[2]

    router = InferenceRouter(SimpleNamespace())
    monkeypatch.setattr(
        router, "_find_executor", AsyncMock(return_value=SimpleNamespace(rpc_call=rpc_call))
    )
    result = await router.route_generate(
        messages=[],
        model="text-embedding-3-small",
        provider_id="private-provider",
        owner_email="owner@cognis.local",
        request_kwargs={
            "cognis_llm_api": "embeddings",
            "input": ["hello"],
            "num_retries": 0,
            "max_retries": 0,
            "timeout": 5,
        },
    )
    assert result == response
    router._find_executor.assert_awaited_once_with(
        None,
        None,
        model="text-embedding-3-small",
        provider_id="private-provider",
        owner_email="owner@cognis.local",
    )
    assert upstream.await_count == 1
    assert upstream.call_args.kwargs["num_retries"] == 0
    assert upstream.call_args.kwargs["timeout"] == 5


@pytest.mark.asyncio
async def test_typed_executor_disconnect_is_retryable(monkeypatch):
    from cognis.providers.executor.websocket import ExecutorDisconnectedError
    from cognis.providers.llm.errors import LLMStreamProviderError

    router = InferenceRouter(SimpleNamespace())
    connection = SimpleNamespace(
        rpc_call=AsyncMock(side_effect=ExecutorDisconnectedError("connection lost"))
    )
    monkeypatch.setattr(router, "_find_executor", AsyncMock(return_value=connection))
    with pytest.raises(LLMStreamProviderError) as failure:
        await router.route_generate(
            messages=[],
            model="text-embedding-3-small",
            request_kwargs={"cognis_llm_api": "embeddings"},
        )
    assert failure.value.to_payload()["category"] == "connection"


@pytest.mark.asyncio
async def test_executor_speech_failure_is_exactly_one_physical_call(monkeypatch):
    from cognis.executor.backends.tts import run_synthesize_local

    upstream = AsyncMock(side_effect=ConnectionError("disconnected"))
    http = AsyncMock()
    monkeypatch.setattr("cognis.executor.backends.tts.litellm.aspeech", upstream)
    monkeypatch.setattr("cognis.executor.backends.tts.httpx.AsyncClient.post", http)
    with pytest.raises(ConnectionError):
        await run_synthesize_local(
            text="hello",
            voice="alloy",
            wire_model="tts-1",
            response_format="mp3",
            speed=1,
            request_kwargs={"timeout": 5, "num_retries": 0, "max_retries": 0},
            resolved_model="tts-1",
            provider_preset="openai",
        )
    assert upstream.await_count == 1
    assert upstream.call_args.kwargs["num_retries"] == 0
    assert upstream.call_args.kwargs["max_retries"] == 0
    http.assert_not_called()


@pytest.mark.asyncio
async def test_executor_image_preserves_deadline_and_zero_retries(monkeypatch):
    upstream = AsyncMock(
        return_value=SimpleNamespace(model_dump=lambda: {"data": [{"b64_json": "aW1hZ2U="}]})
    )
    monkeypatch.setattr("cognis.executor.backends.litellm.litellm.aimage_generation", upstream)
    await InferenceHandler().image_generate(
        prompt="square",
        model="gpt-image-2",
        request_kwargs={"timeout": 5, "num_retries": 0, "max_retries": 0},
    )
    assert upstream.await_count == 1
    assert upstream.call_args.kwargs["timeout"] == 5
    assert upstream.call_args.kwargs["num_retries"] == 0
    assert upstream.call_args.kwargs["max_retries"] == 0
