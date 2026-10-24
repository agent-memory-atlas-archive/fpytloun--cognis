from __future__ import annotations

import base64
import copy
import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from cognis.models.artifact import ArtifactKind, ArtifactStatus
from cognis.models.config import ModelInfo
from cognis.providers.llm import codex_artifacts
from cognis.providers.llm.anthropic.integration import build_native_request
from cognis.providers.llm.litellm import LiteLLMProvider
from cognis.store.models import LLMProvider


@asynccontextmanager
async def _session_factory() -> AsyncIterator[object]:
    yield object()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("authorized", [False, True])
@pytest.mark.parametrize("route", ["native", "executor", "proxy"])
async def test_anthropic_generation_normalizes_many_images_before_native_serialization(
    monkeypatch: pytest.MonkeyPatch, streaming: bool, authorized: bool, route: str
) -> None:
    source = io.BytesIO()
    Image.new("RGB", (4096, 1024), "red").save(source, format="PNG")
    original_bytes = source.getvalue()
    store = SimpleNamespace(async_load=AsyncMock(return_value=(original_bytes, "image/png")))
    row = LLMProvider(
        provider_id="anthropic",
        display_name="Anthropic",
        location="executor" if route == "executor" else "controller",
        backend="litellm",
        config={
            "preset": "anthropic",
            "auth_config": {"mode": "secret", "secret_name": "anthropic"},
        },
        status="active",
    )
    if route == "proxy":
        row.config["api_base"] = "https://anthropic-proxy.test"
    # This unit test owns adapter serialization, not durable route resolution.
    service = LiteLLMProvider(_session_factory, artifact_store=store, inference_router=object())
    monkeypatch.setattr(
        service, "_resolve_model_target", AsyncMock(return_value=("claude-opus-5-5", row))
    )
    monkeypatch.setattr(
        service, "get_model_info", AsyncMock(return_value=ModelInfo(model_id="claude-opus-5-5"))
    )
    monkeypatch.setattr(service, "_resolve_provider_kwargs", AsyncMock(return_value={}))
    record = SimpleNamespace(
        artifact_id="img_large",
        kind=ArtifactKind.IMAGE,
        status=ArtifactStatus.ATTACHED,
        size_bytes=len(original_bytes),
        namespace="conversation",
        object_id="conv_images",
        filename="large.png",
        deleted_at=None,
        expires_at=None,
    )
    monkeypatch.setattr(codex_artifacts, "get_artifact_records", AsyncMock(return_value=[record]))
    authorization = AsyncMock(return_value=authorized)
    monkeypatch.setattr(codex_artifacts, "artifact_authorized_for_conversation", authorization)
    payloads: list[dict[str, Any]] = []
    dispatched_routes: list[str] = []

    class Client:
        async def complete(self, context: Any, payload: Any, bundle: Any, **kwargs: Any) -> Any:
            dispatched_routes.append("native")
            payloads.append(payload)
            return {"choices": [{"message": {"content": "done"}}]}

        async def stream(
            self, context: Any, payload: Any, bundle: Any, **kwargs: Any
        ) -> AsyncIterator[dict[str, Any]]:
            dispatched_routes.append("native")
            payloads.append(payload)
            yield {"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(
        service,
        "_native_anthropic_client",
        AsyncMock(return_value=(Client(), "$credential:anthropic")),
    )
    response = {"choices": [{"message": {"content": "done"}}]}

    def capture_dispatch(messages: list[dict[str, Any]]) -> None:
        assert "cognis_artifact" not in str(messages)
        # Inspect the same native image representation regardless of dispatch route.
        _context, payload, _bundle = build_native_request(
            provider=row,
            model="claude-opus-5-5",
            model_info=ModelInfo(model_id="claude-opus-5-5"),
            messages=messages,
            request_kwargs={},
            credential_ref="$credential:anthropic",
        )
        payloads.append(payload)

    async def executor_generate(
        model: str, messages: list[dict[str, Any]], provider: Any, **kwargs: Any
    ) -> dict[str, Any]:
        dispatched_routes.append("executor")
        capture_dispatch(messages)
        return response

    async def executor_stream(
        model: str, messages: list[dict[str, Any]], provider: Any, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        dispatched_routes.append("executor")
        capture_dispatch(messages)
        yield {"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}

    async def proxy_completion(**kwargs: Any) -> Any:
        dispatched_routes.append("proxy")
        capture_dispatch(kwargs["messages"])
        if kwargs["stream"]:

            async def chunks() -> AsyncIterator[dict[str, Any]]:
                yield {"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}

            return chunks()
        return SimpleNamespace(model_dump=lambda: response)

    monkeypatch.setattr(service, "_executor_generate", executor_generate)
    monkeypatch.setattr(service, "_executor_stream_generate", executor_stream)
    monkeypatch.setattr(service._litellm_transport, "completion", proxy_completion)
    part = {
        "type": "image_url",
        "image_url": {
            "url": "https://cognis.test/original-image",
            "cognis_artifact": {"artifact_id": record.artifact_id, "filename": record.filename},
        },
    }
    # Anthropic's stricter dimension limit applies once a request contains >20 images.
    messages = [{"role": "user", "content": [copy.deepcopy(part) for _ in range(21)]}]
    external_url = "https://external-image.test/photo.png"
    messages[0]["content"].append({"type": "image_url", "image_url": {"url": external_url}})
    original_messages = copy.deepcopy(messages)
    identity = {
        "model": "claude-opus-5-5",
        "provider_id": row.provider_id,
        "acting_user_email": "owner@test.local",
        "cognis_conversation_id": "conv_images",
        "cognis_agent_id": "agent_images",
    }
    try:
        if streaming:
            chunks = [chunk async for chunk in service.stream_generate(messages, **identity)]
            assert chunks[0]["choices"][0]["delta"]["content"] == "done"
        else:
            result = await service.generate(messages, **identity)
            assert result["choices"][0]["message"]["content"] == "done"
        assert len(payloads) == 1
        assert dispatched_routes == [route]
        blocks = [block for message in payloads[0]["messages"] for block in message["content"]]
        images = [
            block
            for block in blocks
            if block["type"] == "image" and block["source"]["type"] == "base64"
        ]
        external_images = [
            block
            for block in blocks
            if block["type"] == "image" and block["source"]["type"] == "url"
        ]
        assert len(external_images) == 1
        assert external_images[0]["source"]["url"] == external_url
        if authorized:
            assert len(images) == 21
            for image in images:
                assert image["source"]["type"] == "base64"
                with Image.open(io.BytesIO(base64.b64decode(image["source"]["data"]))) as decoded:
                    assert decoded.size == (2048, 512)
            store.async_load.assert_awaited_once()
        else:
            assert not images
            assert all(
                "was not sent" in block["text"] for block in blocks if block["type"] == "text"
            )
            store.async_load.assert_not_awaited()
        authorization.assert_awaited_once()
        assert authorization.await_args.kwargs["owner_email"] == identity["acting_user_email"]
        assert (
            authorization.await_args.kwargs["conversation_id"] == identity["cognis_conversation_id"]
        )
        assert authorization.await_args.kwargs["agent_id"] == identity["cognis_agent_id"]
        assert messages == original_messages
        assert store.async_load.return_value[0] == original_bytes
        assert "cognis_artifact" not in str(payloads[0])
        assert "original-image" not in str(payloads[0])
    finally:
        await service.aclose()
