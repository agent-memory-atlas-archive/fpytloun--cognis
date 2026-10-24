"""Redact complete runtime evidence before any lossy projection.

This is a transport boundary, not a logger or an authorization classifier.
Credential-bearing strings are withheld in full: truncating them first can
destroy the syntax needed by downstream redactors.
"""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "secret_key",
    "private_key",
    "auth",
    "authorization",
    "credential",
    "credentials",
    "cookie",
    "set-cookie",
}
_CREDENTIAL_TEXT = re.compile(
    r"(?<!\S)(?:--user(?:=|\s+)|-u\s*)['\"]?[^:\s'\"]*:|"
    r"(?i:Bearer\s+\S+|Basic\s+\S+)|"
    r"(?i:(?:password|passwd|api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token|secret[_-]?key)\s*[:=])|"
    r"(?:[a-z]+://)[^/\s]+:[^@\s]+@|"
    r"sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|gh[ps]_[A-Za-z0-9]{36,}|"
    r"github_pat_[A-Za-z0-9_]{22,}|glpat-[A-Za-z0-9_-]{20,}|xox[bpras]-[A-Za-z0-9-]+|"
    r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"-----BEGIN (?:RSA )?PRIVATE KEY-----"
)
_ASSIGNMENT = re.compile(r"""(?<![\w])([A-Za-z_][\w.-]*)['"]?\s*[:=]""")
_AWS_SECRET = re.compile(r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])")


def _credential_key(key: str) -> bool:
    """Recognize credential components in environment, JSON and camel-case labels."""
    normalized = re.sub(r"([a-z])([A-Z])", r"\1_\2", key).lower()
    parts = set(re.split(r"[^a-z0-9]+", normalized))
    return normalized in _SENSITIVE_KEYS or bool(
        parts
        & {
            "password",
            "passwd",
            "pwd",
            "secret",
            "token",
            "credential",
            "credentials",
            "authorization",
            "cookie",
            "auth",
        }
        or "key" in parts
        and parts & {"api", "access", "private"}
    )


def _credential_scalar(value: str) -> bool:
    if _CREDENTIAL_TEXT.search(value) or any(
        _credential_key(match[1]) for match in _ASSIGNMENT.finditer(value)
    ):
        return True
    for match in _AWS_SECRET.finditer(value):
        candidate = match[0]
        if (
            not candidate.startswith("/")
            and candidate.count("/") <= 3
            and any(c.isupper() for c in candidate)
            and any(c.islower() for c in candidate)
            and any(c.isdigit() for c in candidate)
        ):
            return True
    return False


def redact_runtime_evidence(value: Any) -> Any:
    """Return a redacted copy; never require closing quotes for credential detection."""
    if isinstance(value, str):
        return "[REDACTED:credential-bearing-text]" if _credential_scalar(value) else value
    if isinstance(value, dict):
        return {
            key: "[REDACTED:credential]"
            if _credential_key(str(key))
            else redact_runtime_evidence(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_runtime_evidence(item) for item in value]
    return value
