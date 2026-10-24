"""Ephemeral session activity for conservative, cross-replica idle failback."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from cognis.core.redis_service import RedisService

_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local raw = redis.call('GET', KEYS[1])
local s = raw and cjson.decode(raw) or {active={}, last=now, cache=0}
for token, deadline in pairs(s.active) do
  if deadline <= now then s.active[token] = nil end
end
local eligible = 0
if ARGV[1] == 'begin' then
  if s.probe and s.active[s.probe] then return -1 end
  local threshold = tonumber(ARGV[4])
  if s.cache > 0 then threshold = math.min(threshold, s.cache) end
  if raw and next(s.active) == nil and now - s.last >= threshold then eligible = 1 end
  if eligible == 1 then s.probe = ARGV[2] end
  s.active[ARGV[2]] = now + tonumber(ARGV[3])
  s.last = now + tonumber(ARGV[3])
else
  if s.active[ARGV[2]] then
    s.active[ARGV[2]] = nil
    s.last = now
    s.cache = tonumber(ARGV[4])
  end
end
redis.call('SET', KEYS[1], cjson.encode(s), 'EX', 2592000)
return eligible
"""


class InferenceActivity:
    """Track active requests and end-of-request idle time, never message content.

    Redis TIME and a single-key Lua mutation serialize admission across replicas.
    Missing/expired state starts a fresh idle window instead of triggering a
    probe. Active-request leases cover the whole enforced request deadline.
    """

    def __init__(self, redis: RedisService | None = None) -> None:
        self._redis = redis if redis is not None and redis.configured else None
        self._states: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def begin(self, key: str, token: str, lease: float, idle_seconds: float) -> bool:
        """Admit activity and atomically consume any idle eligibility."""
        while True:
            result = await self._operate("begin", key, token, lease, idle_seconds)
            if result >= 0:
                return bool(result)
            await asyncio.sleep(0.05)

    async def end(self, key: str, token: str, cache_seconds: float | None) -> None:
        """Finish a matching request without letting stale completions reset state."""
        try:
            await self._operate("end", key, token, 0, cache_seconds or 0)
        except Exception:
            logging.getLogger(__name__).warning(
                "Inference activity completion unavailable", exc_info=True
            )

    async def _operate(self, action: str, key: str, token: str, lease: float, value: float) -> int:
        if self._redis is not None:
            result = await self._redis.eval(
                _SCRIPT,
                keys=[f"cognis:inference:activity:{key}"],
                args=[action, token, lease, value],
            )
            if result is None:
                raise RuntimeError("Inference activity coordination unavailable")
            return int(result)
        async with self._lock:
            now = time.monotonic()
            self._states = {k: s for k, s in self._states.items() if now - s["last"] < 2592000}
            existed = key in self._states
            state = self._states.setdefault(key, {"active": {}, "last": now, "cache": 0})
            state["active"] = {k: v for k, v in state["active"].items() if v > now}
            if action == "begin":
                if state.get("probe") in state["active"]:
                    return -1
                threshold = min(value, state["cache"]) if state["cache"] > 0 else value
                eligible = existed and not state["active"] and now - state["last"] >= threshold
                if eligible:
                    state["probe"] = token
                state["active"][token] = now + lease
                state["last"] = now + lease
                return bool(eligible)
            if token in state["active"]:
                del state["active"][token]
                state["last"] = now
                state["cache"] = value
            return False


def cache_lifetime_seconds(value: Any) -> float | None:
    """Read explicit Anthropic ephemeral-cache TTLs from a prepared request.

    No cache hit or expiry is claimed: this is an inactivity-based estimate.
    Unknown cache modes deliberately use only the operator's idle threshold.
    """
    found: list[float] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            points = item.get("cache_breakpoint_index")
            if isinstance(points, int):
                found.append(300)
            elif isinstance(points, list):
                for point in points:
                    if isinstance(point, int):
                        found.append(300)
                    elif isinstance(point, dict):
                        ttl = point.get("ttl", "5m")
                        if ttl in {"5m", "1h"}:
                            found.append(300 if ttl == "5m" else 3600)
            control = item.get("cache_control")
            if isinstance(control, dict) and control.get("type") == "ephemeral":
                ttl = control.get("ttl", "5m")
                if ttl in {"5m", "1h"}:
                    found.append(300 if ttl == "5m" else 3600)
            for key, child in item.items():
                if key != "cache_control":
                    visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return min(found) if found else None
