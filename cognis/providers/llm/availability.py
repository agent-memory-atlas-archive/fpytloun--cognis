"""Ephemeral inference availability, independent of durable session bindings.

Configured Redis is authoritative and fail-closed. Memory is used only when Redis
is unconfigured. Reports are fenced by generation and trial token; reporting
failure must never replay an upstream request.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field

from cognis.core.redis_service import RedisService, RedisUnavailableError
from cognis.providers.llm.recovery_policy import RecoveryPolicy


@dataclass(frozen=True, slots=True)
class AvailabilityPermit:
    """Evidence of admission, not a durable binding or execution permission."""

    key: str
    generation: str
    trial_token: str
    retry_after_seconds: float = 0
    failure_category: str | None = None

    @property
    def allowed(self) -> bool:
        return self.retry_after_seconds == 0


@dataclass
class _State:
    generation: str
    expires_at: float
    failures: dict[str, float] = field(default_factory=dict)
    open_until: float = 0
    trial_token: str = ""
    trial_until: float = 0
    failure_category: str | None = None


# Single-key atomicity also works with Redis Cluster. Redis TIME avoids
# cross-controller clock skew. Tags distinguish state absence from I/O failure.
_AVAILABILITY_SCRIPT = """
local action = ARGV[1]
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local ttl = tonumber(ARGV[2])
local generation = ARGV[3]
local token = ARGV[4]
local window = tonumber(ARGV[5])
local threshold = tonumber(ARGV[6])
local cooldown = tonumber(ARGV[7])
local request = ARGV[8]
local block = tonumber(ARGV[9])
local lease = tonumber(ARGV[10])
local raw = redis.call('GET', KEYS[1])
local state = nil
if raw then state = cjson.decode(raw) end
if action == 'admit' and not state then
  state = {generation=generation, failures={}, open_until=0, trial_token='', trial_until=0}
end
if not state or (action ~= 'admit' and state.generation ~= generation) then
  if action == 'check' then return {'blocked', generation, '', '1'} end
  return {'stale'}
end
if action == 'check' then
  if (token == '' and state.open_until > 0) or
     (token ~= '' and (state.trial_token ~= token or state.trial_until <= now)) then
    return {'blocked', generation, '', tostring(math.max(1, state.open_until - now))}
  end
  return {'ok', generation, token, '0'}
end
for id, stamp in pairs(state.failures) do
  if stamp + window <= now then state.failures[id] = nil end
end
if action == 'admit' then
  if state.open_until > now then
    return {'blocked', state.generation, '', tostring(state.open_until - now), state.failure_category or ''}
  end
  if state.open_until > 0 then
    if state.trial_until > now then
      return {'blocked', state.generation, '', tostring(state.trial_until - now), state.failure_category or ''}
    end
    state.trial_token = token
    state.trial_until = now + lease
  else token = '' end
elseif action == 'release' then
  if token ~= '' and state.trial_token == token then
    state.trial_token = ''
    state.trial_until = 0
  end
elseif action == 'success' then
  if token ~= '' and state.trial_token == token and state.trial_until > now then
    state.open_until = 0
    state.trial_token = ''
    state.trial_until = 0
    state.failures = {}
    state.generation = ARGV[11]
  end
elseif action == 'failure' then
  if token ~= '' and (state.trial_token ~= token or state.trial_until <= now) then
    return {'stale'}
  end
  if not state.failures[request] then state.failures[request] = now end
  if ARGV[12] ~= '' then state.failure_category = ARGV[12] end
  local count = 0
  for _ in pairs(state.failures) do count = count + 1 end
  if block > 0 or count >= threshold or token ~= '' then
    state.open_until = math.max(state.open_until, now + math.max(block, cooldown))
    state.trial_token = ''
    state.trial_until = 0
    state.generation = ARGV[11]
  end
end
redis.call('SET', KEYS[1], cjson.encode(state), 'EX', ttl)
return {'ok', state.generation, token, '0'}
"""


class InferenceAvailability:
    """Shared circuit admission with an in-memory single-replica implementation."""

    def __init__(self, redis: RedisService | None = None) -> None:
        self._redis = redis if redis is not None and redis.configured else None
        self._states: dict[str, _State] = {}
        self._blocks: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def limit(self, key: str, *, block_seconds: float = 0) -> float:
        """Shared known rate/quota reset, independent of route circuit policy."""
        if self._redis is not None:
            result = await self._redis.eval(
                """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local until_time = tonumber(redis.call('GET', KEYS[1]) or '0')
local duration = tonumber(ARGV[1])
if duration > 0 then
  until_time = math.max(until_time, now + duration)
  redis.call('SET', KEYS[1], tostring(until_time), 'PX',
             math.max(1, math.ceil((until_time - now) * 1000)))
