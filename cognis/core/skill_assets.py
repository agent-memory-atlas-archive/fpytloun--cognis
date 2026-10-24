"""Controller-owned version-pinned skill asset preparation."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from cognis.models.skill import SkillAssetRef


@dataclass
class PreparedSkillAssets:
    """Verified paths and optional runtime diagnostics, not skill definition metadata."""

    assets: list[dict[str, Any]] = field(default_factory=list)
    python_environment: dict[str, Any] | None = None
    warning: str | None = None


async def prepare_loaded_skill_assets(
    *,
    skill_id: str,
    version_id: str | None,
    asset_refs: list[SkillAssetRef],
    owner_email: str,
    executor: Any,
    artifact_store: Any,
) -> PreparedSkillAssets:
    """Preparation is optional infrastructure; failures must not hide instructions."""
    try:
        return await _prepare_loaded_skill_assets(
            skill_id=skill_id,
            version_id=version_id,
            asset_refs=asset_refs,
            owner_email=owner_email,
            executor=executor,
            artifact_store=artifact_store,
        )
    except Exception as exc:
        return PreparedSkillAssets(
            warning=(
                f"Asset/environment preparation incomplete: {type(exc).__name__}: {exc}. "
                "Assets might not be runnable. Correct the executor issue and reload the skill."
            )
        )


async def _prepare_loaded_skill_assets(
    *,
    skill_id: str,
    version_id: str | None,
    asset_refs: list[SkillAssetRef],
    owner_email: str,
    executor: Any,
    artifact_store: Any,
) -> PreparedSkillAssets:
    """Send the authorized current bundle to the selected executor, not its stale cache."""
    if not asset_refs:
        return PreparedSkillAssets()
    if executor is None or artifact_store is None or not version_id:
        raise ValueError("Skill assets require an authorized executor and artifact storage")
    assets = []
    for ref in asset_refs:
        content, _ = await artifact_store.async_load(
            ref.artifact_namespace, ref.artifact_object_id, ref.filename
        )
        assets.append(
            {
                "asset_id": ref.asset_id,
                "filename": ref.filename,
                "content_hash": ref.content_hash,
                "size_bytes": ref.size_bytes,
                "content_type": ref.content_type,
                "content_b64": base64.b64encode(content).decode("ascii"),
            }
        )
    response = await executor.rpc_call(
        "skill.assets.prepare",
        {
            "owner_email": owner_email,
            "skill_id": skill_id,
            "version_id": version_id,
            "assets": assets,
        },
        timeout=110,
    )
    manifest = response.get("asset_manifest")
    if (
        response.get("skill_id") != skill_id
        or response.get("version_id") != version_id
        or not isinstance(manifest, list)
        or len(manifest) != len(assets)
    ):
        raise ValueError("Executor returned an invalid skill asset manifest")
    result = []
    for expected, actual in zip(assets, manifest, strict=True):
        if (
            not isinstance(actual, dict)
            or any(
                actual.get(key) != expected[key]
                for key in ("asset_id", "filename", "content_hash", "size_bytes", "content_type")
            )
            or actual.get("version_id") != version_id
            or not isinstance(actual.get("local_path"), str)
            or not actual["local_path"]
        ):
            raise ValueError("Executor did not verify the requested skill asset")
        executor_id = getattr(executor, "executor_id", None)
        if not executor_id:
            executor_id = executor.handle.executor_id
        result.append({**actual, "executor_id": executor_id})
    environment = response.get("python_environment")
    if environment is not None:
        if (
            not isinstance(environment, dict)
            or not isinstance(environment.get("ready"), bool)
            or not isinstance(environment.get("python_path"), str)
        ):
            raise ValueError("Executor returned an invalid Python environment")
        environment = {**environment, "executor_id": executor_id}
    warning = None
    if environment is None and any(ref.filename.endswith(".py") for ref in asset_refs):
        warning = (
            "Python environment incomplete: executor did not report environment preparation. "
            "Assets might not be runnable. Update or correct the executor and reload the skill."
        )
    if environment is not None and not environment["ready"]:
        warning = (
            f"Python environment incomplete: {environment.get('error', 'unknown error')}. "
            "Assets might not be runnable. Correct the executor issue and reload the skill."
        )
    return PreparedSkillAssets(result, environment, warning)
