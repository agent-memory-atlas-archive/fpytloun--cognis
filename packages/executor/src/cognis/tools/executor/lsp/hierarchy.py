"""Bounded one-shot call hierarchy traversal.

The traversal is bound to one live :class:`LSPClient`: ``CallHierarchyItem``
payloads are opaque server state and must never be sent to a different
server or reused after a restart.  Every dimension is limited (depth,
breadth per node, total nodes, total edges, wall time) and the result
reports why it stopped.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Literal

from cognis.tools.executor.lsp.client import LSPClient, uri_to_path
from cognis.tools.executor.lsp.format import (
    Listing,
    relative_path,
    symbol_kind_name,
)
from cognis.tools.executor.lsp.query import QueryStatus

Direction = Literal["incoming", "outgoing"]

MAX_CALL_SITES_SHOWN = 3
# Raw call lists are untrusted; never inspect more entries than this per node.
MAX_RAW_CALLS = 2000
# Call-site ranges per edge are likewise bounded before inspection.
MAX_RAW_CALL_SITES = 100


@dataclass(slots=True, frozen=True)
class HierarchyLimits:
    """Hard bounds for one traversal."""

    max_depth: int = 3
    max_breadth: int = 20
    max_nodes: int = 100
    max_edges: int = 200
    time_budget_s: float = 8.0

    @classmethod
    def from_arguments(cls, depth: Any) -> HierarchyLimits:
        """Build limits from tool arguments, clamping to safe ranges."""
        default = cls()
        max_depth = default.max_depth
        if isinstance(depth, int) and not isinstance(depth, bool):
            max_depth = max(1, min(5, depth))
        return cls(max_depth=max_depth)


@dataclass(slots=True)
class CallNode:
    """One node of the rendered call tree, 1-based coordinates."""

    name: str
    kind: str
    path: str
    line: int
    detail: str
    call_sites: list[int] = field(default_factory=list)
    """Lines of the call expressions that connect this node to its parent."""
    children: list[CallNode] = field(default_factory=list)
    note: str = ""
    """Why expansion stopped here: ``cycle``, ``depth``, ``breadth``, ``limit``."""

    def to_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "line": self.line,
        }
        if self.call_sites:
            data["call_sites"] = self.call_sites
        if self.note:
            data["note"] = self.note
        if self.children:
            data["children"] = [child.to_metadata() for child in self.children]
        return data


@dataclass(slots=True)
class HierarchyResult:
    """Outcome of one traversal."""

    status: QueryStatus
    roots: list[CallNode]
    node_count: int
    edge_count: int
    depth_reached: int
    duration_ms: int
    stop_reason: str | None = None
    """Bounded reason when the traversal is partial: ``depth``, ``nodes``,
    ``edges``, ``time``, ``server_exited``, ``request_failed``."""


def _item_key(item: dict[str, Any]) -> tuple[str, int, int] | None:
    uri = item.get("uri")
    selection = item.get("selectionRange") or item.get("range")
    if not isinstance(uri, str) or not isinstance(selection, dict):
        return None
    start = selection.get("start")
    if not isinstance(start, dict):
        return None
    line = start.get("line")
    character = start.get("character")
    if not isinstance(line, int) or not isinstance(character, int):
        return None
    return uri, line, character


def _node_from_item(item: dict[str, Any], *, cwd: str | None) -> CallNode | None:
    key = _item_key(item)
    name = item.get("name")
    if key is None or not isinstance(name, str):
        return None
    detail = item.get("detail")
    return CallNode(
        name=name,
        kind=symbol_kind_name(item.get("kind")),
        path=relative_path(uri_to_path(key[0]), cwd),
        line=key[1] + 1,
        detail=detail.strip() if isinstance(detail, str) else "",
    )


def _call_site_lines(raw_ranges: Any) -> list[int]:
    lines: list[int] = []
    if not isinstance(raw_ranges, list):
        return lines
    for raw in raw_ranges[:MAX_RAW_CALL_SITES]:
        if not isinstance(raw, dict):
            continue
        start = raw.get("start")
        if isinstance(start, dict) and isinstance(start.get("line"), int):
            lines.append(start["line"] + 1)
    return sorted(set(lines))


async def traverse_call_hierarchy(
    client: LSPClient,
    file_path: str,
    line: int,
    character: int,
    *,
    direction: Direction,
    limits: HierarchyLimits,
    cwd: str | None,
) -> HierarchyResult:
    """Prepare items at a position and expand them breadth-first within limits.

    ``line`` and ``character`` are 0-based protocol coordinates.  Items are
    only ever sent back to ``client``.  If the client dies mid-traversal the
    partial tree is returned with ``stop_reason="server_exited"``.
    """
    started = monotonic()
    deadline = started + limits.time_budget_s
    fetch: Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]] = (
        client.incoming_calls if direction == "incoming" else client.outgoing_calls
    )
    edge_key = "from" if direction == "incoming" else "to"

    def finish(
        status: QueryStatus,
        roots: list[CallNode],
        nodes: int,
        edges: int,
        depth: int,
        reason: str | None,
    ) -> HierarchyResult:
        return HierarchyResult(
            status=status,
            roots=roots,
            node_count=nodes,
            edge_count=edges,
            depth_reached=depth,
            duration_ms=int((monotonic() - started) * 1000),
            stop_reason=reason,
        )

    try:
        items = await asyncio.wait_for(
            client.prepare_call_hierarchy(file_path, line, character),
            timeout=max(0.05, deadline - monotonic()),
        )
    except TimeoutError:
        return finish(QueryStatus.TIMEOUT, [], 0, 0, 0, "time")
    except Exception:
        reason = "request_failed" if client.is_alive else "server_exited"
        return finish(QueryStatus.FAILED, [], 0, 0, 0, reason)

    roots: list[CallNode] = []
    visited: set[tuple[str, int, int]] = set()
    frontier: list[tuple[CallNode, dict[str, Any], int]] = []
    for item in items[: limits.max_breadth]:
        if not isinstance(item, dict):
            continue
        node = _node_from_item(item, cwd=cwd)
        key = _item_key(item)
        if node is None or key is None:
            continue
        visited.add(key)
        roots.append(node)
        frontier.append((node, item, 0))
    if not roots:
        return finish(QueryStatus.EMPTY, [], 0, 0, 0, None)

    node_count = len(roots)
    edge_count = 0
    depth_reached = 0
    stop_reason: str | None = None

    while frontier and stop_reason is None:
        node, item, depth = frontier.pop(0)
        if depth >= limits.max_depth:
            node.note = "depth"
            continue
        remaining = deadline - monotonic()
        if remaining <= 0:
            stop_reason = "time"
            break
        try:
            calls = await asyncio.wait_for(fetch(item), timeout=remaining)
        except TimeoutError:
            node.note = "limit"
            stop_reason = "time"
            break
        except Exception:
            node.note = "limit"
            stop_reason = "request_failed" if client.is_alive else "server_exited"
            break

        shown = 0
        if not isinstance(calls, list):
            calls = []
        for call in calls[:MAX_RAW_CALLS]:
            if not isinstance(call, dict):
                continue
            target = call.get(edge_key)
            if not isinstance(target, dict):
                continue
            child = _node_from_item(target, cwd=cwd)
            key = _item_key(target)
            if child is None or key is None:
                continue
            if shown >= limits.max_breadth:
                node.note = "breadth"
                break
            if edge_count >= limits.max_edges:
                stop_reason = "edges"
                break
            child.call_sites = _call_site_lines(call.get("fromRanges"))
            node.children.append(child)
            edge_count += 1
            shown += 1
            depth_reached = max(depth_reached, depth + 1)
            if key in visited:
                child.note = "cycle"
                continue
            if node_count >= limits.max_nodes:
                child.note = "limit"
                stop_reason = "nodes"
                continue
            visited.add(key)
            node_count += 1
            frontier.append((child, target, depth + 1))

    # Nodes left unexpanded because the traversal stopped are marked so the
    # reader knows the tree is incomplete there.
    if stop_reason is not None:
        for pending_node, _, _ in frontier:
            if not pending_node.children and not pending_node.note:
                pending_node.note = "limit"
    elif any(_has_note(root, "depth") for root in roots):
        stop_reason = "depth"

    status = QueryStatus.PARTIAL if stop_reason else QueryStatus.OK
    return finish(status, roots, node_count, edge_count, depth_reached, stop_reason)


def _has_note(node: CallNode, note: str) -> bool:
    if node.note == note:
        return True
    return any(_has_note(child, note) for child in node.children)


def format_call_tree(
    result: HierarchyResult, *, direction: Direction, indent: str = "  "
) -> Listing:
    """Render the call tree as indented ``kind name  path:line`` lines."""
    lines: list[str] = []
    verb = "called from line" if direction == "incoming" else "call at line"

    def walk(node: CallNode, depth: int) -> None:
        location = f"{node.path}:{node.line}"
        extras: list[str] = []
        if node.call_sites:
            shown = node.call_sites[:MAX_CALL_SITES_SHOWN]
            suffix = (
                f" +{len(node.call_sites) - len(shown)}"
                if len(node.call_sites) > len(shown)
                else ""
            )
            extras.append(f"{verb} {', '.join(str(n) for n in shown)}{suffix}")
        if node.note == "cycle":
            extras.append("already shown")
        elif node.note == "depth":
            extras.append("depth limit")
        elif node.note == "breadth":
            extras.append("more callers omitted")
        elif node.note == "limit":
            extras.append("not expanded")
        suffix_text = f"  ({'; '.join(extras)})" if extras else ""
        lines.append(f"{indent * depth}{node.kind} {node.name}  {location}{suffix_text}")
        for child in node.children:
            walk(child, depth + 1)

    for root in result.roots:
        walk(root, 0)
    return Listing(
        text="\n".join(lines),
        total=result.edge_count,
        shown=result.edge_count,
        truncated=result.stop_reason is not None,
        items=[root.to_metadata() for root in result.roots],
    )
