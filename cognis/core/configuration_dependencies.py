"""Reject configuration deletions that would orphan persisted consumers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from cognis.api.common import api_exception
from cognis.core.executor_resolution import labels_match
from cognis.store.models import (
    Agent,
    InferenceRoute,
    LLMProvider,
    LocalModelTargetStatus,
    ModelRouting,
    SystemAgentOverride,
)


def _contains(value: Any, reference: str, *, qualified: bool = False) -> bool:
    if isinstance(value, dict):
        return any(_contains(item, reference, qualified=qualified) for item in value.values())
    if isinstance(value, list):
        return any(_contains(item, reference, qualified=qualified) for item in value)
    return isinstance(value, str) and (
        value == reference or (qualified and value.startswith(reference + "/"))
    )


async def assert_provider_unreferenced(session: Any, provider_id: str) -> None:
    """No cascades or disclosure of another user's dependency configuration."""
    for config in await session.scalars(select(InferenceRoute.config)):
        if _contains(config, provider_id, qualified=True):
            raise api_exception(
                409, "provider_dependencies", "Provider is referenced by an inference route"
            )
    for row in await session.execute(select(ModelRouting.provider_id, ModelRouting.model)):
        if any(_contains(value, provider_id, qualified=True) for value in row):
            raise api_exception(
                409, "provider_dependencies", "Provider is referenced by task routing"
            )
    for columns in (
        (Agent.llm_config, Agent.agent_profiles),
        (SystemAgentOverride.llm_config_override, SystemAgentOverride.agent_profiles_override),
    ):
        for row in await session.execute(select(*columns)):
            if any(_contains(value, provider_id, qualified=True) for value in row):
                raise api_exception(
                    409, "provider_dependencies", "Provider is referenced by an agent"
                )


async def assert_executor_unreferenced(session: Any, executor: Any) -> None:
    executor_id = executor.executor_id
    if await session.scalar(
        select(LocalModelTargetStatus.deployment_id)
        .where(LocalModelTargetStatus.executor_id == executor_id)
        .limit(1)
    ):
        raise api_exception(409, "executor_dependencies", "Executor has local-model deployments")
    for config in await session.scalars(select(LLMProvider.config)):
        config = config if isinstance(config, dict) else {}
        selector = config.get("executor_labels")
        if config.get("executor_id") == executor_id or (
            isinstance(selector, dict)
            and selector
            and labels_match(executor.labels or {}, selector)
        ):
            raise api_exception(
                409, "executor_dependencies", "Executor is selected by an LLM provider"
            )
    for column in (Agent.execution, SystemAgentOverride.execution_override):
        for config in await session.scalars(select(column)):
            if _contains(config, executor_id):
                raise api_exception(
                    409, "executor_dependencies", "Executor is assigned to an agent"
                )
