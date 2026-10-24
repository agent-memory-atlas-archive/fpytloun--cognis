"""Portable native video HTTP adapters with no automatic paid-call retries."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import Field

from cognis.models.video import (
    VideoCapabilities,
    VideoContract,
    VideoOutput,
    VideoRemoteResult,
    VideoRequest,
)


class VideoProviderError(Exception):
    """Sanitized provider error: raw bodies and credential-bearing URLs stay private."""

    def __init__(self, code: str, *, rejected: bool = False, retry_after: int = 30):
        super().__init__(code)
        self.code = code
        self.rejected = rejected
        self.retry_after = retry_after


class VideoInput(VideoContract):
    role: str
    url: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    # Only supplied by the controller from a prior job's persisted output binding.
    provider_locator: str | None = None
    interaction_id: str | None = None


class VideoConnection(VideoContract):
    adapter: str
    model: str
    api_key: str = Field(repr=False)
    base_url: str


def video_adapter_name(preset: str, model: str) -> str:
    """Select only documented native transports, not chat-compatible guesses."""
    if preset == "openrouter":
        return "openrouter"
    if preset == "gemini":
        if model in {"veo-3.1-generate-preview", "veo-3.1-fast-generate-preview"}:
            return "veo"
        if model == "gemini-omni-1.1-flash":
            return "omni"
    raise ValueError("No certified video transport for this provider/model")


def native_video_capabilities(adapter: str) -> VideoCapabilities:
    """Known executable controls; live account/model metadata may further restrict."""
    if adapter == "veo":
        return VideoCapabilities(
            operations=["generate", "extend"],
            input_roles=["first_frame", "last_frame", "reference"],
            durations=[4, 6, 8],
            resolutions=["720p", "1080p", "4k"],
            aspect_ratios=["16:9", "9:16"],
            max_references=3,
            seed=True,
            negative_prompt=True,
            person_generation=True,
            source_policy="same_provider_output",
            extension_output="combined",
            notes=[
                "Native audio is always generated.",
                "Extension requires a retained Veo output.",
            ],
        )
    if adapter == "omni":
        return VideoCapabilities(
            operations=["generate", "edit", "extend"],
            input_roles=["reference"],
            resolutions=["360p", "720p", "1080p", "4k"],
            aspect_ratios=["16:9", "9:16"],
            max_references=3,
            source_policy="same_provider_output",
            notes=[
                "Edits/extensions use stored interactions from this account.",
                "Uploaded-video editing is region-restricted and is not enabled.",
                "Duration and audio are prompt-controlled, not guaranteed numeric controls.",
            ],
        )
    return VideoCapabilities()


def validate_video_combination(adapter: str, request: VideoRequest) -> None:
    """Validate coupled controls beyond independent capability fields."""
    if adapter == "veo":
        duration = request.duration or 8
        if (
            request.operation == "extend"
            or any(ref.role == "reference" for ref in request.references)
            or request.resolution in {"1080p", "4k"}
        ) and duration != 8:
            raise ValueError("Veo references, extension and high resolution require duration=8")
        if request.operation == "extend" and (
            request.resolution not in {None, "720p"} or request.references
        ):
            raise ValueError("Veo extension requires 720p and no image references")


class VideoHTTPAdapter:
    """Small HTTP-only adapter usable on controller or executor.

    Never retries POST. The caller persists dispatch intent before calling submit.
    Input URLs are controller-issued exact-artifact transfer URLs, not user inputs.
    """

    def __init__(self, connection: VideoConnection, client: httpx.AsyncClient):
        self.connection = connection
        self.client = client
        self.base = connection.base_url.rstrip("/")
        expected = (
            "https://openrouter.ai/api/v1"
            if connection.adapter == "openrouter"
            else "https://generativelanguage.googleapis.com/v1beta"
        )
        if self.base != expected:
            raise ValueError("Native video adapters require their canonical provider endpoint")
        self.headers = (
            {"Authorization": f"Bearer {connection.api_key}"}
            if connection.adapter == "openrouter"
            else {"x-goog-api-key": connection.api_key}
        )

    async def _json(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        async with self.client.stream(
            method,
            f"{self.base}/{path}",
            headers=self.headers,
            json=payload,
            timeout=httpx.Timeout(600, connect=15),
            follow_redirects=False,
        ) as response:
            if response.status_code >= 300:
                retry = response.headers.get("retry-after", "30")
                raise VideoProviderError(
                    f"provider_http_{response.status_code}",
                    rejected=400 <= response.status_code < 500 and response.status_code != 408,
                    retry_after=min(3600, int(retry)) if retry.isdigit() else 30,
                )
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 4 * 1024 * 1024:
                    raise VideoProviderError("provider_response_too_large")
            try:
                result = json.loads(content)
            except (ValueError, UnicodeError) as exc:
                raise VideoProviderError("malformed_provider_response") from exc
            if not isinstance(result, dict):
                raise VideoProviderError("malformed_provider_response")
            return result

    async def capabilities(self) -> VideoCapabilities:
        """Read the live OpenRouter catalog or the native adapter contract."""
        if self.connection.adapter != "openrouter":
            return native_video_capabilities(self.connection.adapter)
        data = await self._json("GET", "videos/models")
        row = next((r for r in data.get("data", []) if r.get("id") == self.connection.model), None)
        if row is None:
            raise ValueError("Video model is not available in the provider catalog")
        parameters = set(row.get("supported_parameters") or [])
        return VideoCapabilities(
            operations=["generate"],
            durations=row.get("supported_durations") or [],
            resolutions=row.get("supported_resolutions") or [],
            aspect_ratios=row.get("supported_aspect_ratios") or [],
            input_roles=(
                (["first_frame", "last_frame"] if "frame_images" in parameters else [])
                + (["reference"] if "input_references" in parameters else [])
            ),
            max_references=3
            if "input_references" in parameters
            else 2
            if "frame_images" in parameters
            else 0,
            audio="generate_audio" in parameters,
            seed="seed" in parameters,
            notes=["Account/model restrictions may further limit image and audio conditioning."],
        )

    async def _image(self, source: VideoInput) -> dict[str, Any]:
        if source.size_bytes > 8 * 1024 * 1024:
            raise ValueError("Veo reference images must be at most 8 MiB")
        content = bytearray()
        async with self.client.stream("GET", source.url, follow_redirects=False) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 8 * 1024 * 1024:
                    raise ValueError("Reference image exceeds its transfer limit")
        return {
            "mimeType": source.mime_type,
            "bytesBase64Encoded": base64.b64encode(content).decode(),
        }

    async def submit(self, request: VideoRequest, inputs: list[VideoInput]) -> VideoRemoteResult:
        """Submit exactly once; ambiguity must be settled by the caller."""
        validate_video_combination(self.connection.adapter, request)
        if self.connection.adapter == "openrouter":
            payload: dict[str, Any] = {"model": self.connection.model, "prompt": request.prompt}
            for name in ("duration", "resolution", "aspect_ratio", "generate_audio", "seed"):
                if (value := getattr(request, name)) is not None:
                    payload[name] = value
            frames, references = [], []
            for source in inputs:
                image = {"type": "image_url", "image_url": {"url": source.url}}
                if source.role in {"first_frame", "last_frame"}:
                    frames.append({**image, "frame_type": source.role})
                else:
                    references.append(image)
            if frames:
                payload["frame_images"] = frames
            if references:
                payload["input_references"] = references
            data = await self._json("POST", "videos", payload)
            return self._openrouter_result(data)
        if self.connection.adapter == "veo":
            instance: dict[str, Any] = {"prompt": request.prompt}
            references = []
            for source in inputs:
                if source.role == "source":
                    if not source.provider_locator:
                        raise ValueError("Veo extension requires a retained provider output")
                    self._output_url(source.provider_locator)
                    instance["video"] = {"uri": source.provider_locator}
                elif source.role == "reference":
                    references.append(
                        {"image": await self._image(source), "referenceType": "asset"}
                    )
                else:
                    instance[
                        "image" if source.role == "first_frame" else "lastFrame"
                    ] = await self._image(source)
            if references:
                instance["referenceImages"] = references
            parameters: dict[str, Any] = {"durationSeconds": request.duration or 8}
            for name, target in (
                ("resolution", "resolution"),
                ("aspect_ratio", "aspectRatio"),
                ("seed", "seed"),
                ("negative_prompt", "negativePrompt"),
                ("person_generation", "personGeneration"),
            ):
                if (value := getattr(request, name)) is not None:
                    parameters[target] = value
            data = await self._json(
                "POST",
                f"models/{quote(self.connection.model, safe='')}:predictLongRunning",
                {"instances": [instance], "parameters": parameters},
            )
            return self._veo_result(data)
        payload = {
            "model": self.connection.model,
            "input": request.prompt,
            "store": True,
            "stream": False,
            "response_format": {"type": "video", "delivery": "uri"},
        }
        response_format = payload["response_format"]
        for name in ("resolution", "aspect_ratio"):
            if (value := getattr(request, name)) is not None:
                response_format[name] = value
        parts: list[dict[str, Any]] = []
        for source in inputs:
            if source.role == "source":
                if not source.interaction_id:
                    raise ValueError("Omni edits require a stored same-account interaction")
                payload["previous_interaction_id"] = source.interaction_id
            else:
                image = await self._image(source)
                parts.append(
                    {
                        "type": "image",
                        "mime_type": source.mime_type,
                        "data": image["bytesBase64Encoded"],
                    }
                )
        prompt = request.prompt
        if request.operation == "extend":
            prompt = f"Extend this video at its end. {prompt}"
        payload["input"] = [*parts, {"type": "text", "text": prompt}] if parts else prompt
        return self._omni_result(await self._json("POST", "interactions", payload))

    async def poll(self, handle: str) -> VideoRemoteResult:
        """Read a previously bound remote operation; never resubmit."""
        if self.connection.adapter == "openrouter":
            return self._openrouter_result(
                await self._json("GET", f"videos/{quote(handle, safe='')}")
            )
        if self.connection.adapter == "veo":
            if not re.fullmatch(r"(?:models/[\w.-]+/)?operations/[\w.-]+", handle):
                raise VideoProviderError("invalid_operation_handle")
            return self._veo_result(await self._json("GET", handle))
        return self._omni_result(await self._json("GET", f"interactions/{quote(handle, safe='')}"))

    def _openrouter_result(self, data: dict[str, Any]) -> VideoRemoteResult:
        handle = data.get("id")
        if not isinstance(handle, str) or not handle:
            raise VideoProviderError("missing_remote_handle")
        status = data.get("status")
        state = {"completed": "completed", "failed": "failed", "cancelled": "cancelled"}.get(
            status if isinstance(status, str) else "", "running"
        )
        outputs = []
        if state == "completed":
            # Construct authenticated URLs; never follow a callback-provided locator.
            count = len(data.get("unsigned_urls") or data.get("urls") or [0])
            if count > 4:
                raise VideoProviderError("unexpected_output_count")
            outputs = [
                VideoOutput(
                    locator=f"{self.base}/videos/{quote(handle, safe='')}/content?index={i}"
                )
                for i in range(count)
            ]
        cost = (data.get("usage") or {}).get("cost")
        return VideoRemoteResult(
            handle=handle,
            state=state,
            outputs=outputs,
            cost_usd=cost,
            error_code="provider_rejected" if state == "failed" else None,
        )

    def _veo_result(self, data: dict[str, Any]) -> VideoRemoteResult:
        handle = data.get("name")
        if not isinstance(handle, str) or not handle:
            raise VideoProviderError("missing_remote_handle")
        if data.get("error"):
            return VideoRemoteResult(handle=handle, state="failed", error_code="provider_rejected")
        if not data.get("done"):
            return VideoRemoteResult(handle=handle, state="running")
        samples = ((data.get("response") or {}).get("generateVideoResponse") or {}).get(
            "generatedSamples", []
        )
        outputs = [VideoOutput(locator=self._output_url(s["video"]["uri"])) for s in samples]
        return VideoRemoteResult(
            handle=handle,
            state="completed" if outputs else "failed",
            outputs=outputs,
            error_code=None if outputs else "provider_filtered_output",
        )

    def _omni_result(self, data: dict[str, Any]) -> VideoRemoteResult:
        handle = data.get("id")
        if not isinstance(handle, str) or not handle:
            raise VideoProviderError("missing_remote_handle")
        outputs = []
        for step in data.get("steps", []):
            if step.get("type") != "model_output":
                continue
            for part in step.get("content", []):
                if part.get("type") == "video" and part.get("uri"):
                    outputs.append(VideoOutput(locator=self._output_url(part["uri"])))
        status = data.get("status")
        if status == "completed" and not outputs:
            raise VideoProviderError("missing_uri_video_output")
        return VideoRemoteResult(
            handle=handle,
            state="completed" if outputs else ("failed" if status == "failed" else "running"),
            outputs=outputs,
            error_code="provider_rejected" if status == "failed" else None,
        )

    def _output_url(self, locator: str) -> str:
        parsed = urlsplit(locator)
        base = urlsplit(self.base)
        if (
            parsed.scheme != "https"
            or parsed.hostname != base.hostname
            or parsed.port not in {None, 443}
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise VideoProviderError("unsafe_output_origin")
        return locator

    async def output_stream(self, output: VideoOutput, max_bytes: int) -> AsyncIterator[bytes]:
        """Stream bytes with bounded size; do not forward credentials through redirects."""
        locator = self._output_url(output.locator)
        async with self.client.stream(
            "GET", locator, headers=self.headers, follow_redirects=False, timeout=120
        ) as response:
            if response.status_code != 200:
                raise VideoProviderError(f"output_http_{response.status_code}")
            content_type = response.headers.get("content-type", "").split(";")[0]
            if content_type not in {"video/mp4", "video/webm", "application/octet-stream"}:
                raise VideoProviderError("unexpected_output_type")
            total = 0
            async for chunk in response.aiter_bytes(256 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise VideoProviderError("output_too_large")
                yield chunk
            if not total:
                raise VideoProviderError("empty_video_output")
