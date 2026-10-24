"""Bounded repair planning for provider-rejected, unexposed tool names."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import get_close_matches

from cognis.models.tool import NativeToolDefinition, stable_tool_id

_REJECTION = re.compile(
    r"attempted to call tool\s+[`'\"](?P<name>[A-Za-z0-9_.:-]{1,160})[`'\"]"
    r"\s+which was not in request\.tools\b",
    re.IGNORECASE,
)
MAX_REJECTIONS_PER_TURN = 4


@dataclass(frozen=True, slots=True)
class RejectionRepair:
    """A safe next-request repair decision; never carries failed arguments."""

    rejected_name: str
    promoted_tool_id: str | None
    note: str


@dataclass(slots=True)
class ToolRejectionRecoveryState:
    """Per-turn rejected names, shared by same-turn step reentries."""

    turn_id: str
    seen_names: set[str]

    @classmethod
    def for_turn(cls, turn_id: str) -> ToolRejectionRecoveryState:
        return cls(turn_id=turn_id, seen_names=set())

    def reset_for_new_turn(self, turn_id: str) -> None:
        if self.turn_id != turn_id:
            self.turn_id = turn_id
            self.seen_names.clear()


def rejected_tool_name(message: str) -> str | None:
    """Extract only a bounded quoted tool identifier from a known rejection."""

    match = _REJECTION.search(message[:2000])
    return match.group("name") if match else None


def plan_rejection_repair(
    name: str,
    *,
    inventory: Iterable[NativeToolDefinition],
    aliases: dict[str, str],
    visible_tool_ids: set[str],
    seen_names: set[str],
) -> RejectionRepair | None:
    """Plan one promotion or corrective note from the already-authorized inventory."""

    if name in seen_names or len(seen_names) >= MAX_REJECTIONS_PER_TURN:
        return None
    tools = list(inventory)
    matches = [
        tool
        for tool in tools
        if name in {tool.name, stable_tool_id(tool)}
        or (aliases.get(name) in {tool.name, stable_tool_id(tool)})
    ]
    # Do not resolve ambiguous aliases or rely on provider-name suffixes.
    unique = {stable_tool_id(tool): tool for tool in matches}
    if len(unique) == 1:
        tool_id, tool = next(iter(unique.items()))
        if tool_id not in visible_tool_ids:
            return RejectionRepair(
                name,
                tool_id,
                f"The provider could not expose the requested tool name. "
                f"Use `describe_tool` for the authorized tool `{tool_id}`, then invoke it "
                "through `call_tool` with its exact tool id and an arguments object. "
                "Do not call the hidden tool directly or reuse the rejected call.",
            )
    suggestions = get_close_matches(name, [tool.name for tool in tools], n=3, cutoff=0.45)
    choices = ", ".join(f"`{candidate}`" for candidate in suggestions)
    suffix = f" Closest authorized names: {choices}." if choices else ""
    return RejectionRepair(
        name,
        None,
        f"The requested tool name `{name}` is not available in the current authorized "
        f"inventory. Use `search_tools` to discover a currently authorized capability "
        f"and call only a tool whose schema is returned.{suffix}",
    )
