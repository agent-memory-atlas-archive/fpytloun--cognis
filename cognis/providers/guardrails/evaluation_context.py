"""Final Intaris context projection; never trim action or authority fields."""

from __future__ import annotations

import copy
import json
from typing import Any

# Deployed EvaluateRequest contract: compact JSON characters, ASCII escaped.
CONTEXT_LIMIT = 8192
_MARKER = "[TRUNCATED]"


def serialized_size(value: Any) -> int:
    """Use the receiving validator's exact serialized-size convention."""
    return len(json.dumps(value, separators=(",", ":"), default=str))


class EvaluationContextTooLarge(ValueError):
    """Protected context alone exceeds the protocol limit; fail closed."""

    def __init__(self, size: int) -> None:
        self.size = size
        super().__init__(
            f"Intaris protected context exceeds serialized limit: size={size}, limit={CONTEXT_LIMIT}"
        )


def _middle_fit(text: str, budget: int) -> str:
    """Fit an explanatory string including its marker, quotes and escaping."""
    if serialized_size(text) <= budget:
        return text
    if budget < serialized_size(_MARKER):
        return _MARKER
    lo, hi = 0, len(text)
    while lo < hi:
        keep = (lo + hi + 1) // 2
        head = (keep + 1) // 2
        tail = keep // 2
        candidate = text[:head] + _MARKER + (text[-tail:] if tail else "")
        if serialized_size(candidate) <= budget:
            lo = keep
        else:
            hi = keep - 1
    head, tail = (lo + 1) // 2, lo // 2
    return text[:head] + _MARKER + (text[-tail:] if tail else "")


def fit_evaluation_context(context: dict[str, Any] | None) -> dict[str, Any] | None:
    """Trim only non-authorizing description fields at the final HTTP boundary.

    No shared state, cache, I/O or action mutation. All modes, identities,
    policy/receipt fields, operation selection/hash/effects and unknown fields
    remain exact. If explanatory text cannot make it fit, do not dispatch.
    """
    if context is None or serialized_size(context) <= CONTEXT_LIMIT:
        return context
    fitted = copy.deepcopy(context)
    candidates: list[tuple[dict[str, Any], str]] = []
    for section in ("tool", "intent", "skill"):
        value = fitted.get(section)
        if isinstance(value, dict) and isinstance(value.get("description"), str):
            candidates.append((value, "description"))
    tool = fitted.get("tool")
    if isinstance(tool, dict):
        summary = tool.get("parameters_summary")
        properties = summary.get("properties") if isinstance(summary, dict) else None
        if isinstance(properties, dict):
            for prop in properties.values():
                if isinstance(prop, dict) and isinstance(prop.get("description"), str):
                    candidates.append((prop, "description"))
    originals = {(id(parent), key): parent[key] for parent, key in candidates}
    while candidates:
        excess = serialized_size(fitted) - CONTEXT_LIMIT
        if excess <= 0:
            break
        parent, key = max(candidates, key=lambda item: serialized_size(item[0][item[1]]))
        current = serialized_size(parent[key])
        minimum = serialized_size(_MARKER)
        if current <= minimum:
            break
        # Share reductions across descriptions instead of erasing the first
        # descriptor to make room for all the others.
        parent[key] = _middle_fit(
            originals[(id(parent), key)], max(minimum, current - min(excess, (current + 1) // 2))
        )
    size = serialized_size(fitted)
    if size > CONTEXT_LIMIT:
        raise EvaluationContextTooLarge(size)
    return fitted
