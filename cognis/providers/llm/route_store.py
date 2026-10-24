"""Named route persistence and role inheritance, shared by agents and proxy."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognis.ownership import SYSTEM_USER_EMAIL
from cognis.providers.llm.recovery_policy import NamedRouteConfig
from cognis.providers.llm.routing import (
    COMPANION_DEFAULTS,
    COMPANION_ROUTES,
    INHERIT_COMPANION_MODEL,
    route_chain,
)
from cognis.store.models import (
    Agent,
    InferenceBinding,
    InferenceRoute,
    ModelRouting,
    SystemAgentOverride,
)


@dataclass(frozen=True)
class NamedRoute:
    route_id: str
    owner: str
    revision: int
    config: NamedRouteConfig


@dataclass(frozen=True)
class RoleSelection:
    model: str
    provider_id: str | None
    owner: str
    reasoning_effort: str | None


class InferenceRouteStore:
    """No inference or external I/O runs inside these short DB operations."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def list(self, owner: str) -> list[NamedRoute]:
        """List visible routes, with private names shadowing global names."""
        async with self.sessions() as session:
            rows = list(
                (
                    await session.scalars(
                        select(InferenceRoute)
                        .where(InferenceRoute.owner_email.in_({owner, SYSTEM_USER_EMAIL}))
                        .order_by(
                            (InferenceRoute.owner_email == SYSTEM_USER_EMAIL).asc(),
                            InferenceRoute.name,
                        )
                    )
                ).all()
            )
        result: dict[str, NamedRoute] = {}
        for row in rows:
            result.setdefault(row.name, self._route(row))
        return list(result.values())

    async def get(self, reference: str, owner: str) -> NamedRoute:
        """Resolve only an authorized named reference, without admin bypass."""
        if not reference.startswith("cognis/"):
            raise ValueError("Expected a cognis/<name> route")
        name = reference.removeprefix("cognis/")
        routes = await self.list(owner)
        for route in routes:
            if route.config.name == name:
                return route
        raise ValueError("Unknown or unavailable inference route")

    async def save(
        self,
        config: NamedRouteConfig,
        *,
        owner: str,
        route_id: str | None = None,
        expected_revision: int | None = None,
    ) -> NamedRoute:
        """Create or compare-and-swap an owner-scoped validated route."""
        async with self.sessions() as session:
            if route_id is None:
                row = InferenceRoute(
                    route_id=f"iroute_{uuid.uuid4().hex}",
                    owner_email=owner,
                    name=config.name,
                    revision=1,
                    config=config.model_dump(mode="json"),
                )
                session.add(row)
                await session.flush()
                result = self._route(row)
            else:
                if expected_revision is None:
                    raise ValueError("An expected revision is required")
                current = await session.get(InferenceRoute, route_id)
                if current is None or current.owner_email != owner:
                    raise ValueError("Inference route not found or not owned")
                if current.name != config.name:
                    await self.assert_unreferenced(session, current)
                result_row = await session.execute(
                    update(InferenceRoute)
                    .where(
                        InferenceRoute.route_id == route_id,
                        InferenceRoute.owner_email == owner,
                        InferenceRoute.revision == expected_revision,
                    )
                    .values(
                        name=config.name,
                        config=config.model_dump(mode="json"),
                        revision=expected_revision + 1,
                    )
                )
                if cast(CursorResult[Any], result_row).rowcount != 1:
                    raise ValueError("Inference route changed or is not owned by this user")
                result = NamedRoute(route_id, owner, expected_revision + 1, config)
            await session.commit()
            return result

    @staticmethod
    async def assert_unreferenced(session: AsyncSession, route: InferenceRoute) -> None:
        """Do not orphan configured consumers or active session affinity."""
        reference = f"cognis/{route.name}"
        private_owners = set(
            await session.scalars(
                select(InferenceRoute.owner_email).where(
                    InferenceRoute.name == route.name,
                    InferenceRoute.owner_email != SYSTEM_USER_EMAIL,
                )
            )
        )

        def resolves_to_route(owner: str) -> bool:
            if route.owner_email != SYSTEM_USER_EMAIL:
                return owner == route.owner_email
            return owner not in private_owners

        role_owners = await session.scalars(
            select(ModelRouting.owner_email).where(ModelRouting.model == reference)
        )
        if any(resolves_to_route(owner) for owner in role_owners):
            raise ValueError("Route is referenced by model routing; replace it first")
        if await session.scalar(
            select(InferenceBinding.binding_key)
            .where(InferenceBinding.reference == route.route_id)
            .limit(1)
        ):
            raise ValueError("Route has session bindings; retain its name")

        def contains(value: Any) -> bool:
            if isinstance(value, dict):
                return any(contains(item) for item in value.values())
            if isinstance(value, list):
                return any(contains(item) for item in value)
            return isinstance(value, str) and value == reference

        for columns in (
            (Agent.owner_email, Agent.llm_config, Agent.agent_profiles),
            (
                SystemAgentOverride.owner_email,
                SystemAgentOverride.llm_config_override,
                SystemAgentOverride.agent_profiles_override,
            ),
        ):
            for row in await session.execute(select(*columns)):
                if resolves_to_route(row[0]) and any(contains(value) for value in row[1:]):
                    raise ValueError("Route is referenced by an agent; replace it first")

    async def role(self, role: str, owner: str) -> RoleSelection | None:
        """Resolve companion restrictions and effort inheritance in one place."""
        global_only = role in {*COMPANION_DEFAULTS, *COMPANION_ROUTES}
        if global_only:
            owner = SYSTEM_USER_EMAIL
        owners = list(dict.fromkeys([owner, SYSTEM_USER_EMAIL]))
        reasoning: str | None = None
        selected: ModelRouting | None = None
        async with self.sessions() as session:
            for candidate in route_chain(role):
                for route_owner in owners:
                    row = (
                        await session.scalars(
                            select(ModelRouting).where(
                                ModelRouting.owner_email == route_owner,
                                ModelRouting.task_type == candidate,
                            )
                        )
                    ).one_or_none()
                    if row is None:
                        continue
                    if reasoning is None:
                        reasoning = (row.config or {}).get("reasoning_effort")
                    if selected is None and row.model != INHERIT_COMPANION_MODEL:
                        selected = row
                    break
        if selected is None:
            if global_only:
                raise ValueError("Configure global companion models in Settings → Routing")
            return None
        return RoleSelection(selected.model, selected.provider_id, owner, reasoning)

    @staticmethod
    def _route(row: InferenceRoute) -> NamedRoute:
        return NamedRoute(
            row.route_id,
            row.owner_email,
            row.revision,
            NamedRouteConfig.model_validate(row.config),
        )
