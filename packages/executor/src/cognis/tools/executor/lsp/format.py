"""Compact, deterministic presentation of LSP query results.

This module owns the translation from protocol payloads (``Location``,
``LocationLink``, ``Hover``, ``DocumentSymbol``, ``SymbolInformation``) to
agent-facing text.  Rules:

- paths are relative to the working directory when possible;
- coordinates are 1-based;
- items are deduplicated and ordered by ``(path, line, column)``;
- every listing honours a ``limit`` and reports truncation explicitly;
- no raw protocol JSON or URIs appear in the output.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from cognis.tools.executor.lsp.client import uri_to_path

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_HOVER_CHARS = 2000
MAX_SNIPPET_CHARS = 120
MAX_SNIPPET_FILES = 20
MAX_OUTPUT_BYTES = 24_000
# Server payloads are untrusted: bound recursion and fan-out before any
# normalization work is done on them.
MAX_OUTLINE_DEPTH = 16
MAX_OUTLINE_CHILDREN = 500
MAX_OUTLINE_NODES = 5000

# LSP ``SymbolKind`` values.
_SYMBOL_KINDS: dict[int, str] = {
    1: "file",
    2: "module",
    3: "namespace",
    4: "package",
    5: "class",
    6: "method",
    7: "property",
    8: "field",
    9: "constructor",
    10: "enum",
    11: "interface",
    12: "function",
    13: "variable",
    14: "constant",
    15: "string",
    16: "number",
    17: "boolean",
    18: "array",
    19: "object",
    20: "key",
    21: "null",
    22: "enum_member",
    23: "struct",
    24: "event",
    25: "operator",
    26: "type_parameter",
}

_CALLABLE_KINDS = frozenset({"function", "method", "constructor"})
_LOCAL_KINDS = frozenset({"variable", "constant"})


def symbol_kind_name(kind: Any) -> str:
    """Return a lowercase name for an LSP ``SymbolKind`` value."""
    if isinstance(kind, int):
        return _SYMBOL_KINDS.get(kind, "symbol")
    return "symbol"


def relative_path(path: str, cwd: str | None) -> str:
    """Return ``path`` relative to ``cwd`` when it lies inside it."""
    if cwd is None:
        return path
    try:
        rel = os.path.relpath(path, cwd)
    except ValueError:
        return path
    if rel.startswith(".."):
        return path
    return str(PurePosixPath(rel))


@dataclass(slots=True, frozen=True, order=True)
class LocationItem:
    """A normalized code location with 1-based coordinates."""

    path: str
    line: int
    column: int
    end_line: int
    end_column: int
    name: str = ""
    kind: str = ""
    container: str = ""

    def to_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {"path": self.path, "line": self.line, "column": self.column}
        if self.end_line != self.line or self.end_column != self.column:
            data["end_line"] = self.end_line
            data["end_column"] = self.end_column
        if self.name:
            data["name"] = self.name
        if self.kind:
            data["kind"] = self.kind
        if self.container:
            data["container"] = self.container
        return data


def _position(raw: Any) -> tuple[int, int] | None:
    if not isinstance(raw, dict):
        return None
    line = raw.get("line")
    character = raw.get("character")
    if not isinstance(line, int) or not isinstance(character, int):
        return None
    if line < 0 or character < 0:
        return None
    return line + 1, character + 1


def _range(raw: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(raw, dict):
        return None
    start = _position(raw.get("start"))
    end = _position(raw.get("end"))
    if start is None:
        return None
    if end is None:
        end = start
    return start[0], start[1], end[0], end[1]


def location_from_payload(raw: Any, *, cwd: str | None) -> LocationItem | None:
    """Normalize a ``Location`` or ``LocationLink`` payload.

    ``LocationLink`` prefers ``targetSelectionRange`` (the identifier) over
    ``targetRange`` (the whole declaration) so results point at the name.
    """
    if not isinstance(raw, dict):
        return None
    uri = raw.get("uri")
    range_raw = raw.get("range")
    if not isinstance(uri, str):
        uri = raw.get("targetUri")
        range_raw = raw.get("targetSelectionRange") or raw.get("targetRange")
    if not isinstance(uri, str) or not uri.startswith("file:"):
        return None
    rng = _range(range_raw)
    if rng is None:
        return None
    path = relative_path(uri_to_path(uri), cwd)
    return LocationItem(path=path, line=rng[0], column=rng[1], end_line=rng[2], end_column=rng[3])


def normalize_locations(items: list[Any], *, cwd: str | None) -> list[LocationItem]:
    """Normalize, deduplicate and order location payloads."""
    seen: set[tuple[str, int, int]] = set()
    normalized: list[LocationItem] = []
    for raw in items:
        item = location_from_payload(raw, cwd=cwd)
        if item is None:
            continue
        key = (item.path, item.line, item.column)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    normalized.sort()
    return normalized


def symbol_from_payload(raw: Any, *, cwd: str | None) -> LocationItem | None:
    """Normalize a flat ``SymbolInformation`` or ``WorkspaceSymbol`` payload."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str):
        return None
    location = location_from_payload(raw.get("location"), cwd=cwd)
    if location is None:
        # WorkspaceSymbol may omit the range; fall back to the URI only.
        loc_raw = raw.get("location")
        uri = loc_raw.get("uri") if isinstance(loc_raw, dict) else None
        if not isinstance(uri, str) or not uri.startswith("file:"):
            return None
        location = LocationItem(
            path=relative_path(uri_to_path(uri), cwd), line=0, column=0, end_line=0, end_column=0
        )
    container = raw.get("containerName")
    return LocationItem(
        path=location.path,
        line=location.line,
        column=location.column,
        end_line=location.end_line,
        end_column=location.end_column,
        name=name,
        kind=symbol_kind_name(raw.get("kind")),
        container=container if isinstance(container, str) else "",
    )


