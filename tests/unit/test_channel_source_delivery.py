import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cognis.channels.inbound import ChannelTurnObserver
from cognis.channels.source_delivery import pending_sources, progress_delivery_id, record_state
from cognis.core.turn_scheduler import TurnError, TurnScheduler
from cognis.models.channel import ChannelDeliveryDescriptor


class Stream:
    def __init__(self):
        self.events = []

    def add(self, kind, **data):
        self.events.append({"type": kind, "seq": len(self.events) + 1, "data": data})

    async def record_events(self, *, session_id, events, source):
        for event in events:
            self.add(event.type, **event.data)
        return SimpleNamespace(ok=True, count=len(events))

    async def read_events(self, **kwargs):
        return SimpleNamespace(events=self.events, has_more=False)


@pytest.mark.asyncio
async def test_multiple_successors_retain_unsent_and_exclude_intended_ranges():
    stream = Stream()
    for turn, parent in (("first", None), ("second", "first"), ("third", "second")):
        await record_state(stream, "session", state="tracking", turn_id=turn)
        if parent:
            stream.add(
                "system_message",
                event="turn_initiated",
                origin_kind="continuation",
                turn_id=turn,
                source_id=parent,
            )
        stream.add(
            "assistant_message",
            turn_id=turn,
            content=turn,
            assistant_phase_index=0,
            turn_cycle_index=1,
        )
        if turn == "first":
            content, refs = await pending_sources(stream, ["session"], turn)
            assert content == "first"
            await record_state(stream, "session", state="intended", turn_id=turn, sources=refs)
    stream.add("assistant_message", turn_id="third", content="aborted", partial=True)
    content, refs = await pending_sources(stream, ["session"], "third")
    assert content == "second\n\nthird"
    assert [ref["turn_id"] for ref in refs] == ["second", "third"]
    assert all(ref["seq"] > 0 and ref["start"] == 0 for ref in refs)


@pytest.mark.asyncio
async def test_legacy_untracked_content_is_not_replayed():
    stream = Stream()
    stream.add("assistant_message", turn_id="legacy", content="possibly sent")
    with pytest.raises(RuntimeError, match="tracking marker"):
        await pending_sources(stream, ["session"], "legacy")
    await record_state(stream, "session", state="tracking", turn_id="current")
    stream.add(
        "system_message",
        event="turn_initiated",
        origin_kind="continuation",
        turn_id="current",
        source_id="legacy",
    )
    assert await pending_sources(stream, ["session"], "current") == ("", [])


@pytest.mark.asyncio
async def test_distinct_cycles_survive_terminal_attachment_snapshot():
    stream = Stream()
    await record_state(stream, "session", state="tracking", turn_id="turn")
    for cycle, content in ((1, "earlier"), (2, "later"), (2, "later")):
        stream.add(
            "assistant_message",
            turn_id="turn",
            content=content,
            assistant_phase_index=0,
            turn_cycle_index=cycle,
        )
    content, refs = await pending_sources(stream, ["session"], "turn")
    assert content == "earlier\n\nlater"
    assert len(refs) == 2


@pytest.mark.asyncio
async def test_reference_append_requires_explicit_acknowledgement():
    guardrails = SimpleNamespace(record_events=AsyncMock(return_value=SimpleNamespace(ok=False)))
    with pytest.raises(RuntimeError, match="not confirmed"):
        await record_state(guardrails, "session", state="tracking", turn_id="turn")


