"""Matched local discovery benchmark; no external services or agent execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from collections import Counter
from pathlib import Path

from sqlalchemy import event

from cognis.core.direct_turn_runtime import DurableDirectTurnRuntime
from cognis.store.coordination import DatabaseLeaseStore
from cognis.store.database import create_engine, create_session_factory
from cognis.store.direct_turns import DirectTurnStatus, DirectTurnStore
from cognis.store.models import Base
from cognis.store.queries import create_agent, create_conversation, create_user


class MeasuredRuntime(DurableDirectTurnRuntime):
    passes = 0
    wakes = 0

    async def run_once(self) -> None:
        self.passes += 1
        await super().run_once()

    def _signal_wake(self) -> None:
        self.wakes += 1
        super()._signal_wake()


async def measure(active: bool, rounds: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="cognis-control-plane-") as directory:
        engine = create_engine(f"sqlite+aiosqlite:///{Path(directory) / 'bench.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            await create_user(session, email="bench@localhost", name="Benchmark", password_hash="")
            await create_agent(
                session, agent_id="bench", owner_email="bench@localhost", name="Benchmark"
            )
            await create_conversation(
                session,
                user_email="bench@localhost",
                agent_id="bench",
                context_type="web",
                conversation_id="bench",
            )
            await session.commit()
        counts: Counter[str] = Counter()

        def statement(_connection, _cursor, sql, _parameters, _context, _many):
            counts["sql"] += 1
            counts[sql.split()[0].lower()] += 1

        event.listen(engine.sync_engine, "before_cursor_execute", statement)
        event.listen(engine.sync_engine, "commit", lambda _connection: counts.update(["commits"]))
        event.listen(
            engine.sync_engine, "rollback", lambda _connection: counts.update(["rollbacks"])
        )
        store = DirectTurnStore(factory)
        completed = 0

        async def execute(row, payload, fence):
            nonlocal completed
            assert payload.content == "benchmark"
            result = await store.mark_terminal(
                row.request_id,
                lease=fence.lease,
                status=DirectTurnStatus.COMPLETED,
                outcome={"phase": "completed"},
            )
            assert result is not None
            completed += 1

        async def failure(_row, _error):
            raise AssertionError("Unexpected execution failure")

        runtimes = [
            MeasuredRuntime(
                store=store,
                lease_store=DatabaseLeaseStore(factory),
                controller_id=f"controller-{index}",
                incarnation_id="bench",
                artifact_store=None,
                execute_claimed_turn=execute,
                on_permanent_failure=failure,
                simple_mode=True,
            )
            for index in range(2)
        ]
        for runtime in runtimes:
            runtime._accepting_claims = True
        cpu_start, wall_start = time.process_time(), time.perf_counter()
        admitted = 0
        try:
            for index in range(rounds):
                if active:
                    await store.admit(
                        conversation_id="bench",
                        session_id=None,
                        agent_id="bench",
                        user_id="bench@localhost",
                        idempotency_scope="benchmark",
                        idempotency_key=str(index),
                        payload={"schema_version": 1, "content": "benchmark", "attachments": []},
                    )
                    admitted += 1
                    await runtimes[index % 2].wake()
                # Sequential controller scans make query counts reproducible.
                for runtime in runtimes:
                    await runtime.run_once()
                    tasks = list(runtime._active.values())
                    if tasks:
                        await asyncio.gather(*tasks)
                        await asyncio.sleep(0)
            assert completed == admitted
            return {
                "workload": "active" if active else "no-work",
                "rounds": rounds,
                "controllers": 2,
                "admitted": admitted,
                "completed": completed,
                "passes": sum(runtime.passes for runtime in runtimes),
                "wake_requests": sum(runtime.wakes for runtime in runtimes),
                "cpu_seconds": time.process_time() - cpu_start,
                "wall_seconds": time.perf_counter() - wall_start,
                **counts,
                "scope": "SQLite direct-turn discovery and fenced stub completion; no providers",
            }
        finally:
            for runtime in runtimes:
                await runtime.stop()
            await engine.dispose()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=100)
    args = parser.parse_args()
    print(
        json.dumps([await measure(False, args.rounds), await measure(True, args.rounds)], indent=2)
    )


if __name__ == "__main__":
    asyncio.run(main())
