"""Availability has one authority and never confuses stale reporting with admission."""

from unittest.mock import AsyncMock

import pytest

from cognis.core.redis_service import RedisService, RedisUnavailableError
from cognis.providers.llm.availability import InferenceAvailability
from cognis.providers.llm.recovery_policy import NamedRouteConfig, RecoveryPolicy


@pytest.mark.asyncio
async def test_terminal_failures_are_deduplicated_and_circuit_has_one_trial(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("cognis.providers.llm.availability.time.monotonic", lambda: now[0])
    store = InferenceAvailability()
    policy = RecoveryPolicy(failure_threshold=2, cooldown_seconds=10)
    key = store.key(target_fingerprint="provider-revision", policy=policy, scope="route")
    first = await store.admit(key, policy, lease_seconds=20)
    await store.failed(first, policy, request_id="request-one")
    await store.failed(first, policy, request_id="request-one")
    assert (await store.admit(key, policy, lease_seconds=20)).allowed
    await store.failed(first, policy, request_id="request-two")
    assert not (await store.admit(key, policy, lease_seconds=20)).allowed
    now[0] += 11
    trial = await store.admit(key, policy, lease_seconds=20)
    assert trial.allowed and trial.trial_token
    assert not (await store.admit(key, policy, lease_seconds=20)).allowed
    await store.succeeded(first, policy)  # A stale success cannot close the circuit.
    assert not (await store.admit(key, policy, lease_seconds=20)).allowed
    await store.succeeded(trial, policy)
    assert (await store.admit(key, policy, lease_seconds=20)).allowed


@pytest.mark.asyncio
async def test_stale_trial_cancellation_cannot_release_replacement(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("cognis.providers.llm.availability.time.monotonic", lambda: now[0])
    store = InferenceAvailability()
    policy = RecoveryPolicy(failure_threshold=1, cooldown_seconds=1)
    first = await store.admit("target", policy, lease_seconds=2)
    await store.failed(first, policy, request_id="request")
    now[0] += 2
    expired = await store.admit("target", policy, lease_seconds=2)
    now[0] += 3
    current = await store.admit("target", policy, lease_seconds=2)
    await store.release(expired, policy)
    assert not (await store.admit("target", policy, lease_seconds=2)).allowed
    await store.release(current, policy)
    assert (await store.admit("target", policy, lease_seconds=2)).allowed


@pytest.mark.asyncio
async def test_configured_redis_error_never_falls_back_to_memory():
    redis = RedisService("redis://127.0.0.1:6379")
    redis.eval = AsyncMock(return_value=None)
    store = InferenceAvailability(redis)
    with pytest.raises(RedisUnavailableError):
        await store.admit("target", RecoveryPolicy(), lease_seconds=10)
    assert store._states == {}
    await redis.aclose()


def test_route_rejects_duplicate_and_nested_targets():
    with pytest.raises(ValueError, match="duplicate"):
        NamedRouteConfig(
            name="chat",
            targets=[
                {"provider_id": "one", "model": "chat"},
                {"provider_id": "one", "model": "chat"},
            ],
        )
    with pytest.raises(ValueError, match="concrete"):
        NamedRouteConfig(name="chat", targets=[{"provider_id": "cognis", "model": "other"}])


@pytest.mark.asyncio
async def test_expired_state_ignores_stale_completion(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("cognis.providers.llm.availability.time.monotonic", lambda: now[0])
    store = InferenceAvailability()
    policy = RecoveryPolicy()
    first = await store.admit("target", policy, lease_seconds=10)
    now[0] += 200
    await store.failed(first, policy, request_id="late-request")
    assert store._states == {}
    replacement = await store.admit("target", policy, lease_seconds=10)
    assert replacement.generation != first.generation


@pytest.mark.asyncio
async def test_shared_lua_circuit_retains_upstream_category_without_error_contents():
    import json
    from types import SimpleNamespace

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis()

    async def evaluate(script, *, keys, args):
        return await client.eval(script, len(keys), *keys, *args)

    redis = SimpleNamespace(configured=True, eval=evaluate)
    first = InferenceAvailability(redis)
    other = InferenceAvailability(redis)
    policy = RecoveryPolicy(failure_threshold=1)
    key = first.key(target_fingerprint="target", policy=policy, scope="route")
    permit = await first.admit(key, policy, lease_seconds=10)
    await first.failed(
        permit,
        policy,
        request_id="upstream-failure",
        retry_after_seconds=120,
        failure_category="connection",
    )
    blocked = await other.admit(key, policy, lease_seconds=10)
    assert not blocked.allowed
    assert blocked.failure_category == "connection"
    assert 119 < blocked.retry_after_seconds <= 120
    stored = json.loads(await client.get(key))
    assert stored["failure_category"] == "connection"
    assert not {"message", "details", "payload"} & stored.keys()
    await client.aclose()
