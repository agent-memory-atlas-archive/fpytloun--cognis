"""Real-tokenizer responsiveness under a large, messy history.

Uses the production ``LiteLLMProvider`` token counting (HF tokenizer via
litellm) on a ~150k-token history with interrupted tool batches and orphan
results, and asserts the event loop keeps ticking while assembly and the
within-turn projection run. Outputs must equal an inline (non-offloaded) run.
"""

from __future__ import annotations

import asyncio
import random
import string
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_context_assembler import (  # noqa: E402
    _agent,
    _conversation,
    _Guardrails,
    _Memory,
    _session,
    _SessionCache,
    _SessionManager,
)

from cognis.core import cpu_offload  # noqa: E402
from cognis.core.agent_loop import AgentLoop  # noqa: E402
from cognis.core.context import ContextAssembler  # noqa: E402
from cognis.core.context_projection import ProjectionPolicy, ProjectionTurnState  # noqa: E402
from cognis.models.config import ModelInfo  # noqa: E402
from cognis.providers.llm.litellm import LiteLLMProvider  # noqa: E402

MODEL = "claude-sonnet-5"


class _RealCountingLLM:
    """Real token counting, stubbed model resolution."""

    def __init__(self) -> None:
        self._provider = LiteLLMProvider(object())  # type: ignore[arg-type]

    async def resolve_model(self, explicit_model: str | None = None, task_type: str = "default"):
        del explicit_model, task_type
        return MODEL

    async def get_model_info(self, model_id: str) -> ModelInfo:
        del model_id
        return ModelInfo(model_id=MODEL, context_window=1_000_000, max_output_tokens=128_000)

    def count_tokens(self, text: str, model: str) -> int:
        return self._provider.count_tokens(text, model)

    def count_messages_tokens(self, messages: list[dict[str, Any]], model: str) -> int:
        return self._provider.count_messages_tokens(messages, model)

    def token_estimator_identity(self, model: str) -> str:
        return self._provider.token_estimator_identity(model)


def _history_events(groups: int, words_per_result: int) -> list[dict[str, Any]]:
    rng = random.Random(7)
    vocabulary = [
        "".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 9))) for _ in range(4000)
    ]

    def text(n: int) -> str:
        return " ".join(rng.choice(vocabulary) for _ in range(n))

    events: list[dict[str, Any]] = []
    for group in range(groups):
        turn = f"turn_{group // 6}"
        if group % 6 == 0:
            # Long, non-prunable chat turns are what keeps a real session large.
            events.append(
                {"type": "user_message", "data": {"content": text(2500), "turn_id": turn}}
            )
            events.append(
                {"type": "assistant_message", "data": {"content": text(2000), "turn_id": turn}}
            )
        call_id = f"call_{group}"
        events.append(
            {
                "type": "tool_call",
                "data": {
                    "call_id": call_id,
                    "name": "shell",
                    "arguments": {"cmd": text(12)},
                    "turn_id": turn,
                },
            }
        )
        if group % 17 == 5:
            # Interrupted batch: the call never produced a result.
            continue
        events.append(
            {
                "type": "tool_result",
                "data": {
                    "call_id": call_id,
                    "name": "shell",
                    "content": text(words_per_result),
                    "turn_id": turn,
                },
            }
        )
        if group % 23 == 11:
            # Orphan result whose call was lost.
            events.append(
                {
                    "type": "tool_result",
                    "data": {
                        "call_id": f"orphan_{group}",
                        "name": "shell",
                        "content": text(40),
                        "turn_id": turn,
                    },
                }
            )
    events.append({"type": "user_message", "data": {"content": "and now?", "turn_id": "turn_last"}})
    for index, event in enumerate(events, start=1):
        event["seq"] = index
    return events


async def _tick(stop: asyncio.Event, gaps: list[float]) -> None:
    last = time.perf_counter()
    while not stop.is_set():
        await asyncio.sleep(0.005)
        now = time.perf_counter()
        gaps.append(now - last)
        last = now