def normalize_symbols(items: list[Any], *, cwd: str | None) -> list[LocationItem]:
    """Normalize, deduplicate and order flat symbol payloads."""
    seen: set[tuple[str, int, int, str]] = set()
    normalized: list[LocationItem] = []
    for raw in items:
        item = symbol_from_payload(raw, cwd=cwd)
        if item is None:
            continue
        key = (item.path, item.line, item.column, item.name)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    normalized.sort()
    return normalized


@dataclass(slots=True)
class Listing:
    """A bounded text listing plus the facts the tool reports about it."""

    text: str
    total: int
    shown: int
    truncated: bool
    items: list[dict[str, Any]]


def clamp_limit(value: Any, *, default: int = DEFAULT_LIMIT) -> int:
    """Return a sane result limit from a raw argument."""
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    limit: int = value
    return max(1, min(MAX_LIMIT, limit))


def format_locations(
    items: list[LocationItem],
    *,
    limit: int,
    snippet_loader: Callable[[str, int], str | None] | None = None,
) -> Listing:
    """Render locations as ``path:line:col`` lines, grouped by file.

    ``snippet_loader`` optionally returns the trimmed source line for a
    ``(path, line)`` pair; it is consulted for at most ``MAX_SNIPPET_FILES``
    distinct files so large reference sets stay cheap.
    """
    total = len(items)
    shown_items = items[:limit]
    lines: list[str] = []
    snippet_files: set[str] = set()
    current_path: str | None = None
    for item in shown_items:
        if item.path != current_path:
            current_path = item.path
            lines.append(f"{item.path}")
        entry = f"  {item.line}:{item.column}"
        if item.name:
            entry += f"  {item.kind + ' ' if item.kind else ''}{item.name}"
        if (
            snippet_loader is not None
            and item.line > 0
            and (item.path in snippet_files or len(snippet_files) < MAX_SNIPPET_FILES)
        ):
            snippet_files.add(item.path)
            snippet = snippet_loader(item.path, item.line)
            if snippet:
                entry += f"  {snippet}"
        lines.append(entry)
    truncated = total > len(shown_items)
    if truncated:
        lines.append(f"... {total - len(shown_items)} more (raise limit to see them)")
    return Listing(
        text="\n".join(lines),
        total=total,
        shown=len(shown_items),
        truncated=truncated,
        items=[item.to_metadata() for item in shown_items],
    )


