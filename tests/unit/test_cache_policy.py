from types import SimpleNamespace

import pytest

from cognis.models.config import ModelInfo
from cognis.providers.llm.activity import InferenceActivity, cache_lifetime_seconds
from cognis.providers.llm.cache_policy import (
    effective_cache_ttl,
    primary_conversation,
    supported_cache_ttls,
)


@pytest.mark.parametrize(
    "kind,task,workflow,expected",
    [
        ("primary", None, None, True),
        ("primary", "task", None, False),
        ("primary", None, "workflow", False),
        ("secondary", None, None, False),
        ("system", None, None, False),
    ],
)
def test_workload_precedence(kind, task, workflow, expected):
    ctx = SimpleNamespace(
        agent=SimpleNamespace(agent_type=kind),
        executor_agent=None,
        task_id=task,
        workflow_id=workflow,
        workflow_step_scope=None,
    )
    assert primary_conversation(ctx) is expected
    info = ModelInfo(model_id="claude-opus-5-5", supported_cache_ttls=["5m", "1h"])
    assert effective_cache_ttl(info, primary_conversation=primary_conversation(ctx)) == (
        "1h" if expected else "5m"
    )


def test_backend_capability_and_overrides():
    assert supported_cache_ttls("us.anthropic.claude-opus-4-6-v1", "bedrock", True) == ["5m", "1h"]
    assert supported_cache_ttls("anthropic.claude-3-7-sonnet", "bedrock", True) == ["5m"]
    assert supported_cache_ttls("gpt-4o", "openai", True) == []
    info = ModelInfo(
        model_id="claude",
        supported_cache_ttls=["5m"],
        primary_cache_ttl="1h",
        auxiliary_cache_ttl="1h",
    )
    assert effective_cache_ttl(info, primary_conversation=True) == "5m"
    info.supported_cache_ttls.append("1h")
    assert effective_cache_ttl(info, primary_conversation=False) == "1h"


@pytest.mark.asyncio
async def test_idle_activity_shorter_threshold_concurrency_and_crash(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("cognis.providers.llm.activity.time.monotonic", lambda: clock[0])
    activity = InferenceActivity()
    assert not await activity.begin("session", "first", 600, 3600)
    await activity.end("session", "first", 300)
    clock[0] += 299
    assert not await activity.begin("session", "second", 600, 3600)
    await activity.end("session", "second", 300)
    clock[0] += 301
    assert await activity.begin("session", "probe", 600, 3600)
    assert await activity._operate("begin", "session", "concurrent", 600, 3600) == -1
    await activity.end("session", "probe", 3600)
    assert not await activity.begin("session", "concurrent", 600, 3600)
    clock[0] += 301
    assert not await activity.begin("session", "still-active", 600, 300)
    # Expired requests do not immediately permit another probe.
    clock[0] += 601
    assert not await activity.begin("session", "after-crash", 600, 300)
    await activity.end("session", "after-crash", None)
    clock[0] += 301
    assert await activity.begin("session", "unknown-cache", 600, 300)


def test_cache_lifetime_from_effective_markers():
    assert cache_lifetime_seconds([{"cache_control": {"type": "ephemeral", "ttl": "1h"}}]) == 3600
    assert cache_lifetime_seconds([{"cache_control": {"type": "ephemeral"}}]) == 300
    assert cache_lifetime_seconds([]) is None


@pytest.mark.asyncio
async def test_lua_probe_blocks_replica_admission_until_completion():
    import asyncio
    import json

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis()

    class Redis:
        configured = True

        async def eval(self, script, *, keys, args):
            return await client.eval(script, len(keys), *keys, *args)

    first, second = InferenceActivity(Redis()), InferenceActivity(Redis())
    assert not await first.begin("shared", "old", 600, 3600)
    await first.end("shared", "old", 300)
    key = "cognis:inference:activity:shared"
    state = json.loads(await client.get(key))
    state["last"] -= 301
    await client.set(key, json.dumps(state))
    assert await first.begin("shared", "probe", 600, 3600)
    waiter = asyncio.create_task(second.begin("shared", "other", 600, 3600))
    await asyncio.sleep(0.06)
    assert not waiter.done()
    await first.end("shared", "probe", 3600)
    assert not await asyncio.wait_for(waiter, 1)
    await second.end("shared", "other", 3600)
    await client.aclose()


@pytest.mark.asyncio
async def test_optional_redis_and_failed_completion_are_safe():
    from unittest.mock import AsyncMock

    redis = SimpleNamespace(configured=False, eval=AsyncMock())
    activity = InferenceActivity(redis)
    assert not await activity.begin("local", "first", 600, 3600)
    await activity.end("local", "first", None)
    redis.eval.assert_not_called()
    redis.configured = True
    redis.eval = AsyncMock(return_value=0)
    activity = InferenceActivity(redis)
    assert not await activity.begin("remote", "first", 600, 3600)
    redis.eval.side_effect = RuntimeError("connection lost")
    await activity.end("remote", "first", 3600)
    with pytest.raises(RuntimeError, match="connection lost"):
        await activity.begin("remote", "next", 600, 3600)


def test_shortest_lifetime_includes_message_breakpoints_and_tool_markers():
    request = {
        "tools": [{"cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        "cache_breakpoint_index": [{"index": 2, "ttl": "5m"}],
    }
    assert cache_lifetime_seconds(request) == 300
    request["cache_breakpoint_index"] = [{"index": 2, "ttl": "1h"}]
    assert cache_lifetime_seconds(request) == 3600
