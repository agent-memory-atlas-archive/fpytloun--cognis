"""Shared session failure classification, independent of admission or delivery."""

from __future__ import annotations

import re
from typing import Any

SESSION_TRANSIENT_MAX_ATTEMPTS = 120


def step_failure_traits(output: Any) -> tuple[bool, bool]:
    """Return transient/database-conflict flags using the normal turn policy."""
    text = str(getattr(output, "error", "") or "").lower()
    metadata = getattr(output, "metadata", None)
    model_error = metadata.get("model_error") if isinstance(metadata, dict) else None
    structured = model_error.get("transient") if isinstance(model_error, dict) else None
    conflict = any(
        marker in text
        for marker in (
            "deadlock detected",
            "deadlockdetectederror",
            "serializationerror",
            "could not serialize access",
        )
    )
    transient = (
        structured
        if isinstance(structured, bool)
        else conflict
        or any(
            marker in text
            for marker in (
                "circuit breaker",
                "dns",
                "connection reset",
                "temporar",
                "timeout",
                "timed out",
            )
        )
        or re.search(r"\b(?:http(?:/\d(?:\.\d)?)?|status(?:_code)?)\s*[:=/ -]\s*5\d\d\b", text)
        is not None
    )
    return bool(transient), conflict