def _assembler(cache: _SessionCache) -> ContextAssembler:
    return ContextAssembler(
        memory=_Memory(),
        guardrails=_Guardrails(),
        llm=_RealCountingLLM(),
        session_cache=cache,
        session_manager=_SessionManager(),
        max_context_tokens=1_000_000,
        compaction_threshold=0.85,
    )


@pytest.mark.asyncio
async def test_large_history_assembly_and_projection_keep_the_loop_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _SessionCache()
    cache.history_events = _history_events(groups=220, words_per_result=450)

    # Inline baseline: run the same work without offloading.
    async def _inline(fn, /, *args, **kwargs):  # noqa: ANN001
        return fn(*args, **kwargs)

    monkeypatch.setattr("cognis.core.context.run_cpu_bound", _inline)
    monkeypatch.setattr("cognis.core.agent_loop.run_cpu_bound", _inline)
    baseline_assembler = _assembler(cache)
    baseline = await baseline_assembler.assemble(
        session=_session(),
        conversation=_conversation(),
        agent=_agent(),
        user_message="and now?",
        tool_definitions=[],
    )
    assert baseline.prompt_tokens > 100_000, baseline.prompt_tokens
    monkeypatch.undo()
    cpu_offload._STATES.clear()

    gaps: list[float] = []
    stop = asyncio.Event()
    ticker = asyncio.create_task(_tick(stop, gaps))
    try:
        assembler = _assembler(cache)
        result = await assembler.assemble(
            session=_session(),
            conversation=_conversation(),
            agent=_agent(),
            user_message="and now?",
            tool_definitions=[],
        )

        loop = object.__new__(AgentLoop)
        loop.providers = SimpleNamespace(llm=_RealCountingLLM())
        ctx = SimpleNamespace(
            current_model=MODEL,
            current_model_info=SimpleNamespace(max_input_tokens=1_000_000, max_output_tokens=0),
            agent=SimpleNamespace(llm_config=None),
            turn_id="turn-1",
            session=_session(),
            cancel_event=None,
            execution_fence=None,
            last_projection_snapshot=None,
            projection_state=ProjectionTurnState(
                turn_id="turn-1",
                policy=ProjectionPolicy.from_budget(
                    max_context_tokens=1_000_000,
                    available_prompt_tokens=800_000,
                    phase="within_turn",
                    pressure_mode="normal",
                ),
            ),
        )
        projected = await loop._project_model_messages_for_budget_offloaded(
            ctx,
            messages=[dict(message) for message in result.messages],
            tool_schemas=[],
            resolved_model=MODEL,
            max_context_tokens=1_000_000,
        )
    finally:
        stop.set()
        await ticker

    def _strip_ts(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        import re

        return [
            {
                key: (re.sub(r'ts="[^"]*"', 'ts=""', value) if isinstance(value, str) else value)
                for key, value in message.items()
            }
            for message in messages
        ]

    assert _strip_ts(result.messages) == _strip_ts(baseline.messages)
    assert result.prompt_tokens == baseline.prompt_tokens
    assert projected.messages, "projection produced no messages"
    assert max(gaps) < 0.25, f"event loop stalled for {max(gaps):.3f}s"


@pytest.mark.asyncio
async def test_large_history_inline_baseline_actually_blocks_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard against a vacuous responsiveness test: inline counting must stall."""

    cache = _SessionCache()
    cache.history_events = _history_events(groups=220, words_per_result=450)

    async def _inline(fn, /, *args, **kwargs):  # noqa: ANN001
        return fn(*args, **kwargs)

    monkeypatch.setattr("cognis.core.context.run_cpu_bound", _inline)
    gaps: list[float] = []
    stop = asyncio.Event()
    ticker = asyncio.create_task(_tick(stop, gaps))
    try:
        await _assembler(cache).assemble(
            session=_session(),
            conversation=_conversation(),
            agent=_agent(),
            user_message="and now?",
            tool_definitions=[],
        )
    finally:
        stop.set()
        await ticker
    assert max(gaps) > 0.1, f"fixture too small to stall the loop inline ({max(gaps):.3f}s)"
