import asyncio
import logging

import pytest

from cognis.core.agent_loop import (
    LLMStreamIdleStats,
    _iterate_llm_stream_with_idle_timeout,
    _llm_stream_chunk_has_reasoning_liveness,
)
from cognis.providers.llm.litellm import _observe_llm_stream_request


@pytest.mark.parametrize("item", [None, {}, {"type": "message"}, {"type": "function_call"}])
def test_non_reasoning_items_do_not_extend_reasoning_deadline(item):
    assert not _llm_stream_chunk_has_reasoning_liveness(
        {"provider_event_type": "response.output_item.done", "responses_output_item": item}
    )


@pytest.mark.asyncio
async def test_completed_private_reasoning_keeps_stream_alive_without_summary():
    async def stream():
        for _ in range(3):
            await asyncio.sleep(0.45)
            yield {
                "provider_event_type": "response.output_item.done",
                "responses_output_item": {"type": "reasoning", "summary": []},
            }
        yield {"choices": [{"delta": {"content": "Done"}}]}

    stats = LLMStreamIdleStats()
    chunks = [
        chunk
        async for chunk in _iterate_llm_stream_with_idle_timeout(
            stream(), idle_timeout_seconds=1, stats=stats
        )
    ]
    assert len(chunks) == 4
    assert stats.reasoning_chunks == 3
    assert stats.meaningful_chunks == 1


@pytest.mark.asyncio
async def test_output_item_diagnostics_do_not_log_content(caplog):
    with caplog.at_level(logging.INFO, logger="cognis.providers.llm.litellm"):
        async with _observe_llm_stream_request(
            provider_id="codex", model="gpt-5.6-sol", llm_api="responses", location="controller"
        ) as observe:
            for item_type in ("reasoning", "message", "function_call", "private-type"):
                observe(
                    {
                        "responses_output_item": {
                            "type": item_type,
                            "encrypted_content": "private-payload",
                        }
                    }
                )
    record = next(r for r in caplog.records if r.message == "LLM stream request completed")
    assert record.extra_data["output_item_type_counts"] == {
        "reasoning": 1,
        "message": 1,
        "function_call": 1,
        "other": 1,
    }
    assert "private-payload" not in str(record.extra_data)
    assert "private-type" not in str(record.extra_data)