@pytest.mark.asyncio
async def test_tracking_retry_after_failed_append_and_duplicate_markers():
    stream = Stream()
    scheduler = object.__new__(TurnScheduler)
    scheduler._providers = SimpleNamespace(guardrails=stream)
    original = stream.record_events
    stream.record_events = AsyncMock(side_effect=[RuntimeError("append unavailable")])
    with pytest.raises(RuntimeError, match="append unavailable"):
        await scheduler._ensure_channel_source_tracking("session", "turn")
    with pytest.raises(RuntimeError, match="tracking marker"):
        await pending_sources(stream, ["session"], "turn")
    stream.record_events = original
    await scheduler._ensure_channel_source_tracking("session", "turn")
    await scheduler._ensure_channel_source_tracking("session", "turn")
    stream.add("assistant_message", turn_id="turn", content="response")
    assert (await pending_sources(stream, ["session"], "turn"))[0] == "response"


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [False, True])
async def test_cancelled_source_delivery_includes_only_explicit_user_cancelled_partials(partial):
    stream = Stream()
    await record_state(stream, "session", state="tracking", turn_id="turn")
    stream.add("assistant_message", turn_id="turn", content="aborted", partial=True)
    if partial:
        stream.add(
            "assistant_message",
            turn_id="turn",
            content="saved partial",
            partial=True,
            cancelled=True,
            finish_reason="user_cancelled",
        )
    scheduler = object.__new__(TurnScheduler)
    scheduler._direct_turn_store = SimpleNamespace(
        effective_channel_delivery=AsyncMock(return_value=(None, None)),
        get=AsyncMock(
            return_value=SimpleNamespace(
                conversation_id="conversation", session_id="session", turn_id="turn", payload={}
            )
        ),
    )
    scheduler.channel_pending_sources = lambda *args: pending_sources(stream, ["session"], "turn")
    scheduler._channel_delivery = SimpleNamespace(deliver_fenced_direct_turn=AsyncMock())
    await scheduler._persist_direct_turn_terminal_delivery(
        request_id="request",
        lease=SimpleNamespace(),
        descriptor=ChannelDeliveryDescriptor(
            channel_type="matrix", account_id="account", chat_id="room"
        ),
        content="The current turn was cancelled.",
        attachments=None,
        error=True,
    )
    assert scheduler._channel_delivery.deliver_fenced_direct_turn.await_args.kwargs["content"] == (
        ("saved partial\n\n" if partial else "") + "The current turn was cancelled."
    )


@pytest.mark.asyncio
async def test_legacy_successor_segments_have_boundaries_and_exclude_aborted_tokens():
    adapter = SimpleNamespace(send_message=AsyncMock(return_value="sent"), send_typing=AsyncMock())
    scheduler = SimpleNamespace(remove_observer=lambda *args: None)
    observer = ChannelTurnObserver(
        channel_type="matrix",
        account_id="account",
        chat_id="room",
        conversation_id="conversation",
        turn_scheduler=scheduler,
        channel_manager_ref=lambda: SimpleNamespace(get_adapter=lambda *args: adapter),
    )
    observer._get_adapter = lambda: adapter
    observer._record_delivery_mapping = AsyncMock()
    for segment in ("first", "second"):
        await observer.on_token("conversation", "session", "message", delta=segment + "aborted")
        await observer.on_turn_complete(
            SimpleNamespace(managed_continuation_pending=True, final_content=segment)
        )
    await observer.on_token("conversation", "session", "message", delta="third")
    await observer.on_turn_complete(SimpleNamespace(managed_continuation_pending=False))
    assert adapter.send_message.await_args.args[0].content == "first\n\nsecond\n\nthird"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [False, True])
async def test_scheduler_owns_slow_terminal_success_and_exhaustion(error):
    stream = Stream()
    for turn in ("parent", "successor"):
        await record_state(stream, "session", state="tracking", turn_id=turn)
        stream.add("assistant_message", turn_id=turn, content=turn)
    stream.add(
        "system_message",
        event="turn_initiated",
        origin_kind="continuation",
        turn_id="successor",
        source_id="parent",
    )
    scheduler = object.__new__(TurnScheduler)
    scheduler._direct_turn_store = SimpleNamespace(
        effective_channel_delivery=AsyncMock(return_value=(None, None)),
        get=AsyncMock(
            return_value=SimpleNamespace(
                conversation_id="conversation",
                session_id="session",
                turn_id="successor",
                payload={"metadata": {"outbound_attachments": [{"artifact_id": "art_saved"}]}},
            )
        ),
    )
    scheduler._channel_delivery = SimpleNamespace(deliver_fenced_direct_turn=AsyncMock())

    async def slow_sources(*args):
        await asyncio.sleep(1.05)  # Longer than the generic observer budget.
        return await pending_sources(stream, ["session"], "successor")

    scheduler.channel_pending_sources = slow_sources
    descriptor = ChannelDeliveryDescriptor(
        channel_type="matrix", account_id="account", chat_id="room"
    )
    if error:
        await scheduler._persist_direct_turn_step_error_delivery(
            request_id="request",
            lease=SimpleNamespace(),
            descriptor=descriptor,
            error=TurnError(
                code="automatic_continuation_exhausted", message="Limit reached.", recoverable=True
            ),
            attachments=[{"artifact_id": "art_final"}],
        )
    else:
        await scheduler._persist_direct_turn_terminal_delivery(
            request_id="request",
            lease=SimpleNamespace(),
            descriptor=descriptor,
            content="successor",
            attachments=[{"artifact_id": "art_final"}],
        )
    sent = scheduler._channel_delivery.deliver_fenced_direct_turn.await_args.kwargs
    assert sent["content"] == "parent\n\nsuccessor" + ("\n\nLimit reached." if error else "")
    assert {ref["artifact_id"] for ref in sent["attachments"]} == {"art_saved", "art_final"}
    scheduler._observers = {}
    observer = ChannelTurnObserver(
        channel_type="matrix",
        account_id="account",
        chat_id="room",
        conversation_id="conversation",
        turn_scheduler=scheduler,
        channel_manager_ref=lambda: None,
        channel_delivery=descriptor,
    )
    async with asyncio.timeout(0.1):
        await observer.on_turn_complete(SimpleNamespace(managed_continuation_pending=False))
    scheduler._channel_delivery.deliver_fenced_direct_turn.assert_awaited_once()


