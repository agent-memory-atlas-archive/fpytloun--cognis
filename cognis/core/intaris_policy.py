"""Human-owned profile mutation boundary for model-authored metadata."""

from __future__ import annotations

from typing import Any

from cognis import json_codec as json
from cognis.models.tool import ToolResult
from cognis.models.workflow import normalize_session_policy

_HUMAN_ONLY_KEYS = {
    "intaris_evaluation": "Intaris evaluation",
    "approval_mode": "Agent approval mode",
}


def profile_mutation_error(arguments: Any) -> ToolResult | None:
    """Reject human-only policy keys, including null, at nested metadata boundaries."""
    if isinstance(arguments, dict):
        for key, label in _HUMAN_ONLY_KEYS.items():
            if key not in arguments:
                continue
            return ToolResult(
                output=json.dumps(
                    {
                        "status": "error",
                        "code": "human_policy_selection_required",
                        "message": f"{label} can only be selected or cleared through the human UI/API.",
                    }
                ),
                is_error=True,
            )
        for value in arguments.values():
            error = profile_mutation_error(value)
            if error is not None:
                return error
    elif isinstance(arguments, list):
        for value in arguments:
            error = profile_mutation_error(value)
            if error is not None:
                return error
    return None


def approvals_unattended(
    interaction_mode: str | None, agent: Any, task_interaction_mode_override: str | None
) -> bool:
    """Return whether Intaris escalations are denied instead of asking a human.

    An explicit task interaction mode wins. Otherwise interaction mode ``none``
    or an agent approval mode of ``unattended`` makes the session unattended.
    """
    if task_interaction_mode_override is not None:
        return task_interaction_mode_override == "none"
    if interaction_mode == "none":
        return True
    capabilities = getattr(agent, "capabilities", None)
    return getattr(capabilities, "approval_mode", "ask") == "unattended"


def tool_session_policy(value: Any, existing: Any = None) -> dict[str, Any]:
    """Replace model-authored prose while retaining any human-selected profile."""
    policy = normalize_session_policy(value)
    prior = normalize_session_policy(existing)
    if prior.get("intaris_evaluation") is not None:
        policy["intaris_evaluation"] = prior["intaris_evaluation"]
    return policy
