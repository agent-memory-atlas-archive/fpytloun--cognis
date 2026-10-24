"""Tests for the Intaris MCP listing cache."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from cognis.providers.guardrails.mcp_listing_cache import MCPListingCache


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_listing_is_cached_within_ttl_and_reloaded_after() -> None:
    clock = _Clock()
    cache = MCPListingCache(ttl_seconds=15, clock=clock)
    calls = 0

    async def load() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        return [{"name": f"t{calls}"}]

    assert await cache.get("k", load) == [{"name": "t1"}]
    assert await cache.get("k", load) == [{"name": "t1"}]
    clock.now += 16
    assert await cache.get("k", load) == [{"name": "t2"}]
    assert calls == 2


@pytest.mark.asyncio
async def test_concurrent_misses_share_one_load() -> None:
    cache = MCPListingCache()
    calls = 0
    release = asyncio.Event()

    async def load() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        await release.wait()
        return [{"name": "t"}]

    waiters = [asyncio.create_task(cache.get("k", load)) for _ in range(10)]
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*waiters)
    assert calls == 1
    assert all(result == [{"name": "t"}] for result in results)
    # Callers get independent list objects.
    results[0].append({"name": "mutated"})
    assert await cache.get("k", load) == [{"name": "t"}]


@pytest.mark.asyncio
async def test_failures_are_not_cached() -> None:
    cache = MCPListingCache()
    calls = 0

    async def load() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("down")
        return [{"name": "t"}]

    with pytest.raises(RuntimeError):
        await cache.get("k", load)
    assert await cache.get("k", load) == [{"name": "t"}]


@pytest.mark.asyncio
async def test_keys_are_isolated_per_user() -> None:
    cache = MCPListingCache()

    async def load_a() -> list[dict[str, Any]]:
        return [{"name": "a"}]

    async def load_b() -> list[dict[str, Any]]:
        return [{"name": "b"}]

    assert await cache.get(("tools", "a@x"), load_a) == [{"name": "a"}]
    assert await cache.get(("tools", "b@x"), load_b) == [{"name": "b"}]


class _FakeAuth:
    def sign_service_jwt(self, subject: str, *_args: Any, **_kwargs: Any) -> str:
        return f"jwt-for-{subject}"


@pytest.mark.asyncio
async def test_provider_caches_mcp_tools_per_current_user() -> None:
    import httpx

    from cognis.providers.guardrails.intaris import IntarisProvider
    from cognis.runtime_context import current_user_email

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers["Authorization"].removeprefix("Bearer jwt-for-")
        seen.append(auth)
        return httpx.Response(200, json={"tools": [{"name": f"tool-{auth}"}]})

    provider = IntarisProvider("http://intaris.test", _FakeAuth())
    provider.client = httpx.AsyncClient(
        base_url="http://intaris.test", transport=httpx.MockTransport(handler)
    )

    async def list_as(email: str) -> list[dict[str, Any]]:
        token = current_user_email.set(email)
        try:
            return await provider.list_mcp_tools()
        finally:
            current_user_email.reset(token)

    results = await asyncio.gather(
        *(list_as(email) for email in ["a@x", "b@x", "a@x", "b@x", "a@x"])
    )
    assert [r[0]["name"] for r in results] == [
        "tool-a@x",
        "tool-b@x",
        "tool-a@x",
        "tool-b@x",
        "tool-a@x",
    ]
    assert sorted(seen) == ["a@x", "b@x"]
    await provider.client.aclose()
