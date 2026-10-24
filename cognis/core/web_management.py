"""Shared readiness checks for web backend configuration."""

from __future__ import annotations

from typing import Any

from cognis.api.common import api_exception
from cognis.ownership import SYSTEM_USER_EMAIL
from cognis.store.queries import get_setting_value


async def configured_web_backends(session: Any, secrets: Any) -> dict[str, bool]:
    configured = {"tavily": False, "brave": False}
    if secrets is not None:
        for backend in configured:
            try:
                await secrets.get_secret(f"{backend}_api_key", SYSTEM_USER_EMAIL)
                configured[backend] = True
            except Exception:
                pass
    url = await get_setting_value(session, "web.searxng_url", "")
    configured["searxng"] = bool(isinstance(url, str) and url.strip())
    return configured


async def validate_web_setting(session: Any, secrets: Any, key: str, value: Any) -> None:
    if key not in {"web.backend", "web.search_backend", "web.fetch_backend"}:
        return
    configured = await configured_web_backends(session, secrets)
    available = ["direct"]
    if key == "web.fetch_backend":
        available.append("browser")
    for backend in ("tavily", "brave", "searxng"):
        if key == "web.fetch_backend" and backend != "tavily":
            continue
        if configured[backend] and await get_setting_value(session, f"web.{backend}_enabled", True):
            available.append(backend)
    if value not in available:
        raise api_exception(400, "validation_error", "Web backend is not configured and enabled")
