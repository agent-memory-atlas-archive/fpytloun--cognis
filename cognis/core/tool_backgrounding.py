"""User-initiated handoff of a running foreground tool call to a background job.

Owned state: none. The authoritative lookup is the durable direct-turn dispatch
record (``tool_dispatch_groups``) of the conversation's active turn, which binds
each in-flight call to its executor and executor process instance.

Side effect: one ``tool.background`` RPC to that executor instance. The
executor decides whether the handoff still applies; the tool result it then
returns (marked ``moved_to_background``) is the terminal outcome of the call and
flows through the normal agent-loop result path.

Idempotency: repeated requests for the same call are reported as already
requested by the executor and treated as success.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from cognis.logging import get_logger
from cognis.models.tool import ToolResult
from cognis.store.direct_turns import DirectTurnStore, read_tool_dispatch_groups
from cognis.tools.registry import ToolBackgroundRequestOutcome

logger = get_logger(__name__)

BACKGROUNDABLE_TOOL_NAMES: frozenset[str] = frozenset({"bash"})


class ToolBackgroundErrorCode(StrEnum):
    """Stable reasons a background handoff request cannot be honored."""

    NO_ACTIVE_TURN = "no_active_turn"
    UNKNOWN_CALL = "unknown_call"
    UNSUPPORTED_TOOL = "unsupported_tool"
    NOT_BACKGROUNDABLE = "not_backgroundable"
    EXECUTOR_UNAVAILABLE = "executor_unavailable"
    EXECUTOR_UNSUPPORTED = "executor_unsupported"


_ERROR_MESSAGES: dict[ToolBackgroundErrorCode, str] = {
    ToolBackgroundErrorCode.NO_ACTIVE_TURN: "The conversation has no active turn.",
    ToolBackgroundErrorCode.UNKNOWN_CALL: "The tool call is not running in the active turn.",
    ToolBackgroundErrorCode.UNSUPPORTED_TOOL: "Only running bash commands can be moved to the background.",
    ToolBackgroundErrorCode.NOT_BACKGROUNDABLE: (
        "The command can no longer be moved to the background; it may have just finished."
    ),
    ToolBackgroundErrorCode.EXECUTOR_UNAVAILABLE: (
        "The executor running this command is not reachable from this controller."
    ),
    ToolBackgroundErrorCode.EXECUTOR_UNSUPPORTED: (
        "The executor did not acknowledge the request; it may need to be upgraded."
    ),
}


class ToolBackgroundError(Exception):
    """Raised when a running tool call cannot be moved to the background."""

    def __init__(self, code: ToolBackgroundErrorCode, message: str | None = None) -> None:
        super().__init__(message or _ERROR_MESSAGES[code])
        self.code = code


@dataclass(frozen=True, slots=True)
class ToolBackgroundRequestResult:
    """Accepted background handoff request."""

    call_id: str
    tool_name: str
    executor_id: str | None
    already_requested: bool


@dataclass(frozen=True, slots=True)
class _InFlightCall:
    tool_name: str
    executor_id: str | None
    executor_instance_id: str | None


TOOL_BACKGROUND_NOTICE_KIND = "tool_moved_to_background"


@dataclass(frozen=True, slots=True)
class ToolBackgroundNotice:
    """Controller notice for a tool call the user moved to the background."""

    call_id: str
    tool_name: str
    shell_id: str
    executor_id: str | None
    message: str
    agent_context: str

    @property
    def notice_id(self) -> str:
        """Stable identity so a replayed or retried notice is recorded once."""

        return f"{TOOL_BACKGROUND_NOTICE_KIND}:{self.call_id}"

    def metadata(self) -> dict[str, Any]:
        """Return durable ``system_notice`` metadata for this notice."""

        return {
            "kind": TOOL_BACKGROUND_NOTICE_KIND,
            "notice_id": self.notice_id,
            "agent_context": self.agent_context,
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "shell_id": self.shell_id,
            "executor_id": self.executor_id,
        }


def tool_background_notice_from_result(
    *,
    call_id: str,
    tool_name: str,
    executor_native: bool,
    result: ToolResult,
) -> ToolBackgroundNotice | None:
    """Return the controller notice for a result that reports a user handoff.

    Only executor-native backgroundable tools qualify: their result metadata is
    produced by executor runtime code that runs solely after the controller's
    ``tool.background`` request, never by command output or a remote MCP server.
    """

    if not executor_native or tool_name not in BACKGROUNDABLE_TOOL_NAMES:
        return None
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    if metadata.get("moved_to_background") is not True:
        return None
    if metadata.get("background_initiator") != "user":
        return None
    shell_id = metadata.get("shell_id")
    if not isinstance(shell_id, str) or not shell_id:
        return None
    executor_id = metadata.get("executor_id")
    executor_label = executor_id if isinstance(executor_id, str) and executor_id else None
    target_hint = (
        f" Include target_executor='{executor_label}' when that executor is not active."
        if executor_label
        else ""
    )
    agent_context = (
        f"The user moved your running {tool_name} command (call_id {call_id}) to the "
        f"background as shell {shell_id}. It is still running; do not wait for it or run it "
        f"again. Use bash_output with shell_id='{shell_id}' to read output and bash_kill to "
        f"stop it.{target_hint} You will receive a follow-up when it finishes. Continue with "
        "the remaining work, or end the turn if nothing else is independently actionable."
    )
    return ToolBackgroundNotice(
        call_id=call_id,
        tool_name=tool_name,
        shell_id=shell_id,
        executor_id=executor_label,
        message=f"Moved the running {tool_name} command to the background ({shell_id}).",
        agent_context=agent_context,
    )


class ToolBackgroundingService:
    """Route a user request to move a running tool call into the background."""

    def __init__(
        self,
        *,
        direct_turn_store: DirectTurnStore | None,
        executor_provider: Any,
    ) -> None:
        self._direct_turn_store = direct_turn_store
        self._executor_provider = executor_provider

    async def request_background(
        self, *, conversation_id: str, call_id: str
    ) -> ToolBackgroundRequestResult:
        """Ask the executor running ``call_id`` to continue it as a background job.

        The caller must already have authorized access to ``conversation_id``.
        Only calls recorded in that conversation's active durable turn are
        eligible, so a call ID from another conversation is never routed.
        """

        call = await self._find_in_flight_call(conversation_id, call_id)
        if call.tool_name not in BACKGROUNDABLE_TOOL_NAMES:
            raise ToolBackgroundError(ToolBackgroundErrorCode.UNSUPPORTED_TOOL)
        outcome = await self._dispatch(call_id, call)
        if outcome is ToolBackgroundRequestOutcome.UNKNOWN_CALL:
            raise ToolBackgroundError(ToolBackgroundErrorCode.NOT_BACKGROUNDABLE)
        if outcome is ToolBackgroundRequestOutcome.NOT_BACKGROUNDABLE:
            raise ToolBackgroundError(ToolBackgroundErrorCode.NOT_BACKGROUNDABLE)
        logger.info(
            "tool_backgrounding: request accepted",
            extra={
                "extra_data": {
                    "conversation_id": conversation_id,
                    "call_id": call_id,
                    "tool_name": call.tool_name,
                    "executor_id": call.executor_id,
                    "outcome": outcome.value,
                }
            },
        )
        return ToolBackgroundRequestResult(
            call_id=call_id,
            tool_name=call.tool_name,
            executor_id=call.executor_id,
            already_requested=outcome is ToolBackgroundRequestOutcome.ALREADY_REQUESTED,
        )

    async def _find_in_flight_call(self, conversation_id: str, call_id: str) -> _InFlightCall:
        if self._direct_turn_store is None:
            raise ToolBackgroundError(ToolBackgroundErrorCode.NO_ACTIVE_TURN)
        row = await self._direct_turn_store.get_conversation_active(conversation_id)
        if row is None:
            raise ToolBackgroundError(ToolBackgroundErrorCode.NO_ACTIVE_TURN)
        groups = read_tool_dispatch_groups(
            row.outcome,
            fallback_session_id=row.session_id,
            fallback_turn_id=row.turn_id,
        )
        for group in groups:
            for raw in group.tool_calls:
                if not isinstance(raw, dict) or raw.get("call_id") != call_id:
                    continue
                tool_name = raw.get("tool_name")
                executor_id = raw.get("executor_id")
                instance_id = raw.get("executor_instance_id")
                return _InFlightCall(
                    tool_name=tool_name if isinstance(tool_name, str) else "",
                    executor_id=executor_id if isinstance(executor_id, str) else None,
                    executor_instance_id=instance_id if isinstance(instance_id, str) else None,
                )
        raise ToolBackgroundError(ToolBackgroundErrorCode.UNKNOWN_CALL)

    async def _dispatch(self, call_id: str, call: _InFlightCall) -> ToolBackgroundRequestOutcome:
        websocket_provider = getattr(self._executor_provider, "websocket", None)
        connection = None
        if call.executor_id is not None and websocket_provider is not None:
            connection = websocket_provider.get_connection(call.executor_id)
        if connection is not None:
            # A replacement executor process never ran this call; reject a known
            # mismatch up front. A cold forwarded proxy does not know its peer
            # instance until its bridge opens; the request is then still safe
            # because a process that does not own the call answers unknown_call.
            live_instance_id = getattr(connection, "executor_instance_id", None)
            if (
                call.executor_instance_id is not None
                and live_instance_id is not None
                and live_instance_id != call.executor_instance_id
            ):
                raise ToolBackgroundError(ToolBackgroundErrorCode.EXECUTOR_UNAVAILABLE)
            try:
                outcome: ToolBackgroundRequestOutcome = await connection.request_background(call_id)
            except TimeoutError as exc:
                raise ToolBackgroundError(ToolBackgroundErrorCode.EXECUTOR_UNSUPPORTED) from exc
            except Exception as exc:
                logger.warning(
                    "tool_backgrounding: executor request failed",
                    extra={
                        "extra_data": {
                            "call_id": call_id,
                            "executor_id": call.executor_id,
                            "error_type": type(exc).__name__,
                        }
                    },
                )
                raise ToolBackgroundError(ToolBackgroundErrorCode.EXECUTOR_UNAVAILABLE) from exc
            return outcome
        in_process_provider = getattr(self._executor_provider, "in_process", None)
        requester = getattr(in_process_provider, "request_background", None)
        if callable(requester):
            outcome = await requester(call_id)
            if outcome is not ToolBackgroundRequestOutcome.UNKNOWN_CALL:
                return outcome
        raise ToolBackgroundError(ToolBackgroundErrorCode.EXECUTOR_UNAVAILABLE)