def format_workspace_symbols(items: list[LocationItem], *, limit: int) -> Listing:
    """Render workspace symbols as ``kind name  path:line`` lines."""
    total = len(items)
    shown_items = items[:limit]
    lines: list[str] = []
    for item in shown_items:
        location = item.path if item.line == 0 else f"{item.path}:{item.line}"
        container = f"  in {item.container}" if item.container else ""
        lines.append(f"{item.kind} {item.name}  {location}{container}")
    truncated = total > len(shown_items)
    if truncated:
        lines.append(f"... {total - len(shown_items)} more (raise limit or refine query)")
    return Listing(
        text="\n".join(lines),
        total=total,
        shown=len(shown_items),
        truncated=truncated,
        items=[item.to_metadata() for item in shown_items],
    )


def _markup_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        value = raw.get("value")
        if isinstance(value, str):
            language = raw.get("language")
            if isinstance(language, str) and language:
                return f"```{language}\n{value}\n```"
            return value
        return ""
    if isinstance(raw, list):
        return "\n\n".join(part for part in (_markup_text(entry) for entry in raw) if part)
    return ""


def format_hover(items: list[Any], *, max_chars: int = MAX_HOVER_CHARS) -> Listing:
    """Render ``Hover`` payloads as text, deduplicated across servers."""
    texts: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        text = _markup_text(raw.get("contents")).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        texts.append(text)
    joined = "\n\n".join(texts)
    truncated = len(joined) > max_chars
    if truncated:
        joined = joined[:max_chars].rstrip() + "\n... (hover text truncated)"
    return Listing(
        text=joined,
        total=len(texts),
        shown=len(texts),
        truncated=truncated,
        items=[{"text": text[:max_chars]} for text in texts],
    )


@dataclass(slots=True)
class OutlineNode:
    """A hierarchical document symbol with 1-based coordinates."""

    name: str
    kind: str
    line: int
    end_line: int
    detail: str
    children: list[OutlineNode]

    def to_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "line": self.line,
            "end_line": self.end_line,
        }
        if self.detail:
            data["detail"] = self.detail
        if self.children:
            data["children"] = [child.to_metadata() for child in self.children]
        return data


def _outline_from_document_symbol(
    raw: Any, *, depth: int = 0, budget: list[int]
) -> OutlineNode | None:
    """Build one node; ``budget`` is a shared remaining-node counter."""
    if not isinstance(raw, dict) or depth >= MAX_OUTLINE_DEPTH or budget[0] <= 0:
        return None
    budget[0] -= 1
    name = raw.get("name")
    if not isinstance(name, str):
        return None
    rng = _range(raw.get("range")) or _range(raw.get("selectionRange"))
    if rng is None:
        return None
    detail = raw.get("detail")
    kind = symbol_kind_name(raw.get("kind"))
    children_raw = raw.get("children")
    children: list[OutlineNode] = []
    if isinstance(children_raw, list):
        for child in children_raw[:MAX_OUTLINE_CHILDREN]:
            if budget[0] <= 0:
                break
            node = _outline_from_document_symbol(child, depth=depth + 1, budget=budget)
            if node is None:
                continue
            # Function-local variables are implementation detail, not structure.
            if kind in _CALLABLE_KINDS and node.kind in _LOCAL_KINDS:
                continue
            children.append(node)
    children.sort(key=lambda node: (node.line, node.name))
    return OutlineNode(
        name=name,
        kind=kind,
        line=rng[0],
        end_line=rng[2],
        detail=detail.strip() if isinstance(detail, str) else "",
        children=children,
    )


def _outline_from_symbol_information(items: list[Any], *, cwd: str | None) -> list[OutlineNode]:
    """Rebuild a hierarchy from flat symbols using ``containerName``."""
    flat = normalize_symbols(items, cwd=cwd)
    nodes: dict[str, OutlineNode] = {}
    roots: list[OutlineNode] = []
    for item in flat:
        node = OutlineNode(
            name=item.name,
            kind=item.kind,
            line=item.line,
            end_line=item.end_line,
            detail="",
            children=[],
        )
        nodes.setdefault(item.name, node)
        parent = nodes.get(item.container) if item.container else None
        if parent is not None and parent is not node:
            parent.children.append(node)
        else:
            roots.append(node)
    return roots


