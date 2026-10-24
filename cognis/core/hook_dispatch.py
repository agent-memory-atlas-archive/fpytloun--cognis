"""Content-backed tool journal for resumable internal hooks.

Intaris owns descriptors (including canonical event snapshots); the hook row
holds only their reference and executor-binding metadata. The execution lease
fences every write. No interrupted tool is dispatched by this recovery path.
"""

from __future__ import annotations

import json
from typing import Any

from cognis.core.hook_handoff import lock_run
from cognis.models.session import SessionEvent
from cognis.store.models import AgentHookRunRow


class HookDispatchJournal:
    @staticmethod
    def key(session_id: str, turn_id: str, call_id: str) -> str:
        return json.dumps([session_id, turn_id, call_id])

    def __init__(self, fence: Any, guardrails: Any) -> None:
        self.fence = fence
        self.guardrails = guardrails

    async def record(
        self, session_id: str, turn_id: str, descriptors: list[dict[str, Any]]
    ) -> None:
        await self.fence.assert_current()
        if len(descriptors) > 500:
            raise ValueError("Hook tool batch exceeds recovery bound")
        result = await self.guardrails.record_events(
            session_id,
            [
                SessionEvent(
                    type="lifecycle",
                    data={
                        "event": "hook_tool_dispatch",
                        "hook_run_id": self.fence.run_id,
                        "turn_id": turn_id,
                        "descriptors": descriptors,
                    },
                )
            ],
        )
        if not result.ok or result.first_seq is None:
            raise RuntimeError("Hook dispatch journal was not acknowledged")
        async with self.fence.session_factory() as db:
            run = await lock_run(db, self.fence.run_id)
            await self.fence.assert_current(db)
            refs = dict(run.handoff.get("tool_dispatch") or {})
            for descriptor in descriptors:
                key = self.key(session_id, turn_id, descriptor["call_id"])
                refs[key] = {
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "seq": result.first_seq,
                    "call_id": descriptor["call_id"],
                    "binding": refs.get(key, {}).get("binding", {}),
                }
            if len(refs) > 500:
                raise ValueError("Hook pending dispatches exceed recovery bound")
            run.handoff = {**run.handoff, "tool_dispatch": refs}
            await db.commit()

    async def bind(
        self,
        call_id: str,
        executor_id: str,
        executor_instance_id: str | None,
        *,
        session_id: str,
        turn_id: str,
        dispatch_state: str,
    ) -> None:
        async with self.fence.session_factory() as db:
            run = await lock_run(db, self.fence.run_id)
            await self.fence.assert_current(db)
            refs = dict(run.handoff.get("tool_dispatch") or {})
            key = self.key(session_id, turn_id, call_id)
            if key not in refs:
                raise RuntimeError("Unjournaled hook tool dispatch")
            refs[key] = {
                **refs[key],
                "binding": {
                    "executor_id": executor_id,
                    "executor_instance_id": executor_instance_id,
                    "dispatch_state": dispatch_state,
                },
            }
            run.handoff = {**run.handoff, "tool_dispatch": refs}
            await db.commit()

    async def complete(self, session_id: str, turn_id: str, call_ids: list[str]) -> None:
        async with self.fence.session_factory() as db:
            run = await lock_run(db, self.fence.run_id)
            await self.fence.assert_current(db)
            refs = dict(run.handoff.get("tool_dispatch") or {})
            for call_id in call_ids:
                refs.pop(self.key(session_id, turn_id, call_id), None)
            run.handoff = {**run.handoff, "tool_dispatch": refs}
            await db.commit()

    async def recover(self, scheduler: Any) -> None:
        async with self.fence.session_factory() as db:
            run = await db.get(AgentHookRunRow, self.fence.run_id)
            refs = (run.handoff or {}).get("tool_dispatch") or {}
        batches: dict[tuple[str, str], list[dict[str, Any]]] = {}
        events_by_ref: dict[tuple[str, int], dict[str, Any]] = {}
        for ref in refs.values():
            await self.fence.assert_current()
            location = (ref["session_id"], ref["seq"])
            if location not in events_by_ref:
                result = await self.guardrails.read_events(ref["session_id"], seqs=[ref["seq"]])
                events = [e for e in result.events if e.get("seq") == ref["seq"]]
                if (
                    len(events) != 1
                    or events[0].get("data", {}).get("hook_run_id") != self.fence.run_id
                ):
                    raise RuntimeError("Hook dispatch journal unavailable")
                events_by_ref[location] = events[0]
            data = events_by_ref[location]["data"]
            if data.get("turn_id") != ref["turn_id"]:
                raise RuntimeError("Hook journal turn mismatch")
            descriptors = [d for d in data["descriptors"] if d["call_id"] == ref["call_id"]]
            if len(descriptors) != 1:
                raise RuntimeError("Incomplete hook dispatch journal")
            batches.setdefault((ref["session_id"], ref["turn_id"]), []).append(
                {**descriptors[0], **ref["binding"]}
            )
        for (session_id, turn_id), descriptors in batches.items():
            await self.fence.assert_current()
            await scheduler.recover_internal_tool_batch(
                session_id=session_id,
                turn_id=turn_id,
                descriptors=descriptors,
            )
            await self.complete(session_id, turn_id, [d["call_id"] for d in descriptors])
