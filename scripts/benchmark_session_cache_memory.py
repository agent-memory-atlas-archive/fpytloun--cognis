"""Offline cache codec allocation benchmark using synthetic, non-sensitive data.

Run with ``uv run python scripts/benchmark_session_cache_memory.py``.
Optionally pass a previous session_cache.py source path for a baseline comparison.
No external services are contacted.
"""

from __future__ import annotations

import asyncio
import gc
import importlib.util
import json
import sys
import tracemalloc
from pathlib import Path
from time import perf_counter
from unittest.mock import AsyncMock


async def main() -> None:
    if len(sys.argv) > 1:
        name = "cognis.core.session_cache"
        spec = importlib.util.spec_from_file_location(name, sys.argv[1])
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    else:
        from cognis.core import session_cache as module

    from cognis.core.redis_service import RedisService

    values: dict[str, bytes] = {}
    service = RedisService("")

    async def get(key: str) -> bytes | None:
        return values.get(key)

    async def set_value(key: str, value: bytes, *, ttl_seconds: int) -> bool:
        values[key] = value
        return True

    async def evaluate(script: str, *, keys: tuple, args: tuple) -> int:
        values[keys[0]] = args[3]
        return 1

    service.get = get
    service.set = set_value
    service.eval = evaluate
    entry = module.CachedSessionState(
        session_id="session-memory-benchmark",
        intaris_session_id="session-memory-benchmark",
        initialized=True,
        last_event_seq=64,
        events=[
            module.CachedEvent(
                seq=i,
                type="tool_result",
                data={"content": f"{i}:" + "Příliš 🐈 " * 4096},
            )
            for i in range(1, 65)
        ],
    )
    cache = module.SessionCache(AsyncMock(), redis_service=service)
    for operation in ("checkpoint", "hydrate"):
        gc.collect()
        tracemalloc.start()
        start = perf_counter()
        if operation == "checkpoint":
            await cache._redis_set(entry)
        else:
            restored = await cache._redis_get(entry.session_id)
            assert restored is not None
            assert [(e.seq, e.data) for e in restored.events] == [
                (e.seq, e.data) for e in entry.events
            ]
        elapsed = perf_counter() - start
        retained, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(
            json.dumps(
                {
                    "operation": operation,
                    "elapsed_seconds": round(elapsed, 4),
                    "peak_bytes": peak,
                    "retained_bytes": retained,
                    "wire_bytes": sum(map(len, values.values())),
                    "rss_kib": next(
                        line.split()[1]
                        for line in Path("/proc/self/status").read_text().splitlines()
                        if line.startswith("VmRSS:")
                    ),
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
