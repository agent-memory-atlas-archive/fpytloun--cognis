from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from cognis.core.context import ContextAssembler
from cognis.core.project_context import (
    ProjectContextEntry,
    project_context_event_data,
)
from cognis.core.session_cache import SessionCache
from cognis.models.session import EventAppendResult, EventReadResult, SessionEvent
from cognis.providers.llm.message_projection import project_messages_for_provider
from cognis.providers.llm.responses_bridge import messages_to_responses_input
from tests.unit.test_context_assembler import (
    _LLM,
    _agent,
    _conversation,
    _Guardrails,
    _Memory,
    _session,
    _SessionManager,
)


class DurableGuardrails(_Guardrails):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    async def read_events(self, *, after_seq: int = 0, **kwargs: object) -> EventReadResult:
        return EventReadResult(
            events=deepcopy([e for e in self.events if e["seq"] > after_seq]),
            last_seq=len(self.events),
            has_more=False,
        )

    async def record_events(self, **kwargs: object) -> EventAppendResult:
        first = len(self.events) + 1
        for event in kwargs["events"]:
            self.events.append(
                {"seq": len(self.events) + 1, "type": event.type, "data": deepcopy(event.data)}
            )
        return EventAppendResult(
            ok=True,
            first_seq=first,
            last_seq=len(self.events),
            count=len(self.events) - first + 1,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("skip_memory", [True, False])
@pytest.mark.parametrize("provider", ["responses", "anthropic"])
async def test_preamble_prefix_extension_and_cold_replay(
    skip_memory: bool,
    provider: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guardrails = DurableGuardrails()
    cache = SessionCache(guardrails)
    session = _session()
    revision = 1

    async def policy(*args: object) -> dict:
        return {"role": "system", "content": f"Policy revision {revision}"}

    monkeypatch.setattr("cognis.core.current_policy_context.current_policy_message", policy)
    monkeypatch.setattr(
        "cognis.core.context.render_agent_profile_context",
        lambda *args, **kwargs: f"Runtime profile revision {revision}",
    )

    def assembler(active_cache: SessionCache) -> ContextAssembler:
        return ContextAssembler(
            memory=_Memory(),
            guardrails=guardrails,
            llm=_LLM(),
            session_cache=active_cache,
            session_manager=_SessionManager(),
            compaction_threshold=0.85,
        )

    async def append(kind: str, data: dict) -> None:
        if kind == "user_message":
            data["message_metadata"] = {"ts": "2026-01-01T00:00:00Z"}
        events = [SessionEvent(type=kind, data=data)]
        result = await guardrails.record_events(events=events)
        await cache.append_recorded_events(session, events, result)

    await cache.refresh(session)
    await append("user_message", {"content": "First request", "turn_id": "first"})
    kwargs = dict(
        session=session,
        conversation=_conversation(),
        agent=_agent(),
        user_message="First request",
        skip_memory=skip_memory,
        required_turn_id="first",
        require_user_event=True,
        user_message_metadata={"ts": "2026-01-01T00:00:00Z"},
    )
    first = await assembler(cache).assemble(**kwargs)
    for item in first.audit_messages:
        metadata = item.get("metadata", {})
        if metadata.get("replayable"):
            await append(
                "developer_message",
                {
                    "content": item["content"],
                    "source": item["source"],
                    **metadata,
                },
            )
    # Actual mid-turn exposure is recorded after the tool batch, separately
    # from project discovery. Compare the last request, not its completion.
    from cognis.core.tool_result_context import project_context_exposure

    notice, audit = project_context_exposure(
        {"role": "system", "content": "Project instructions loaded mid-turn"}
    )
    await append(
        "developer_message",
        project_context_event_data(
            ProjectContextEntry(
                project_root="/repo",
                source_path="/repo/AGENTS.md",
                content=notice["content"],
            ),
            turn_id="first",
        ),
    )
    await append(
        "developer_message",
        {
            "source": audit["source"],
            "content": notice["content"],
            **audit["metadata"],
        },
    )
    last_messages = [*first.messages, notice]
    await append("assistant_message", {"content": "Done"})
    await append("user_message", {"content": "Second request", "turn_id": "second"})
    revision = 2
    kwargs.update(
        user_message="Second request",
        required_turn_id="second",
        workspace_root="/repo",
        effective_working_directory="/repo/src",
    )
    second = await assembler(cache).assemble(**kwargs)

    def payload(messages: list[dict]) -> object:
        if provider == "responses":
            return messages_to_responses_input(messages)
        return project_messages_for_provider(
            messages,
            provider=SimpleNamespace(config={"preset": "anthropic"}),
            llm_api="chat_completions",
        ).messages

    old = payload(last_messages)
    new = payload(second.messages)
    assert new[: len(old)] == old
    update_index = next(
        i
        for i, m in enumerate(second.messages)
        if str(m.get("content", "")).startswith("Context update:")
    )
    assert "Second request" in str(second.messages[update_index + 1]["content"])
    cold_cache = SessionCache(guardrails)
    cold = await assembler(cold_cache).assemble(**kwargs)
    assert payload(cold.messages) == new
    assert len([e for e in guardrails.events if e["data"].get("event") == "context_preamble"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("cold", [False, True])
async def test_recovered_policy_supersedes_mid_turn_unknown(cold: bool) -> None:
    from cognis.core.current_policy_context import current_policy_message

    guardrails = DurableGuardrails()
    cache = SessionCache(guardrails)
    session = _session()
    assembler = ContextAssembler(
        memory=_Memory(),
        guardrails=guardrails,
        llm=_LLM(),
        session_cache=cache,
        session_manager=_SessionManager(),
        compaction_threshold=0.85,
    )
    await cache.refresh(session)
    policy = await current_policy_message(guardrails, session)
    # Both messages retain the real policy envelope/provenance guidance.
    policy["content"] = policy["content"].replace('"revision": "unknown"', '"revision": 7')
    snapshot = await cache.acquire_context_snapshot(session)
    await assembler._freeze_preamble(
        session,
        _agent(),
        [policy],
        snapshot,
        turn_id="first",
        before_user=True,
    )
    events = [
        SessionEvent(
            type="developer_message",
            data={
                "source": "current_policy_update",
                "content": (await current_policy_message(guardrails, session))["content"],
                "context_injection": True,
                "replayable": True,
                "visibility": "agent_context",
                "model_role": "system",
            },
        )
    ]
    result = await guardrails.record_events(events=events)
    await cache.append_recorded_events(session, events, result)
    if cold:
        cache = SessionCache(guardrails)
        assembler.session_cache = cache
    snapshot = await cache.acquire_context_snapshot(session)
    _, updated = await assembler._freeze_preamble(
        session,
        _agent(),
        [policy],
        snapshot,
        turn_id="second",
        before_user=True,
    )
    assert len(updated.preamble_events()) == 2
    assert '"revision": 7' in updated.preamble_events()[-1].data["content"]


@pytest.mark.asyncio
async def test_preamble_cancellation_reconciles_and_preview_never_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guardrails = DurableGuardrails()
    cache = SessionCache(guardrails)
    session = _session()
    assembler = ContextAssembler(
        memory=_Memory(),
        guardrails=guardrails,
        llm=_LLM(),
        session_cache=cache,
        session_manager=_SessionManager(),
        compaction_threshold=0.85,
    )
    await cache.refresh(session)
    snapshot = await cache.acquire_context_snapshot(session)
    blocks = [{"role": "system", "content": "Environment: first"}]
    await assembler._freeze_preamble(
        session,
        _agent(),
        blocks,
        snapshot,
        turn_id="first",
        before_user=True,
        read_only=True,
    )
    assert not guardrails.events
    original_record = guardrails.record_events

    async def interrupted(**kwargs: object) -> EventAppendResult:
        await original_record(**kwargs)
        raise asyncio.CancelledError

    monkeypatch.setattr(guardrails, "record_events", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await assembler._freeze_preamble(
            session,
            _agent(),
            blocks,
            snapshot,
            turn_id="first",
            before_user=True,
        )
    monkeypatch.setattr(guardrails, "record_events", original_record)
    snapshot = await cache.acquire_context_snapshot(session)
    frozen, snapshot = await assembler._freeze_preamble(
        session,
        _agent(),
        blocks,
        snapshot,
        turn_id="first",
        before_user=True,
    )
    assert len(guardrails.events) == 1
    assert frozen[0]["content"] == blocks[0]["content"]
    changed = [{"role": "system", "content": "Environment: second"}]
    preview, _ = await assembler._freeze_preamble(
        session,
        _agent(),
        changed,
        snapshot,
        turn_id="second",
        before_user=True,
        read_only=True,
    )
    assert preview == frozen
    assert len(guardrails.events) == 1
