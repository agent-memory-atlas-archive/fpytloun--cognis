"""Outcome policy synchronization preserves the authenticated agent identity."""

from types import SimpleNamespace

import httpx
import pytest

from cognis.providers.guardrails.intaris import IntarisProvider


@pytest.mark.asyncio
async def test_yolo_read_and_patch_use_shared_agent_identity() -> None:
    identities: list[tuple[str, str, str]] = []
    policies: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/session/session-1"
        identities.append(
            (
                request.headers["X-Agent-Id"],
                request.headers["X-Agent-Owner"],
                request.headers["Authorization"],
            )
        )
        if request.method == "PATCH":
            import json

            policies.append(json.loads(request.content)["policy"])
        return httpx.Response(
            200,
            json={
                "session_id": "session-1",
                "user_id": "participant@example.com",
                "agent_id": "shared-agent",
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "policy": policies[-1] if policies else {"maximum_outcome": "escalate"},
            },
        )

    def sign_service_jwt(
        subject: str, agent_id: str, audience: list[str], *, agent_owner_email: str
    ) -> str:
        assert audience == ["intaris"]
        return f"{subject}:{agent_id}:{agent_owner_email}"

    provider = IntarisProvider(
        "http://intaris.test", SimpleNamespace(sign_service_jwt=sign_service_jwt)
    )
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="http://intaris.test", transport=httpx.MockTransport(respond)
    )
    try:
        await provider.get_session(
            "session-1",
            user_email="participant@example.com",
            agent_id="shared-agent",
            agent_owner_email="owner@example.com",
        )
        await provider.update_session_policy(
            "session-1",
            user_id="participant@example.com",
            agent_id="shared-agent",
            agent_owner_email="owner@example.com",
            policy={"maximum_outcome": "approve"},
        )
    finally:
        await provider.client.aclose()

    assert policies == [{"maximum_outcome": "approve"}]
    assert (
        identities
        == [
            (
                "shared-agent",
                "owner@example.com",
                "Bearer participant@example.com:shared-agent:owner@example.com",
            )
        ]
        * 2
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_maximum", ["approve", None])
async def test_create_verifies_stored_maximum_not_intention_ack(
    stored_maximum: str | None,
) -> None:
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        if request.method == "POST":
            assert request.url.path == "/api/v1/intention"
            return httpx.Response(200, json={"ok": True})
        assert request.url.path == "/api/v1/session/session-1"
        return httpx.Response(
            200, json={"policy": {"maximum_outcome": stored_maximum} if stored_maximum else {}}
        )

    provider = IntarisProvider(
        "http://intaris.test",
        SimpleNamespace(sign_service_jwt=lambda *args, **kwargs: "signed-token"),
    )
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url="http://intaris.test", transport=httpx.MockTransport(respond)
    )
    try:
        if stored_maximum is None:
            with pytest.raises(ValueError, match="did not acknowledge"):
                await provider.create_session(
                    "session-1",
                    "task",
                    "agent-1",
                    "user@example.com",
                    policy={"maximum_outcome": "approve"},
                )
        else:
            await provider.create_session(
                "session-1",
                "task",
                "agent-1",
                "user@example.com",
                policy={"maximum_outcome": "approve"},
            )
    finally:
        await provider.client.aclose()

    assert requests[0:2] == ["POST", "GET"]