def build_outline(items: list[Any], *, cwd: str | None) -> list[OutlineNode]:
    """Build an outline from ``DocumentSymbol[]`` or ``SymbolInformation[]``.

    Results from several servers are merged; duplicate root symbols (same
    name, kind and line) are dropped.
    """
    hierarchical = [raw for raw in items if isinstance(raw, dict) and "location" not in raw]
    flat = [raw for raw in items if isinstance(raw, dict) and "location" in raw]
    roots: list[OutlineNode] = []
    budget = [MAX_OUTLINE_NODES]
    for raw in hierarchical:
        if budget[0] <= 0:
            break
        node = _outline_from_document_symbol(raw, budget=budget)
        if node is not None:
            roots.append(node)
    if flat:
        roots.extend(_outline_from_symbol_information(flat, cwd=cwd))
    seen: set[tuple[str, str, int]] = set()
    unique: list[OutlineNode] = []
    for node in sorted(roots, key=lambda node: (node.line, node.name)):
        key = (node.name, node.kind, node.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(node)
    return unique


def format_outline(
    roots: list[OutlineNode],
    *,
    limit: int,
    max_depth: int = 4,
    indent: str = "  ",
) -> Listing:
    """Render an outline as indented ``kind name (L10-L42)  detail`` lines."""
    lines: list[str] = []
    items: list[dict[str, Any]] = []
    total = 0
    shown = 0

    def count(node: OutlineNode) -> int:
        return 1 + sum(count(child) for child in node.children)

    for root in roots:
        total += count(root)

    def walk(node: OutlineNode, depth: int) -> None:
        nonlocal shown
        if shown >= limit:
            return
        span = f"L{node.line}" if node.end_line <= node.line else f"L{node.line}-{node.end_line}"
        detail = f"  {node.detail[:MAX_SNIPPET_CHARS]}" if node.detail else ""
        lines.append(f"{indent * depth}{node.kind} {node.name} ({span}){detail}")
        shown += 1
        if depth + 1 >= max_depth and node.children:
            nested = count(node) - 1
            lines.append(f"{indent * (depth + 1)}... {nested} nested symbol(s)")
            shown += nested
            return
        for child in node.children:
            walk(child, depth + 1)

    for root in roots:
        walk(root, 0)
        if shown < limit:
            items.append(root.to_metadata())
    truncated = shown < total
    if truncated:
        lines.append(f"... {total - shown} more symbol(s) (raise limit to see them)")
    return Listing(
        text="\n".join(lines), total=total, shown=shown, truncated=truncated, items=items
    )


def make_snippet_loader(
    *, cwd: str | None, cache: dict[str, list[str] | None]
) -> Callable[[str, int], str | None]:
    """Return a loader that reads one trimmed source line per request.

    Locations come from an untrusted server, so snippets are read only from
    files that resolve inside ``cwd`` (symlinks followed); anything else
    yields no snippet.  File contents are cached per call so multi-reference
    files are read once.  Unreadable files yield no snippet rather than an
    error.
    """
    root = os.path.realpath(cwd) if cwd else None

    def load(path: str, line: int) -> str | None:
        if root is None:
            return None
        absolute = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
        if absolute != root and not absolute.startswith(root + os.sep):
            return None
        if absolute not in cache:
            try:
                with open(absolute, encoding="utf-8", errors="replace") as handle:
                    cache[absolute] = handle.read().splitlines()
            except OSError:
                cache[absolute] = None
        lines = cache[absolute]
        if lines is None or line < 1 or line > len(lines):
            return None
        text = lines[line - 1].strip()
        if len(text) > MAX_SNIPPET_CHARS:
            text = text[: MAX_SNIPPET_CHARS - 3] + "..."
        return text

    return load


def bound_output(text: str, *, max_bytes: int = MAX_OUTPUT_BYTES) -> tuple[str, bool]:
    """Cap output bytes as a last line of defence behind per-listing limits."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    clipped = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return clipped.rstrip() + "\n... (output truncated)", True
