"""Bounded capacity retries within one live router admission.

No authorization or state escapes the invocation. The caller owns cancellation
and the outer timeout; the transport rechecks its before-send fence each attempt.
Only a typed pre-send capacity rejection permits resending the identical call.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cognis.models.tool import ToolCall, ToolResult
from cognis.providers.executor.delivery import DeliveryState, ExecutorDeliveryError


async def dispatch_admitted_tool(executor: Any, call: ToolCall, **kwargs: Any) -> ToolResult:
    """Retry capacity rejection twice without re-entering authorization."""
    for attempt in range(3):
        try:
            result: ToolResult = await executor.tool_execute(call, **kwargs)
            return result
        except ExecutorDeliveryError as exc:
            if (
                exc.code != "executor_bridge_capacity"
                or exc.delivery_state != DeliveryState.NOT_SENT
                or attempt == 2
            ):
                raise
            await asyncio.sleep(0.1 * (2**attempt))
    raise AssertionError("Unreachable dispatch attempt")
