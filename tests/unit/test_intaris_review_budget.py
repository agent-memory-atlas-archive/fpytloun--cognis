"""The evaluation transport must outlive the bounded multi-stage review."""

from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest

from cognis.providers.guardrails.intaris import IntarisProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [65.0, 90.0])
async def test_review_timeout_applies_only_to_evaluation(budget):
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "decision": "approve",
                "risk": "low",
                "reasoning": "Authorized read.",
                "call_id": str(uuid4()),
            },
        )

    provider = IntarisProvider(
        "https://intaris.test", auth_provider=object(), evaluation_timeout=budget
    )
    provider._headers = Mock(return_value={})
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(
        base_url=provider.base_url, timeout=10, transport=httpx.MockTransport(respond)
    )
    try:
        result = await provider.evaluate(
            session_id=str(uuid4()), tool_name="read", arguments={"file_path": "/repo/README.md"}
        )
        assert result.decision == "approve"
        assert seen[0].extensions["timeout"]["read"] == budget
        assert provider.client.timeout.read == 10
    finally:
        await provider.client.aclose()


def test_nonpositive_review_transport_budget_is_rejected():
    with pytest.raises(ValueError, match="evaluation_timeout"):
        IntarisProvider("https://intaris.test", auth_provider=object(), evaluation_timeout=0)
