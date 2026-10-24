"""Content-free classification of Intaris approval resolution rejections."""

from __future__ import annotations

import re
from typing import Any

_MESSAGES = {
    "read_only_ceiling": "This action can't be approved under the explicit read-only restriction.",
    "mandatory_denial": "This action is denied by mandatory policy and can't be approved.",
    "stale_approval": "This approval expired because the session changed. Request approval again.",
    "stale_resolution": (
        "This approval is no longer valid because the session or policy changed. "
        "Ask the agent to evaluate the action again. Refreshing this approval won't renew it."
    ),
    "human_approval_required": "This action requires a new human approval.",
    "stale_admission": "This admission expired. Request a new approval.",
    "stale_task_context": "The task context changed. Request a new approval.",
    "stale_policy_revision": "The approval policy changed. Request a new approval.",
    "stale_policy_hash": "The approval policy changed. Request a new approval.",
    "policy_version_mismatch": "The approval policy version changed. Request a new approval.",
    "expired_admission": "This admission expired. Request a new approval.",
    "invalid_active_policy": "The active approval policy is invalid.",
    "logical_call_conflict": "This approval conflicts with an existing tool call.",
    "duplicate_admission": "This admission was already submitted.",
    "alignment_not_ready": "The session policy is not ready for approval yet.",
    "already_resolved": "Notification already resolved or not found",
}

# Compatibility with de115a5 /decision ValueError details. Match only the
# known wire messages, never arbitrary text containing a policy keyword.
_LEGACY_MESSAGES = {
    "Unattended Judge review cannot be resolved by a human": "mandatory_denial",
}
_LEGACY_RESOLVED = re.compile(
    r"Call [^\s]+ already resolved(?: by user)? \(user_decision=(?:approve|deny)\)"
)

_REEVALUATION_CODES = {
    "stale_resolution",
    "stale_approval",
    "stale_admission",
    "stale_task_context",
    "stale_policy_revision",
    "stale_policy_hash",
    "policy_version_mismatch",
    "expired_admission",
}


def stale_approval_result(decision: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Describe a cancelled stale wait without inventing a human refusal."""
    if (
        decision != "cancel"
        or data.get("requires_reevaluation") is not True
        or data.get("reason") not in _REEVALUATION_CODES
    ):
        return None
    return {
        "status": "interrupted",
        "code": "stale_approval",
        "message": (
            "The approval became stale because the session or policy changed. "
            "The tool was not executed, and this was not a user denial. "
            "Evaluate the action again under the current session and policy; "
            "do not reuse the expired approval."
        ),
        "retryable": True,
    }


class ResolutionRejected(Exception):
    """A definitive HTTP rejection, not an uncertain submission outcome."""

    def __init__(self, status: int, payload: Any) -> None:
        detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        raw_code = detail.get("code") if isinstance(detail, dict) else None
        if isinstance(detail, str):
            # Older deployments may serialize a bare code rather than a
            # structured detail. Unknown prose remains a content-free error.
            raw_code = detail if detail in _MESSAGES else _LEGACY_MESSAGES.get(detail)
            if _LEGACY_RESOLVED.fullmatch(detail):
                raw_code = "already_resolved"
        self.code = (
            raw_code
            if isinstance(raw_code, str) and raw_code in _MESSAGES
            else "resolution_rejected"
        )
        self.status = status
        if status == 404:
            self.code = "already_resolved"
        self.message = _MESSAGES.get(
            self.code,
            "Intaris rejected this approval resolution. Refresh the approval and try again.",
        )
        self.permanent = self.code in {"read_only_ceiling", "mandatory_denial"}
        self.requires_reevaluation = self.code in _REEVALUATION_CODES
        self.resolved_locally = False
        super().__init__(f"Intaris resolution rejected ({self.code})")

    def api_detail(self) -> dict[str, Any]:
        """Return safe transport metadata and the authoritative local disposition."""
        return {
            "code": self.code,
            "message": self.message,
            "details": {
                "resolved": self.resolved_locally,
                "decision": (
                    ("cancel" if self.requires_reevaluation else "deny")
                    if self.resolved_locally
                    else None
                ),
            },
        }
