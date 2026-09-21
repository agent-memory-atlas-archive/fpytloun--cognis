"""Caller-scoped target discovery and validation for orchestration tools."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from cognis.core.agent_profiles import agent_profile_options
from cognis.models.agent import (
    AgentDefinition,
    AgentDelegationPolicy,
    PrimaryDelegationPolicy,
    SystemDelegationPolicy,
)


class OrchestrationTargetMode(StrEnum):
    """Supported orchestration target domains."""

    DELEGATE = "delegate"
    MANAGED = "managed"


class OrchestrationTargetError(RuntimeError):
    """Stable target-domain rejection raised before orchestration creates work."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class OrchestrationTarget:
    """Model-safe metadata for one currently eligible target."""

    agent_id: str
    name: str
    description: str
    agent_type: str
    is_system: bool
    profiles: tuple[dict[str, str | bool], ...]

    @classmethod
    def from_agent(cls, agent: AgentDefinition) -> OrchestrationTarget:
        return cls(
            agent_id=agent.agent_id,
            name=agent.display_name or agent.name,
            description=agent.description or "",
            agent_type=agent.agent_type,
            is_system=agent.is_system,
            profiles=tuple(agent_profile_options(agent)),
        )

    def as_dynamic_option(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "agent_type": self.agent_type,
            "is_system": self.is_system,
            "profiles": [dict(profile) for profile in self.profiles],
        }


@dataclass(frozen=True, slots=True)
class OrchestrationTargetSnapshot:
    """Discovery snapshot used consistently for one controller turn."""

    delegate: tuple[OrchestrationTarget, ...] = ()
    managed: tuple[OrchestrationTarget, ...] = ()

    def for_mode(self, mode: OrchestrationTargetMode) -> tuple[OrchestrationTarget, ...]:
        return self.delegate if mode is OrchestrationTargetMode.DELEGATE else self.managed


def effective_delegation_policy(agent: AgentDefinition) -> AgentDelegationPolicy:
    """Return the runtime policy, preserving the legacy master switch."""

    permissions = agent.permissions
    if permissions is not None and permissions.delegation is not None:
        return permissions.delegation
    enabled = permissions.can_delegate if permissions is not None else True
    return AgentDelegationPolicy(
        enabled=enabled,
        primary=PrimaryDelegationPolicy(enabled=enabled, max_managed_depth=1),
        system=SystemDelegationPolicy(enabled=enabled),
    )


def managed_depth_limit(agent: AgentDefinition) -> int:
    """Return the configured managed-chain limit for a root controller."""

    policy = effective_delegation_policy(agent)
    if not policy.enabled or not policy.primary.enabled:
        return 0
    return policy.primary.max_managed_depth


class OrchestrationTargetService:
    """Resolve effective targets from the registry without semantic routing heuristics."""

    def __init__(self, agent_registry: Any) -> None:
        self._registry = agent_registry

    async def snapshot(
        self,
        *,
        controller_agent: AgentDefinition,
        user_email: str,
        managed_depth: int = 0,
        inherited_managed_depth_limit: int | None = None,
    ) -> OrchestrationTargetSnapshot:
        policy = effective_delegation_policy(controller_agent)
        if not policy.enabled:
            return OrchestrationTargetSnapshot()
        visible = await self._registry.list_all(
            owner_email=user_email,
            include_hidden=False,
            include_system=True,
            include_disabled=False,
        )
        allowed_ids = None if policy.allowed_agent_ids is None else set(policy.allowed_agent_ids)
        depth_limit = (
            policy.primary.max_managed_depth
            if inherited_managed_depth_limit is None
            else inherited_managed_depth_limit
        )
        managed_creation_allowed = policy.primary.enabled and managed_depth < depth_limit

        delegate: list[OrchestrationTarget] = []
        managed: list[OrchestrationTarget] = []
        for agent in visible:
            if agent.hidden or agent.disabled or agent.status != "active":
                continue
            if agent.agent_type == "secondary":
                if (
                    policy.system.enabled
                    and agent.is_system
                    and (allowed_ids is None or agent.agent_id in allowed_ids)
                ):
                    delegate.append(OrchestrationTarget.from_agent(agent))
                continue
            target_policy = effective_delegation_policy(agent)
            allowed_controllers = target_policy.primary.allowed_controller_agent_ids
            is_self = agent.agent_id == controller_agent.agent_id
            if (
                managed_creation_allowed
                and agent.agent_type == "primary"
                and not agent.is_system
                and (is_self or allowed_ids is None or agent.agent_id in allowed_ids)
                and (
                    is_self
                    or allowed_controllers is None
                    or controller_agent.agent_id in allowed_controllers
                )
            ):
                managed.append(OrchestrationTarget.from_agent(agent))

        return OrchestrationTargetSnapshot(
            delegate=tuple(sorted(delegate, key=lambda target: target.agent_id)),
            managed=tuple(sorted(managed, key=lambda target: target.agent_id)),
        )

    async def require(
        self,
        mode: OrchestrationTargetMode,
        *,
        target_agent_id: str | None,
        controller_agent: AgentDefinition,
        user_email: str,
        managed_depth: int = 0,
        inherited_managed_depth_limit: int | None = None,
    ) -> AgentDefinition:
        normalized = str(target_agent_id or "").strip()
        if not normalized:
            code = (
                "delegate_target_required"
                if mode is OrchestrationTargetMode.DELEGATE
                else "managed_target_required"
            )
            raise OrchestrationTargetError(
                code=code,
                message=f"agent_id is required for {mode.value} orchestration.",
            )

        snapshot = await self.snapshot(
            controller_agent=controller_agent,
            user_email=user_email,
            managed_depth=managed_depth,
            inherited_managed_depth_limit=inherited_managed_depth_limit,
        )
        if normalized not in {target.agent_id for target in snapshot.for_mode(mode)}:
            code = (
                "delegate_target_not_eligible"
                if mode is OrchestrationTargetMode.DELEGATE
                else "managed_target_not_eligible"
            )
            guidance = (
                "Use an eligible secondary specialist returned by the delegate target catalog."
                if mode is OrchestrationTargetMode.DELEGATE
                else "Use an eligible primary non-system agent returned by the managed target catalog."
            )
            raise OrchestrationTargetError(
                code=code,
                message=f"Agent '{normalized}' is not an eligible {mode.value} target. {guidance}",
            )

        target = await self._registry.get(normalized, owner_email=user_email)
        if (
            target is None
            or target.hidden
            or target.disabled
            or target.status != "active"
            or (
                mode is OrchestrationTargetMode.DELEGATE
                and (target.agent_type != "secondary" or not target.is_system)
            )
            or (
                mode is OrchestrationTargetMode.MANAGED
                and (target.agent_type != "primary" or target.is_system)
            )
        ):
            code = (
                "delegate_target_not_eligible"
                if mode is OrchestrationTargetMode.DELEGATE
                else "managed_target_not_eligible"
            )
            raise OrchestrationTargetError(
                code=code,
                message=f"Agent '{normalized}' is no longer an eligible {mode.value} target.",
            )
        return cast(AgentDefinition, target)
