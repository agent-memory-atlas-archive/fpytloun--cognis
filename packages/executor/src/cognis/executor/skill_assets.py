"""Prepare controller-authorized skill assets without configure-time snapshots."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import os
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any


async def prepare_skill_assets(params: dict[str, Any]) -> dict[str, Any]:
    """Verify and atomically cache a version-pinned bundle on this executor."""
    result = await asyncio.to_thread(_prepare_skill_assets, params)
    scripts = {
        asset["filename"]: base64.b64decode(asset["content_b64"], validate=True)
        for asset in params["assets"]
        if asset["filename"].endswith(".py")
    }
    if scripts:
        from cognis.executor.skill_python import prepare_python_environment

        path = Path(result["asset_manifest"][0]["local_path"])
        relative = PurePosixPath(result["asset_manifest"][0]["filename"])
        root = path.parents[len(relative.parts) - 1].parent
        data_dir = Path(os.environ.get("COGNIS_DATA_DIR") or "~/.cognis").expanduser().resolve()
        descriptor = _open_cache_directory(data_dir, root)
        try:
            result["python_environment"] = await prepare_python_environment(
                root, scripts, descriptor
            )
        finally:
            os.close(descriptor)
    return result


def _prepare_skill_assets(params: dict[str, Any]) -> dict[str, Any]:
    if os.name != "posix":
        raise ValueError("Skill asset preparation requires a POSIX executor (Linux or macOS)")
    skill_id = str(params["skill_id"])
    version_id = str(params["version_id"])
    owner_email = str(params["owner_email"])
    if not skill_id or not version_id or not owner_email:
        raise ValueError("Skill asset preparation requires owner, skill, and version")
    assets = params["assets"]
    if not isinstance(assets, list):
        raise ValueError("Skill assets must be a list")
    verified: list[tuple[dict[str, Any], bytes, PurePosixPath]] = []
    filenames: set[str] = set()
    for asset in assets:
        filename = str(asset["filename"])
        relative = PurePosixPath(filename)
        if (
            not filename
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in filename.split("/"))
            or "\\" in filename
            or ":" in filename
            or filename in filenames
        ):
            raise ValueError("Unsafe or duplicate skill asset filename")
        filenames.add(filename)
        expected_hash = str(asset["content_hash"])
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise ValueError("Skill asset requires a SHA-256 hash")
        content = base64.b64decode(asset["content_b64"], validate=True)
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise ValueError("Skill asset hash mismatch")
        if len(content) != asset["size_bytes"]:
            raise ValueError("Skill asset size mismatch")
        verified.append((asset, content, relative))

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    data_dir = Path(os.environ.get("COGNIS_DATA_DIR") or "~/.cognis").expanduser().resolve()
    root = data_dir / "skill_assets" / digest(owner_email) / digest(skill_id) / digest(version_id)
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for asset, content, relative in verified:
        path = root.joinpath(*relative.parts)
        directory_fd = _open_cache_directory(data_dir, path.parent)
        try:
            _write_verified_asset(directory_fd, path.name, content, asset["content_hash"])
        finally:
            os.close(directory_fd)
        manifest.append(
            {
                key: asset[key]
                for key in ("asset_id", "filename", "content_hash", "size_bytes", "content_type")
            }
            | {"local_path": str(path), "version_id": version_id}
        )
    return {"skill_id": skill_id, "version_id": version_id, "asset_manifest": manifest}


def _open_cache_directory(root: Path, target: Path) -> int:
    """Walk with pinned directory descriptors so symlink swaps cannot escape."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in target.relative_to(root).parts:
            with contextlib.suppress(FileExistsError):
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _write_verified_asset(directory_fd: int, name: str, content: bytes, expected_hash: str) -> None:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    else:
        with os.fdopen(descriptor, "rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == expected_hash:
                return
    temporary = f".asset-{uuid.uuid4().hex}"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        mode=0o600,
        dir_fd=directory_fd,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory_fd)
