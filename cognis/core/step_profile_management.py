"""Workflow step-profile application operations shared by transports."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, TypedDict

from sqlalchemy import select

from cognis import json_codec as json
from cognis.api.common import api_exception
from cognis.api.models import StepProfileResponse
from cognis.core.management_access import ManagementActor
from cognis.core.step_profiles import (
    STEP_PROFILE_CUSTOM_SETTING_KEY,
    STEP_PROFILE_OVERRIDES_SETTING_KEY,
    StepProfileRegistry,
    serialize_step_profile_override,
)
from cognis.models.workflow import StepProfileConfig, StepProfileMode
from cognis.store.local_models import lock_local_model_dispatch_guard
from cognis.store.models import SystemWorkflowOverride, WorkflowRow
from cognis.store.queries import delete_setting, get_setting, upsert_setting

_REVISION_KEY = "internal.step_profile_revision"


class ProfileSnapshot(TypedDict):
    profiles: list[StepProfileResponse]
    revision: str


def response(registry: Any, definition: Any) -> StepProfileResponse:
    return StepProfileResponse(
        profile_id=definition.profile_id,
        name=definition.name,
        mode=str(definition.mode),
        config=definition.config.model_dump(mode="json"),
        has_override=registry.has_override(definition.profile_id),
        is_custom=registry.is_custom(definition.profile_id),
    )


async def ensure_unreferenced(session: Any, profile_id: str) -> None:
    definitions = await session.scalars(select(WorkflowRow.definition))
    for definition in definitions:
        steps = definition.get("steps", []) if isinstance(definition, dict) else []
        if isinstance(steps, list) and any(
            isinstance(step, dict) and step.get("step_profile_id") == profile_id for step in steps
        ):
            raise api_exception(409, "conflict", "Step profile is still used by a workflow")
    overrides = await session.scalars(select(SystemWorkflowOverride.step_overrides))
    for override in overrides:
        if isinstance(override, dict) and any(
            isinstance(step, dict) and step.get("step_profile_id") == profile_id
            for step in override.values()
        ):
            raise api_exception(
                409, "conflict", "Step profile is still used by a system workflow override"
            )


@dataclass(frozen=True)
class StepProfileManagement:
    session_factory: Any
    registry: Any

    async def _snapshot(self, session: Any) -> tuple[dict[str, dict[str, Any]], str]:
        snapshot: dict[str, Any] = {}
        documents: dict[str, dict[str, Any]] = {}
        for key in (STEP_PROFILE_CUSTOM_SETTING_KEY, STEP_PROFILE_OVERRIDES_SETTING_KEY):
            row = await get_setting(session, key)
            documents[key] = (
                dict(row.value) if row is not None and isinstance(row.value, dict) else {}
            )
            snapshot[key] = {
                "value": documents[key],
                "updated_at": row.updated_at.isoformat() if row is not None else None,
            }
        generation = await get_setting(session, _REVISION_KEY)
        snapshot[_REVISION_KEY] = generation.value if generation is not None else 0
        revision = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        return documents, revision

    async def read(self) -> ProfileSnapshot:
        async with self.session_factory() as session:
            await lock_local_model_dispatch_guard(session)
            documents, revision = await self._snapshot(session)
        registry = self._registry_snapshot(documents)
        return {
            "profiles": [
                response(registry, definition) for definition in registry.list_definitions()
            ],
            "revision": revision,
        }

    def _registry_snapshot(self, documents: dict[str, dict[str, Any]]) -> StepProfileRegistry:
        registry = StepProfileRegistry(self.session_factory)
        registry.load_configuration(
            documents[STEP_PROFILE_OVERRIDES_SETTING_KEY],
            documents[STEP_PROFILE_CUSTOM_SETTING_KEY],
        )
        return registry

    async def mutate(
        self,
        actor: ManagementActor,
        action: str,
        profile_id: str,
        payload: Any = None,
        *,
        expected_revision: str | None = None,
        preview: bool = False,
    ) -> Any:
        actor.require_admin()
        if not re.fullmatch(r"[a-zA-Z0-9:_-]{1,80}", profile_id):
            raise api_exception(400, "validation_error", "invalid profile_id")
        async with self.session_factory() as session:
            await lock_local_model_dispatch_guard(session)
            documents, revision = await self._snapshot(session)
            if expected_revision is not None and revision != expected_revision:
                raise api_exception(
                    409, "step_profile_conflict", "Step profiles changed; read again"
                )
            registry = self._registry_snapshot(documents)
            existing = registry.get_definition(profile_id)
            if action == "create":
                if existing is not None:
                    raise api_exception(409, "conflict", "Step profile already exists")
            elif existing is None:
                raise api_exception(404, "not_found", "Step profile not found")
            was_custom = action == "create" or registry.is_custom(profile_id)
            serialized = None
            if action != "reset":
                try:
                    serialized = serialize_step_profile_override(
                        name=payload.name
                        or (existing.name if existing is not None else profile_id),
                        mode=StepProfileMode(payload.mode),
                        config=StepProfileConfig.model_validate(payload.config),
                    )
                except (ValueError, TypeError) as exc:
                    raise api_exception(
                        400, "validation_error", "Invalid step profile configuration"
                    ) from exc
            key = (
                STEP_PROFILE_CUSTOM_SETTING_KEY
                if was_custom
                else STEP_PROFILE_OVERRIDES_SETTING_KEY
            )
            document = documents[key]
            if action == "create" and profile_id in document:
                raise api_exception(409, "conflict", "Step profile already exists")
            if action == "reset":
                if was_custom:
                    await ensure_unreferenced(session, profile_id)
                document.pop(profile_id, None)
            else:
                document[profile_id] = serialized
            if preview:
                return {
                    "preview": True,
                    "profile_id": profile_id,
                    "action": action,
                    "after": serialized,
                }
            if document:
                await upsert_setting(
                    session,
                    key=key,
                    value=document,
                    category="workflow",
                    updated_by=actor.email,
                )
            else:
                await delete_setting(session, key)
            generation = await get_setting(session, _REVISION_KEY)
            await upsert_setting(
                session,
                key=_REVISION_KEY,
                value=(generation.value if generation else 0) + 1,
                category="internal",
                updated_by=actor.email,
            )
            await session.commit()
            registry = self._registry_snapshot(documents)
        await self.registry.refresh()
        if action == "reset" and was_custom:
            assert existing is not None
            return StepProfileResponse(
                profile_id=existing.profile_id,
                name=existing.name,
                mode=str(existing.mode),
                config=existing.config.model_dump(mode="json"),
                has_override=False,
                is_custom=True,
            )
        return response(registry, registry.get_definition(profile_id))
