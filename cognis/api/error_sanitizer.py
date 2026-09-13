"""Helpers for safe client-facing error details.

These helpers are intentionally conservative. If a detail string cannot be
cleanly reduced to a short, obviously safe fragment, callers should fall back
to a category-only message.
"""

from __future__ import annotations

import re

_API_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"key-[A-Za-z0-9_-]+"),
    re.compile(r"(?i)(api[_ -]?key\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)((?:access[_ -]?token|token|password|secret)\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"https?://[^\s:@]+:[^\s@]+@"),
    # Signed-URL credentials. A provider error often echoes the attachment URL
    # it failed to fetch, and a Cognis signature (`?exp=...&sig=...`) or a
    # cloud presign parameter is directly usable until it expires. The
    # parameter name is kept so the redaction is recognizable; only the secret
    # value is removed. Expiry timestamps are left intact for debugging.
    re.compile(
        r"(?i)([?&](?:sig|signature|x-amz-signature|x-amz-credential"
        r"|x-amz-security-token|awsaccesskeyid)=)([^&\s#]+)"
    ),
]
_LONG_QUOTED_CONTENT = re.compile(r'(["\'])([^"\']{51,})\1')
_WHITESPACE = re.compile(r"\s+")
_MAX_DETAIL_LENGTH = 200


def sanitize_client_error_detail(
    value: str | Exception | None,
    *,
    fallback: str,
    max_length: int | None = _MAX_DETAIL_LENGTH,
) -> str:
    """Return a client-safe error detail string.

    Redaction and truncation are separate concerns. API responses keep the
    short default length, while callers that must preserve a complete provider
    diagnostic (for example a model error naming a required client version)
    pass ``max_length=None`` and rely on their own sink limits.
    """

    if value is None:
        return fallback

    message = str(value)
    for pattern in _API_KEY_PATTERNS:
        message = pattern.sub(r"\1[redacted]" if pattern.groups else "[redacted]", message)
    message = _LONG_QUOTED_CONTENT.sub("[redacted-content]", message)
    message = _WHITESPACE.sub(" ", message).strip()
    if not message:
        return fallback
    if max_length is not None and len(message) > max_length:
        message = message[: max_length - 3].rstrip() + "..."
    return message
