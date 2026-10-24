"""Assert URL and model normalization at HTTP, not just mocked SDK arguments."""

from __future__ import annotations

import json
from types import SimpleNamespace

import litellm
import pytest
import respx

from cognis.providers.llm.compatible_transport import (
    openai_api_base,
    openai_endpoint,
    proxy_service_root,
)
from cognis.providers.llm.litellm import LiteLLMProvider, _provider_request_kwargs_from_config
from cognis.providers.llm.monitoring import probe_connectivity


@pytest.fixture(autouse=True)
def use_httpx_transport(monkeypatch):
    # respx intercepts HTTPX, not LiteLLM's optional aiohttp transport.
    monkeypatch.setattr(litellm, "disable_aiohttp_transport", True)


@pytest.mark.parametrize(
    "base",
    [
        "https://api.groq.com/openai",
        "https://api.groq.com/openai/",
        "https://api.groq.com/openai/v1",
        "https://api.groq.com/openai/v1/",
        "http://localhost:4000",
        "http://localhost:4000/v1/",
        "https://host.test/prefix",
        "https://host.test/prefix/v1",
    ],
)
def test_version_normalization_is_idempotent_and_preserves_prefix(base):
    root = base.rstrip("/").removesuffix("/v1")
    assert openai_api_base(base) == root + "/v1"
    assert openai_api_base(openai_api_base(base)) == root + "/v1"
    assert openai_endpoint(base, "models") == root + "/v1/models"
    assert proxy_service_root(base) == root


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/", "/v1", "/v1/"])
@pytest.mark.parametrize("preset", ["openai_compatible", "litellm_proxy"])
async def test_discovery_probe_and_chat_use_same_base_and_literal_model(suffix, preset):
    base = "https://gateway.test/openai" + suffix
    config = {"preset": preset, "base_url": base}
    row = SimpleNamespace(config=config, location="controller")
    kwargs = _provider_request_kwargs_from_config(config)
    model = "openai/gpt-oss-20b"
    wire_model = LiteLLMProvider._apply_model_prefix(model, row)
    service = LiteLLMProvider(None)
    with respx.mock(assert_all_called=False) as mock:
        models = mock.get("https://gateway.test/openai/v1/models").respond(
            200,
            json={"data": [{"id": model}]},
        )
        # LiteLLM metadata belongs at the service root, even when base has /v1.
        metadata = mock.get("https://gateway.test/openai/model/info").respond(404)
        chat = mock.post("https://gateway.test/openai/v1/chat/completions").respond(
            200,
            json={
                "id": "chatcmpl-wire",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )
        found = await service._discover_models_remote(preset, base, "test-credential")
        assert any(entry["model_id"] == model for entry in found)
        assert (await probe_connectivity(row, kwargs))["status"] == "healthy"
        await litellm.acompletion(
            model=wire_model,
            api_key="test-credential",
            messages=[{"role": "user", "content": "Check"}],
            reasoning_effort="low",
            num_retries=0,
            **kwargs,
        )
        assert models.call_count == 2
        assert metadata.called is (preset == "litellm_proxy")
        payload = json.loads(chat.calls.last.request.content)
        assert payload["model"] == model
        assert payload["reasoning_effort"] == "low"


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/v1/"])
async def test_embedding_and_proxy_metadata_paths(suffix):
    base = "https://proxy.test/prefix" + suffix
    row = SimpleNamespace(config={"preset": "litellm_proxy", "base_url": base})
    service = LiteLLMProvider(None)
    with respx.mock as mock:
        metadata = mock.get("https://proxy.test/prefix/model/info").respond(200, json={"data": []})
        embeddings = mock.post("https://proxy.test/prefix/v1/embeddings").respond(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )
        await service._fetch_proxy_model_info(base, "test-credential", bypass_cache=True)
        await litellm.aembedding(
            model=service._apply_model_prefix("text-embedding-3-small", row),
            input=["test"],
            api_key="test-credential",
            **_provider_request_kwargs_from_config(row.config),
        )
        assert metadata.called and embeddings.called


def test_native_provider_endpoints_and_model_names_are_unchanged():
    for preset, base in [
        ("ollama", "http://localhost:11434"),
        ("anthropic", "https://api.anthropic.com"),
    ]:
        assert (
            _provider_request_kwargs_from_config({"preset": preset, "base_url": base})["api_base"]
            == base
        )
    assert (
        LiteLLMProvider._apply_model_prefix("gpt-4o", SimpleNamespace(config={"preset": "openai"}))
        == "gpt-4o"
    )
