"""Internal LLM transport interfaces and LiteLLM implementation."""

from __future__ import annotations

from typing import Any, Protocol

import litellm


def strip_controller_transport_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Remove Cognis-only routing metadata at the provider wire boundary."""

    # Reserved namespaces belong to controller tracing/routing, not upstream SDKs.
    return {
        key: value for key, value in kwargs.items() if not key.startswith(("cognis_", "_cognis_"))
    }


class ChatCompletionsTransport(Protocol):
    """Transport boundary for Chat Completions-compatible calls."""

    name: str

    async def completion(self, **kwargs: Any) -> Any:
        """Call a Chat Completions-compatible transport."""


class ResponsesTransport(Protocol):
    """Transport boundary for Responses-compatible calls."""

    name: str

    async def responses(self, **kwargs: Any) -> Any:
        """Call a Responses-compatible transport."""


class LLMTransport(ChatCompletionsTransport, ResponsesTransport, Protocol):
    """Transport that supports both major text-generation APIs."""


class LiteLLMTransport:
    """Thin adapter around LiteLLM network calls."""

    name = "litellm"

    @staticmethod
    def _request_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        from cognis.providers.llm.recovery import active_attempt_budget

        result = strip_controller_transport_kwargs(kwargs)
        budget = active_attempt_budget.get()
        if budget is not None:
            result.update(num_retries=0, max_retries=0)
            result["timeout"] = min(
                float(result.get("timeout") or budget.remaining), budget.remaining
            )
        return result

    async def completion(self, **kwargs: Any) -> Any:
        return await litellm.acompletion(**self._request_kwargs(kwargs))

    async def responses(self, **kwargs: Any) -> Any:
        return await litellm.aresponses(**self._request_kwargs(kwargs))
