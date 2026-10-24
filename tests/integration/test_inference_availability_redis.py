"""Run against an isolated Redis via COGNIS_TEST_REDIS_URL; no production keys."""

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

from cognis.core.redis_service import RedisService, RedisUnavailableError
from cognis.providers.llm.availability import InferenceAvailability
from cognis.providers.llm.recovery_policy import RecoveryPolicy


@pytest_asyncio.fixture
async def replicas():
    url = os.environ.get("COGNIS_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set COGNIS_TEST_REDIS_URL to an isolated Redis instance")
    services = [RedisService(url), RedisService(url)]
    assert all(await asyncio.gather(*(service.start() for service in services)))
    key = f"cognis:test:inference:{uuid.uuid4().hex}"
    try:
        yield services, [InferenceAvailability(service) for service in services], key
    finally:
        await services[0].delete(key)
        await asyncio.gather(*(service.aclose() for service in services))


@pytest.mark.asyncio
async def test_shared_cooldown_and_one_half_open_trial(replicas):
    _, (a, b), key = replicas
    policy = RecoveryPolicy(failure_threshold=1, cooldown_seconds=1)
    initial = await a.admit(key, policy, lease_seconds=10)
    assert initial.allowed
    await a.failed(initial, policy, request_id="failed-request")
    assert not (await b.admit(key, policy, lease_seconds=10)).allowed
    await asyncio.sleep(1.05)
    trials = await asyncio.gather(
        a.admit(key, policy, lease_seconds=10),
        b.admit(key, policy, lease_seconds=10),
    )
    winners = [permit for permit in trials if permit.allowed]
    assert len(winners) == 1
    await a.succeeded(initial, policy)
    assert not (await b.admit(key, policy, lease_seconds=10)).allowed
    await b.succeeded(winners[0], policy)
    assert (await a.admit(key, policy, lease_seconds=10)).allowed


@pytest.mark.asyncio
async def test_reset_cannot_be_repopulated_by_old_report(replicas):
    services, (a, b), key = replicas
    policy = RecoveryPolicy(failure_threshold=1)
    initial = await a.admit(key, policy, lease_seconds=10)
    await services[0].delete(key)
    await a.failed(initial, policy, request_id="old-request")
    assert await services[0].get(key) is None
    fresh = await b.admit(key, policy, lease_seconds=10)
    assert fresh.allowed and fresh.generation != initial.generation
    await a.failed(initial, policy, request_id="old-request")
    assert (await b.admit(key, policy, lease_seconds=10)).allowed


@pytest.mark.asyncio
async def test_configured_client_loss_denies_new_admission(replicas):
    services, (a, _), key = replicas
    policy = RecoveryPolicy()
    permit = await a.admit(key, policy, lease_seconds=10)
    await services[0].aclose()
    with pytest.raises(RedisUnavailableError):
        await a.admit(key, policy, lease_seconds=10)
    with pytest.raises(RedisUnavailableError):
        await a.succeeded(permit, policy)
    assert a._states == {}
