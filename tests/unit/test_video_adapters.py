"""Documented provider wire contracts, tested without billable calls."""

import json

import httpx
import pytest

from cognis.artifacts.ranges import parse_byte_range
from cognis.models.video import VideoOutput, VideoReference, VideoRequest
from cognis.providers.video import (
    VideoConnection,
    VideoHTTPAdapter,
    VideoInput,
    VideoProviderError,
    native_video_capabilities,
    validate_video_combination,
    video_adapter_name,
)


def adapter(client, kind="veo", model="veo-3.1-generate-preview"):
    return VideoHTTPAdapter(
        VideoConnection(
            adapter=kind,
            model=model,
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1"
            if kind == "openrouter"
            else "https://generativelanguage.googleapis.com/v1beta",
        ),
        client,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,field",
    [
        ("first_frame", "image"),
        ("last_frame", "lastFrame"),
        ("reference", "referenceImages"),
    ],
)
async def test_veo_image_native_wire_format(role, field):
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, content=b"image")
        instance = json.loads(request.content)["instances"][0]
        image = instance[field][0]["image"] if field == "referenceImages" else instance[field]
        assert image == {"bytesBase64Encoded": "aW1hZ2U=", "mimeType": "image/png"}
        assert "inlineData" not in image
        return httpx.Response(200, json={"name": "operations/image-render"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await adapter(client).submit(
            VideoRequest(prompt="Animate", max_cost_usd=5),
            [
                VideoInput(
                    role=role, mime_type="image/png", url="https://cognis.test/image", size_bytes=5
                )
            ],
        )


@pytest.mark.asyncio
async def test_veo_text_submit_and_poll():
    def handler(request):
        if request.method == "POST":
            assert request.url.path.endswith(":predictLongRunning")
            body = json.loads(request.content)
            assert body["instances"] == [{"prompt": "Mountain sunrise"}]
            assert body["parameters"]["durationSeconds"] == 8
            return httpx.Response(200, json={"name": "operations/test-render"})
        return httpx.Response(
            200,
            json={
                "name": "operations/test-render",
                "done": True,
                "response": {
                    "generateVideoResponse": {
                        "generatedSamples": [
                            {
                                "video": {
                                    "uri": "https://generativelanguage.googleapis.com/v1beta/files/render:download"
                                }
                            }
                        ]
                    }
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = adapter(client)
        started = await api.submit(VideoRequest(prompt="Mountain sunrise", max_cost_usd=5), [])
        assert started.state == "running"
        completed = await api.poll(started.handle)
        assert completed.state == "completed" and len(completed.outputs) == 1


@pytest.mark.asyncio
async def test_omni_image_serialization_is_independent_of_veo():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, content=b"image")
        body = json.loads(request.content)
        assert body["input"][0] == {"type": "image", "mime_type": "image/png", "data": "aW1hZ2U="}
        return httpx.Response(200, json={"id": "image-interaction", "status": "in_progress"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await adapter(client, "omni", "gemini-omni-1.1-flash").submit(
            VideoRequest(prompt="Animate", max_cost_usd=5),
            [
                VideoInput(
                    role="reference",
                    mime_type="image/png",
                    url="https://cognis.test/image",
                    size_bytes=5,
                )
            ],
        )
        assert result.handle == "image-interaction"


@pytest.mark.asyncio
async def test_openrouter_native_payload_and_cost():
    def handler(request):
        body = json.loads(request.content)
        assert body["frame_images"][0]["frame_type"] == "first_frame"
        assert body["duration"] == 8
        assert "callback_url" not in body
        return httpx.Response(202, json={"id": "test-render", "status": "pending"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = adapter(client, "openrouter", "google/veo-3.1")
        await api.submit(
            VideoRequest(prompt="Animate", max_cost_usd=5, duration=8),
            [
                VideoInput(
                    role="first_frame",
                    url="https://cognis.test/signed.png",
                    mime_type="image/png",
                    size_bytes=10,
                ),
            ],
        )
        result = api._openrouter_result(
            {
                "id": "test-render",
                "status": "completed",
                "usage": {"cost": "0.25"},
                "unsigned_urls": ["https://evil.test/video"],
            }
        )
        assert str(result.cost_usd) == "0.25"
        assert result.outputs[0].locator.startswith("https://openrouter.ai/api/v1/videos/")


@pytest.mark.asyncio
async def test_omni_edit_continuation_and_uri_output():
    def handler(request):
        body = json.loads(request.content)
        assert body["previous_interaction_id"] == "interaction-prior"
        assert body["response_format"]["delivery"] == "uri"
        return httpx.Response(
            200,
            json={
                "id": "interaction-new",
                "status": "completed",
                "steps": [
                    {
                        "type": "model_output",
                        "content": [
                            {
                                "type": "video",
                                "uri": "https://generativelanguage.googleapis.com/v1beta/files/new:download",
                            }
                        ],
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await adapter(client, "omni", "gemini-omni-1.1-flash").submit(
            VideoRequest(
                operation="edit",
                source_artifact_id="source-video",
                prompt="Change the lighting",
                max_cost_usd=5,
            ),
            [
                VideoInput(
                    role="source",
                    url="",
                    mime_type="video/mp4",
                    size_bytes=100,
                    interaction_id="interaction-prior",
                )
            ],
        )
        assert result.state == "completed"


@pytest.mark.parametrize(
    "url",
    [
        "http://generativelanguage.googleapis.com/video",
        "https://generativelanguage.googleapis.com.evil.test/video",
        "https://key@generativelanguage.googleapis.com/video",
        "https://127.0.0.1/video",
        "https://generativelanguage.googleapis.com:444/video",
    ],
)
def test_output_origins_rejected(url):
    with pytest.raises(VideoProviderError):
        adapter(httpx.AsyncClient())._output_url(url)


@pytest.mark.asyncio
async def test_download_rejects_redirect_and_bounds_bytes():
    for response in (
        httpx.Response(302, headers={"location": "http://127.0.0.1/secret"}),
        httpx.Response(200, headers={"content-type": "text/html"}, content=b"error"),
        httpx.Response(200, headers={"content-type": "video/mp4"}, content=b"x" * 11),
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request, response=response: response)
        ) as client:
            with pytest.raises(VideoProviderError):
                _ = [
                    chunk
                    async for chunk in adapter(client).output_stream(
                        VideoOutput(locator="https://generativelanguage.googleapis.com/video"), 10
                    )
                ]


@pytest.mark.parametrize(
    "preset,model",
    [
        ("openai", "sora-2"),
        ("anthropic", "claude"),
        ("ollama", "llama"),
        ("gemini", "gemini-2.5-pro"),
    ],
)
def test_chat_presets_do_not_imply_video_support(preset, model):
    with pytest.raises(ValueError):
        video_adapter_name(preset, model)


def test_no_silent_capability_downgrade():
    with pytest.raises(ValueError, match="audio"):
        native_video_capabilities("veo").validate_request(
            VideoRequest(prompt="Rain", max_cost_usd=5, generate_audio=False)
        )
    with pytest.raises(ValueError, match="require duration"):
        validate_video_combination(
            "veo", VideoRequest(prompt="Rain", max_cost_usd=5, duration=4, resolution="1080p")
        )
    with pytest.raises(ValueError, match="cannot be combined"):
        VideoRequest(
            prompt="Rain",
            max_cost_usd=5,
            references=[
                VideoReference(artifact_id="first", role="first_frame"),
                VideoReference(artifact_id="style", role="reference"),
            ],
        )


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, (0, 99, False)),
        ("bytes=10-19", (10, 19, True)),
        ("bytes=90-", (90, 99, True)),
        ("bytes=-10", (90, 99, True)),
        ("bytes=0-200", (0, 99, True)),
    ],
)
def test_media_ranges(header, expected):
    assert parse_byte_range(header, 100) == expected


@pytest.mark.parametrize(
    "header", ["bytes=100-", "bytes=-0", "bytes=20-10", "bytes=1-2,5-6", "cats=0-1"]
)
def test_bad_media_ranges(header):
    with pytest.raises(ValueError):
        parse_byte_range(header, 100)
