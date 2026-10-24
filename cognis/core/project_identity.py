"""Stable, validated project accent colors without a data migration."""

import re
from typing import Any

_COLORS = ("#38bdf8", "#a78bfa", "#34d399", "#fbbf24", "#fb7185", "#22d3ee", "#f472b6")


def project_color(project_id: str, metadata: Any = None) -> str:
    value = metadata.get("color") if isinstance(metadata, dict) else None
    if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value.lower()
    return _COLORS[sum(project_id.encode("utf-8")) % len(_COLORS)]