end
return {'ok', tostring(math.max(0, until_time - now))}
""",
                keys=[f"cognis:inference:limit:{key}"],
                args=[block_seconds],
            )
            if not isinstance(result, (list, tuple)) or len(result) != 2:
                raise RedisUnavailableError("Inference limit state unavailable")
            tag = result[0].decode() if isinstance(result[0], bytes) else result[0]
            if tag != "ok":
                raise RedisUnavailableError("Invalid inference limit state")
            return float(result[1])
        async with self._lock:
            now = time.monotonic()
            self._blocks = {k: end for k, end in self._blocks.items() if end > now}
            if block_seconds:
                self._blocks[key] = max(self._blocks.get(key, 0), now + block_seconds)
            return max(0, self._blocks.get(key, 0) - now)

    @staticmethod
    def key(*, target_fingerprint: str, policy: RecoveryPolicy, scope: str) -> str:
        """Partition circuit policy without placing secrets in Redis keys."""
        identity = json.dumps(
            [
                target_fingerprint,
                scope,
                policy.failure_threshold,
                policy.failure_window_seconds,
                policy.cooldown_seconds,
            ],
            separators=(",", ":"),
        )
        return "cognis:inference:availability:" + hashlib.sha256(identity.encode()).hexdigest()

    async def admit(
        self, key: str, policy: RecoveryPolicy, *, lease_seconds: float
    ) -> AvailabilityPermit:
        """Grant one normal attempt or one fenced half-open trial."""
        return await self._operate(
            "admit",
            AvailabilityPermit(key, uuid.uuid4().hex, uuid.uuid4().hex),
            policy,
            lease_seconds=lease_seconds,
        )

    async def failed(
        self,
        permit: AvailabilityPermit,
        policy: RecoveryPolicy,
        *,
        request_id: str,
        retry_after_seconds: float = 0,
        failure_category: str | None = None,
    ) -> None:
        """Record one terminal candidate failure, even when fallback succeeds."""
        await self._operate(
            "failure",
            permit,
            policy,
            request_id=request_id,
            block_seconds=retry_after_seconds,
            failure_category=failure_category,
        )

    async def verify(self, permit: AvailabilityPermit, policy: RecoveryPolicy) -> bool:
        """Recheck admission immediately before dispatch without renewing leases."""
        return (await self._operate("check", permit, policy)).allowed

    async def succeeded(self, permit: AvailabilityPermit, policy: RecoveryPolicy) -> None:
        """Close only the matching half-open generation."""
        await self._operate("success", permit, policy)

    async def release(self, permit: AvailabilityPermit, policy: RecoveryPolicy) -> None:
        """Release only a matching trial token; safe for stale cancellation."""
        if permit.trial_token:
            await self._operate("release", permit, policy)

    async def _operate(
        self,
        action: str,
        permit: AvailabilityPermit,
        policy: RecoveryPolicy,
        *,
        request_id: str = "",
        block_seconds: float = 0,
        lease_seconds: float = 1,
        failure_category: str | None = None,
    ) -> AvailabilityPermit:
        ttl = (
            int(
                max(
                    policy.failure_window_seconds,
                    policy.cooldown_seconds,
                    block_seconds,
                    lease_seconds,
                )
            )
            + 60
        )
        next_generation = uuid.uuid4().hex
        if self._redis is not None:
            result = await self._redis.eval(
                _AVAILABILITY_SCRIPT,
                keys=[permit.key],
                args=[
                    action,
                    ttl,
                    permit.generation,
                    permit.trial_token,
                    policy.failure_window_seconds,
                    policy.failure_threshold,
                    policy.cooldown_seconds,
                    request_id,
                    block_seconds,
                    lease_seconds,
                    next_generation,
                    failure_category or "",
                ],
            )
            if not isinstance(result, (list, tuple)) or not result:
                raise RedisUnavailableError("Inference availability is unavailable")
            values = [v.decode() if isinstance(v, bytes) else str(v) for v in result]
            if values[0] == "stale":
                return permit
            if len(values) not in {4, 5} or values[0] not in {"ok", "blocked"}:
                raise RedisUnavailableError("Invalid inference availability response")
            return AvailabilityPermit(
                permit.key,
                values[1],
                values[2],
                float(values[3]),
                values[4] or None if len(values) == 5 else None,
            )

        async with self._lock:
            now = time.monotonic()
            self._states = {
                key: state for key, state in self._states.items() if state.expires_at > now
            }
            state = self._states.get(permit.key)
            if state is None:
                if action != "admit":
                    return (
                        AvailabilityPermit(permit.key, permit.generation, "", 1)
                        if action == "check"
                        else permit
                    )
                state = _State(permit.generation, now + ttl)
                self._states[permit.key] = state
            elif action != "admit" and state.generation != permit.generation:
                return (
                    AvailabilityPermit(permit.key, permit.generation, "", 1)
                    if action == "check"
                    else permit
                )
            if action == "check":
                valid = (
                    state.trial_token == permit.trial_token and state.trial_until > now
                    if permit.trial_token
                    else state.open_until == 0
                )
                return (
                    permit
                    if valid
                    else AvailabilityPermit(
                        permit.key, permit.generation, "", max(1, state.open_until - now)
                    )
                )
            state.failures = {
                key: stamp
                for key, stamp in state.failures.items()
                if stamp + policy.failure_window_seconds > now
            }
            token = permit.trial_token
            if action == "admit":
                remaining = max(state.open_until, state.trial_until) - now
                if remaining > 0:
                    return AvailabilityPermit(
                        permit.key, state.generation, "", remaining, state.failure_category
                    )
                if state.open_until:
                    state.trial_token, state.trial_until = token, now + lease_seconds
                else:
                    token = ""
            elif action == "release":
                if token and state.trial_token == token:
                    state.trial_token, state.trial_until = "", 0
            elif action == "success":
                if token and state.trial_token == token and state.trial_until > now:
                    state.open_until = 0
                    state.trial_token, state.trial_until = "", 0
                    state.failures.clear()
                    state.generation = next_generation
            elif action == "failure":
                if token and (state.trial_token != token or state.trial_until <= now):
                    return permit
                state.failures.setdefault(request_id, now)
                if failure_category:
                    state.failure_category = failure_category
                if block_seconds or len(state.failures) >= policy.failure_threshold or token:
                    state.open_until = max(
                        state.open_until, now + max(block_seconds, policy.cooldown_seconds)
                    )
                    state.trial_token, state.trial_until = "", 0
                    state.generation = next_generation
            state.expires_at = now + ttl
            return AvailabilityPermit(permit.key, state.generation, token)
