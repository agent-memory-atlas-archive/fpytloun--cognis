"""Typed, non-retryable Intaris evaluation conflicts."""

from __future__ import annotations

import re
from typing import Any


class EvaluationConflict(Exception):
    """A failed admission, never an authorization to execute a tool."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        # Keep exception logging content-free.
        super().__init__(f"Intaris evaluation conflict ({code})")

    @classmethod
    def from_payload(cls, payload: Any) -> EvaluationConflict:
        """Decode current structured detail and older string-detail responses."""
        detail = payload.get("detail") if isinstance(payload, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
        if not isinstance(code, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is None:
            code = "evaluation_conflict"
        message = detail.get("message") if isinstance(detail, dict) else detail
        if not isinstance(message, str) or not message.strip():
            message = "Intaris could not admit this tool call."
        return cls(code, " ".join(message.split())[:300])
