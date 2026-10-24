"""First-run state and configuration checks; no inference or tool execution."""

from __future__ import annotations

from typing import Any

from cognis.core.executor_policy import is_executor_row_usable, load_executor_policy
from cognis.core.executor_resolution import select_executor_for_agent
from cognis.ownership import SYSTEM_USER_EMAIL
from cognis.providers.llm.hosted import is_chat_model
from cognis.providers.llm.routing import COMPANION_ROUTES, EMBEDDING_ROUTES
from cognis.store.queries import (
    AgentReadinessSnapshot,
    get_user_ui_state_value,
    list_agent_readiness_snapshots,
    list_executors,
)

ONBOARDING_STATE_KEY = "ui.onboarding"


async def configuration_readiness(
    session_factory: Any,
    llm: Any,
    owner_email: str,
    *,
    agents: list[AgentReadinessSnapshot] | None = None,
) -> dict[str, bool]:
    """Check effective models and owner-visible executors, not record counts.

    This proves configuration only. Credentials, embedding dimensions, generation
    and tool execution require explicit functional verification.
    """
    if agents is not None and any(agent.owner_email != owner_email for agent in agents):
        raise ValueError("Readiness snapshot owner does not match the request")
    policy = await load_executor_policy(session_factory)
    async with session_factory() as session:
        executors = await list_executors(session, owner_email=owner_email, include_shared=True)
        if agents is None:
            agents = await list_agent_readiness_snapshots(session, owner_email)
        state = await get_user_ui_state_value(session, owner_email, ONBOARDING_STATE_KEY)

    def usable(executor: Any) -> bool:
        return bool(
            is_executor_row_usable(executor, policy, owner_email=owner_email)
            and executor.runtime_state in {"active", "degraded"}
            and executor.applied_config_version == executor.desired_config_version
            and executor.observed_tools
        )

    async def model_ready(
        role: str, *, model: str | None = None, provider_id: str | None = None
    ) -> bool:
        scope = SYSTEM_USER_EMAIL if role in COMPANION_ROUTES else owner_email
        try:
            resolved, provider = await llm.resolve_model_target(
                model, task_type=role, explicit_provider_id=provider_id, acting_user_email=scope
            )
            info = await llm.get_model_info(resolved, provider_id=provider, acting_user_email=scope)
        except ValueError:
            return False
        if role in EMBEDDING_ROUTES:
            return bool(info.supports_embedding)
        if role == "image_generation":
            return bool(info.supports_image_generation)
        if info.model_mode == "systemone":
            return role == "intaris_evaluation"
        if not is_chat_model(info.model_dump()):
            return False
        return bool(info.supports_tools) if role == "default" else True

    companion_ready = True
    for role in COMPANION_ROUTES:
        companion_ready = await model_ready(role) and companion_ready
    agent_ready = False
    for agent in agents:
        if agent.status != "active" or agent.agent_type != "primary":
            continue
        executor = select_executor_for_agent(
            executors, agent.execution, owner_email=owner_email, policy=policy
        )
        if executor is not None and usable(executor):
            config = agent.llm_config or {}
            if await model_ready(
                "default", model=config.get("model"), provider_id=config.get("provider_id")
            ):
                agent_ready = True
                break
    return {
        "companion_routes_configured": companion_ready,
        "agent_model_configured": await model_ready("default"),
        "image_generation_configured": await model_ready("image_generation"),
        "executor_tools_configured": any(usable(executor) for executor in executors),
        "agent_created": any(
            agent.status == "active" and agent.agent_type == "primary" for agent in agents
        ),
        "agent_ready": agent_ready,
        "onboarding_pending": (state or {}).get("status") not in {"completed", "dismissed"},
    }
