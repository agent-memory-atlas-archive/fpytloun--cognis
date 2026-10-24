"""Single submission owner for service-absent, local legacy approvals."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from cognis.core.agent_loop import PauseResolution, PauseWaiter, PendingPause
from cognis.providers.guardrails.resolution_errors import ResolutionRejected


def escalation_call_id(pause: PendingPause) -> str:
    """Map the recorded call ID or the supported legacy pause ID to Intaris."""
    recorded = (pause.context or {}).get("call_id")
    if isinstance(recorded, str) and recorded:
        return recorded
    return pause.pause_id.removeprefix("escalation:")


async def resolve_legacy_approval(
    waiter: PauseWaiter,
    pause_id: str,
    *,
    conversation_id: str,
    decision: str,
    note: str | None,
    submit: Callable[..., Awaitable[Any]],
    require_unique: bool = False,
) -> bool:
    """Claim before submission; uncertain outcomes remain claimed until cleanup.

    The caller authenticates conversation ownership. This path is permitted
    only when the durable notification service is absent, never as a fallback
    for an approval whose durable registration has not completed.
    """
    pending = waiter.get(pause_id)
    claim = waiter.claim_escalation(
        pause_id, conversation_id=conversation_id, require_unique=require_unique
    )
    if pending is None or claim is None:
        return False
    try:
        await submit(escalation_call_id(pending), decision, note)
    except ResolutionRejected as exc:
        if exc.permanent:
            exc.resolved_locally = waiter.resolve(
                pause_id,
                PauseResolution(decision="deny", data={"note": exc.message, "reason": exc.code}),
                claim=claim,
            )
        else:
            waiter.release_escalation_claim(pause_id, claim)
        raise
    return waiter.resolve(
        pause_id, PauseResolution(decision=decision, data={"note": note or ""}), claim=claim
    )
