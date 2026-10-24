"""Shared stream liveness watchdog for agents and proxy inference."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import monotonic
from typing import Any

from cognis.providers.llm.errors import LLMStreamIdleTimeout


def has_activity(chunk: dict[str, Any]) -> bool:
    if any(chunk.get(key) for key in ("mid_stream_failure", "error", "done", "usage")):
        return True
    if any(
        choice.get("finish_reason")
        or value_has_activity(choice.get("delta"))
        or value_has_activity(choice.get("message"))
        for choice in chunk.get("choices") or []
        if isinstance(choice, dict)
    ):
        return True
    return any(
        value_has_activity(chunk.get(key))
        for key in (
            "content",
            "reasoning_content",
            "provider_thinking_blocks",
            "thinking_blocks",
            "tool_calls",
            "function_call",
        )
    )


def value_has_activity(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, list):
        return any(value_has_activity(item) for item in value)
    if isinstance(value, dict):
        return (
            "tool_calls" in value
            or "function_call" in value
            or any(
                value_has_activity(value.get(key))
                for key in (
                    "content",
                    "reasoning_content",
                    "arguments",
                    "name",
                    "id",
                    "text",
                    "delta",
                    "refusal",
                )
            )
        )
    return False


def has_provider_liveness(chunk: dict[str, Any]) -> bool:
    return bool(
        has_activity(chunk)
        or chunk.get("provider_event")
        or chunk.get("provider_event_type")
        or isinstance(chunk.get("choices"), list)
    )


def has_reasoning_liveness(chunk: dict[str, Any]) -> bool:
    event = chunk.get("provider_event_type", "")
    item = chunk.get("responses_output_item")
    if (
        event == "response.output_item.done"
        and isinstance(item, dict)
        and item.get("type") == "reasoning"
    ):
        return True
    if event in {
        "response.reasoning_text.delta",
        "response.reasoning_text.done",
        "response.reasoning_summary_text.delta",
        "response.reasoning_summary_text.done",
        "response.reasoning_summary_part.added",
        "response.reasoning_summary_part.done",
    }:
        return True
    return any(
        isinstance(choice, dict)
        and isinstance(choice.get("delta"), dict)
        and any(
            key in choice["delta"]
            for key in ("reasoning", "reasoning_content", "reasoning_part_boundary")
        )
        for choice in chunk.get("choices") or []
    )


@dataclass(slots=True)
class LLMStreamIdleStats:
    raw_chunks: int = 0
    meaningful_chunks: int = 0
    reasoning_chunks: int = 0
    first_raw_after_seconds: float | None = None
    first_activity_after_seconds: float | None = None
    first_reasoning_after_seconds: float | None = None
    last_raw_after_seconds: float | None = None
    last_activity_after_seconds: float | None = None
    last_reasoning_after_seconds: float | None = None

    @property
    def timeout_phase(self) -> str:
        if not self.raw_chunks:
            return "raw"
        return "reasoning" if self.reasoning_chunks and not self.meaningful_chunks else "activity"

    def as_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return {
            key: round(value, 2) if isinstance(value, float) else value
            for key, value in asdict(self).items()
        }


async def iterate_stream(
    stream: AsyncIterator[dict[str, Any]],
    *,
    idle_timeout_seconds: int,
    stats: LLMStreamIdleStats | None = None,
    cancel_event: asyncio.Event | None = None,
    monitor_idle: bool = True,
) -> AsyncIterator[dict[str, Any]]:
    """Heartbeats maintain raw liveness, not the meaningful-output deadline."""
    timeout = max(1, idle_timeout_seconds)
    reasoning_timeout = max(timeout, min(timeout * 3, 900))
    started = monotonic()
    raw_deadline = activity_deadline = started + timeout
    stats = stats or LLMStreamIdleStats()
    iterator = aiter(stream)
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError
            remaining = (
                min(raw_deadline, activity_deadline) - monotonic() if monitor_idle else float("inf")
            )
            if remaining <= 0:
                raise LLMStreamIdleTimeout(
                    timeout_message(stats, timeout, reasoning_timeout),
                    payload={"category": f"idle_timeout_{stats.timeout_phase}"},
                )
            next_chunk = asyncio.ensure_future(anext(iterator))
            cancellation = asyncio.create_task(cancel_event.wait()) if cancel_event else None
            pending = {next_chunk} | ({cancellation} if cancellation else set())
            try:
                done, _ = await asyncio.wait(
                    pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
                )
                if cancellation and cancellation in done and cancellation.result():
                    raise asyncio.CancelledError
                if next_chunk not in done:
                    raise LLMStreamIdleTimeout(
                        timeout_message(stats, timeout, reasoning_timeout),
                        payload={"category": f"idle_timeout_{stats.timeout_phase}"},
                    )
                try:
                    chunk = next_chunk.result()
                except StopAsyncIteration:
                    return
            finally:
                for task in pending:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            now = monotonic()
            elapsed = now - started
            if has_provider_liveness(chunk):
                stats.raw_chunks += 1
                stats.first_raw_after_seconds = stats.first_raw_after_seconds or elapsed
                stats.last_raw_after_seconds = elapsed
                raw_deadline = now + timeout
            if has_reasoning_liveness(chunk):
                stats.reasoning_chunks += 1
                stats.first_reasoning_after_seconds = stats.first_reasoning_after_seconds or elapsed
                stats.last_reasoning_after_seconds = elapsed
                if not stats.meaningful_chunks:
                    activity_deadline = now + reasoning_timeout
            if has_activity(chunk):
                stats.meaningful_chunks += 1
                stats.first_activity_after_seconds = stats.first_activity_after_seconds or elapsed
                stats.last_activity_after_seconds = elapsed
                activity_deadline = now + timeout
            yield chunk
    finally:
        closer = getattr(iterator, "aclose", None)
        if closer is not None:
            await closer()


def timeout_message(stats: LLMStreamIdleStats, timeout: float, reasoning_timeout: float) -> str:
    if stats.timeout_phase == "raw":
        return f"LLM stream produced no provider events for {timeout}s"
    if stats.timeout_phase == "reasoning":
        return (
            "LLM stream produced provider reasoning events but no meaningful output "
            f"for {reasoning_timeout}s"
        )
    return f"LLM stream produced no meaningful activity for {timeout}s"
