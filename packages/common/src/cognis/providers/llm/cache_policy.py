"""Provider-model cache policy, shared by controller and executor."""

import re
from typing import Any

from cognis.models.config import ModelInfo


def supported_cache_ttls(model_id: str, preset: str, supports_caching: bool) -> list[str]:
    if not supports_caching or "claude" not in model_id.lower():
        return []
    if preset == "anthropic":
        return ["5m", "1h"]
    if preset == "bedrock":
        # Bedrock's documented 1h support starts at the 4.5 generation.
        modern = re.search(
            r"claude-(?:opus|sonnet|haiku|fable|mythos)-(?:4-[5-8]|5(?:-|$))",
            model_id.lower(),
        )
        return ["5m", "1h"] if modern else ["5m"]
    # Other gateways may accept cache markers but not the extended TTL.
    return ["5m"]


def effective_cache_ttl(info: ModelInfo | None, *, primary_conversation: bool) -> str:
    supported = getattr(info, "supported_cache_ttls", None)
    if info is None or not supported:
        return "5m"
    requested = info.primary_cache_ttl if primary_conversation else info.auxiliary_cache_ttl
    return requested if requested in supported else "5m"


def primary_conversation(ctx: Any) -> bool:
    """Task/workflow context takes precedence over the executing agent's type."""
    agent = getattr(ctx, "executor_agent", None) or ctx.agent
    return (
        getattr(agent, "agent_type", None) == "primary"
        and not getattr(ctx, "task_id", None)
        and not getattr(ctx, "workflow_id", None)
        and not getattr(ctx, "workflow_step_scope", None)
    )


def apply_cache_ttl(value: Any, ttl: str) -> None:
    """Update existing cache markers in a request-local copy, never add new ones."""
    if isinstance(value, dict):
        control = value.get("cache_control")
        if isinstance(control, dict) and control.get("type") == "ephemeral":
            control["ttl"] = ttl
        for key, child in value.items():
            if key != "cache_control":
                apply_cache_ttl(child, ttl)
    elif isinstance(value, (list, tuple)):
        for child in value:
            apply_cache_ttl(child, ttl)


def cache_breakpoints(value: Any, ttl: str) -> Any:
    if isinstance(value, int):
        return [{"index": value, "ttl": ttl}]
    if isinstance(value, list):
        return [
            {**point, "ttl": ttl} if isinstance(point, dict) else {"index": point, "ttl": ttl}
            for point in value
        ]
    return value
