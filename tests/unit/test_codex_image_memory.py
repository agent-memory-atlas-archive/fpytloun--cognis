import asyncio
import io
import threading

import pytest
from PIL import Image

from cognis.providers.llm import codex_artifacts as images


def test_pixel_budget_before_decode(monkeypatch):
    buffer = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buffer, format="PNG")
    monkeypatch.setattr(images, "MAX_CODEX_IMAGE_PIXELS", 9999)
    with pytest.raises(images.CodexArtifactError, match="pixel budget"):
        images._normalize_image(buffer.getvalue(), artifact_id="synthetic-pixel-budget")


@pytest.mark.asyncio
async def test_concurrent_cache_misses_decode_once(monkeypatch):
    calls = []

    def normalize(content, *, artifact_id):
        calls.append(content)
        return "data:image/png;base64,YQ=="

    monkeypatch.setattr(images, "_normalize_data_url", normalize)
    cache = images.CodexImageNormalizationCache()
    results = await asyncio.gather(
        *[cache.data_url(b"synthetic", artifact_id="synthetic-concurrent") for _ in range(10)]
    )
    assert len(calls) == 1
    assert len(set(results)) == 1


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_release_native_decode_slot(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    second_started = threading.Event()

    def normalize(content, *, artifact_id):
        if content == b"first":
            started.set()
            assert release.wait(5)
        else:
            second_started.set()
        return b"encoded", "image/png"

    monkeypatch.setattr(images, "_normalize_image", normalize)
    first = asyncio.create_task(
        asyncio.to_thread(images._normalize_data_url, b"first", artifact_id="synthetic-first")
    )
    assert await asyncio.to_thread(started.wait, 2)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(
        asyncio.to_thread(images._normalize_data_url, b"second", artifact_id="synthetic-second")
    )
    try:
        assert not await asyncio.to_thread(second_started.wait, 0.1)
    finally:
        release.set()
    await asyncio.wait_for(second, 2)
    assert second_started.is_set()
