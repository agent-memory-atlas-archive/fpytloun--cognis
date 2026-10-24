"""Bounded notification text; never include code, links or credential-bearing lines."""

from __future__ import annotations

import re


def notification_preview(content: str) -> str:
    """Produce plain presentation text from one exact completed reply."""
    if re.search(
        r"password|passwd|secret|credential|token|api.?key|authorization|"
        r"private.?key|recovery.?code|otp|bearer|sk-[A-Za-z0-9]|"
        r"[A-Za-z0-9_+/=-]{32,}",
        content,
        re.I,
    ):
        return ""
    text = re.sub(r"```.*?(?:```|$)", "", content[:8192], flags=re.S)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+|<[^>]*>|[`*_#>]", "", text)
    return " ".join(text.split())[:240]
