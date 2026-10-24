"""Installation-scoped inference credentials for managed companion deployments."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

from cognis.store.models import InferenceCompanion


def write_companion_token(directory: Path, service: str, token: str) -> None:
    """Publish a credential atomically, without exposing Cognis's signing key."""
    if service not in {"intaris", "mnemory"}:
        raise ValueError("Unsupported companion")
    parent = directory / service
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=parent, prefix=".token-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(token + "\n")
        os.replace(temporary, parent / "token.jwt")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def provision_companion_tokens(
    directory: Path,
    session_factory: Any,
    auth_provider: Any,
) -> None:
    """Provision before companion readiness checks; preserve revoked identities."""
    for service in ("intaris", "mnemory"):
        async with session_factory() as session:
            row = await session.get(InferenceCompanion, service)
            if row is None:
                row = InferenceCompanion(service=service, token_version=0, enabled=True)
                session.add(row)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    row = await session.get(InferenceCompanion, service)
            if row is not None and row.enabled:
                token = auth_provider.sign_inference_companion_token(service, row.token_version)
                write_companion_token(directory, service, token)