@pytest.mark.asyncio
async def test_queued_progress_survives_repeated_snapshot_and_continuation():
    stream = Stream()
    await record_state(stream, "session", state="tracking", turn_id="parent")
    stream.add("assistant_message", turn_id="parent", content="Checking now.")
    _, sources = await pending_sources(stream, ["session"], "parent")
    queued = {progress_delivery_id(sources[0])}

    async def is_queued(source):
        return progress_delivery_id(source) in queued

    # A later terminal snapshot has a new event seq but the same source identity.
    stream.add("assistant_message", turn_id="parent", content="Checking now.")
    await record_state(stream, "session", state="tracking", turn_id="successor")
    stream.add(
        "system_message",
        event="turn_initiated",
        origin_kind="continuation",
        turn_id="successor",
        source_id="parent",
    )
    stream.add("assistant_message", turn_id="successor", content="Done.")
    content, refs = await pending_sources(stream, ["session"], "successor", is_queued=is_queued)
    assert content == "Done."
    assert [ref["turn_id"] for ref in refs] == ["successor"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["immediate", "concatenated", "final_only"])
async def test_worker_progress_without_admission_observer(mode):
    stream = Stream()
    await record_state(stream, "session", state="tracking", turn_id="turn")
    for cycle, content in ((1, "Checking now."), (2, "Looking deeper.")):
        stream.add("assistant_message", turn_id="turn", content=content, turn_cycle_index=cycle)
    queued = set()

    async def is_queued(source):
        return progress_delivery_id(source) in queued

    async def deliver(**kwargs):
        if kwargs.get("progress_source") is not None:
            queued.add(progress_delivery_id(kwargs["progress_source"]))

    scheduler = object.__new__(TurnScheduler)
    descriptor = ChannelDeliveryDescriptor(
        channel_type="matrix", account_id="account", chat_id="room"
    )
    scheduler._durable_request_by_conversation = {"conversation": "request"}
    scheduler._durable_fences = {
        "request": SimpleNamespace(lease=object(), assert_current=AsyncMock())
    }
    scheduler._direct_turn_store = SimpleNamespace(
        effective_channel_delivery=AsyncMock(return_value=(descriptor, mode)),
        get=AsyncMock(
            return_value=SimpleNamespace(
                session_id="session",
                turn_id="turn",
                payload={
                    "channel_delivery": descriptor.model_dump(mode="json"),
                    "metadata": {"channel_assistant_delivery_mode": mode},
                },
            )
        ),
    )
    scheduler._channel_delivery = SimpleNamespace(
        source_is_queued=is_queued, deliver_fenced_direct_turn=AsyncMock(side_effect=deliver)
    )
    scheduler.channel_pending_sources = lambda *args, **kwargs: pending_sources(
        stream, ["session"], "turn", is_queued=is_queued, **kwargs
    )
    await scheduler._deliver_durable_channel_progress("conversation")
    await scheduler._deliver_durable_channel_progress("conversation")
    calls = scheduler._channel_delivery.deliver_fenced_direct_turn.await_args_list
    assert [call.kwargs["content"] for call in calls] == (
        ["Checking now.", "Looking deeper."] if mode == "immediate" else []
    )
    stream.add("assistant_message", turn_id="turn", content="Done.", turn_cycle_index=3)
    terminal, _ = await scheduler.channel_pending_sources("conversation", "session", "turn")
    assert terminal == (
        "Done." if mode == "immediate" else "Checking now.\n\nLooking deeper.\n\nDone."
    )
