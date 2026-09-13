"""Bounded directory outline built from cached document symbols.

The outline answers "what is in this package" with symbol signatures only.
It never fetches references or call hierarchy for the listed symbols and it
never walks outside the resolved directory.  Every dimension is bounded:
files considered, symbols per file, nesting depth, total output bytes and
wall time.  Files whose extension has no semantic server are reported as
unsupported rather than silently dropped.
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from cognis.tools.executor.filesystem import DEFAULT_IGNORE_NAMES
from cognis.tools.executor.lsp.format import (
    MAX_SNIPPET_CHARS,
    OutlineNode,
    build_outline,
    relative_path,
)
from cognis.tools.executor.lsp.query import QueryOutcome, QueryStatus, aggregate_status
from cognis.tools.executor.lsp.servers import get_servers_for_extension

MAX_UNSUPPORTED_EXTENSIONS_SHOWN = 5
# Data members nested in a container are attributes, not structure; the
# directory outline keeps callables and properties so methods are not pushed
# out of the per-file budget by instance variables.
_NESTED_DATA_KINDS = frozenset({"variable", "constant", "field"})
# Upper bound on directory entries visited during enumeration so a huge tree
# cannot turn the outline into a filesystem scan.
MAX_ENTRIES_WALKED = 5000


@dataclass(slots=True, frozen=True)
class OutlineLimits:
    """Hard bounds for one directory outline."""

    max_files: int = 25
    max_symbols_per_file: int = 30
    max_depth: int = 2
    max_bytes: int = 12 * 1024
    time_budget_s: float = 20.0

    @classmethod
    def from_arguments(cls, limit: Any) -> OutlineLimits:
        """Build limits from the tool ``limit`` argument (files to include)."""
        default = cls()
        max_files = default.max_files
        if isinstance(limit, int) and not isinstance(limit, bool):
            max_files = max(1, min(100, limit))
        return cls(max_files=max_files)


@dataclass(slots=True)
class Enumeration:
    """Deterministic list of candidate source files under a directory."""

    files: list[str]
    """Absolute paths with a semantic server, in stable order, capped."""
    supported_total: int
    """Supported files seen, including those beyond the cap."""
    unsupported_by_extension: Counter[str]
    walk_truncated: bool


def _is_supported(ext: str) -> bool:
    return bool(ext) and bool(get_servers_for_extension(ext, purpose="semantic"))


def enumerate_source_files(directory: str, *, max_files: int) -> Enumeration:
    """Walk ``directory`` breadth-first with sorted entries.

    Hidden entries and the shared filesystem ignore set are skipped.  Files
    directly in the directory come before files in subdirectories so the
    outline of a package starts with its own modules.
    """
    files: list[str] = []
    supported_total = 0
    unsupported: Counter[str] = Counter()
    visited = 0
    truncated = False
    queue = [os.path.abspath(directory)]
    while queue:
        current = queue.pop(0)
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError:
            continue
        subdirs: list[str] = []
        for entry in entries:
            visited += 1
            if visited > MAX_ENTRIES_WALKED:
                truncated = True
                break
            name = entry.name
            if name.startswith(".") or name in DEFAULT_IGNORE_NAMES:
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    subdirs.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            ext = os.path.splitext(name)[1].lower()
            if _is_supported(ext):
                supported_total += 1
                if len(files) < max_files:
                    files.append(entry.path)
            else:
                unsupported[ext or "(none)"] += 1
        if truncated:
            break
        queue.extend(subdirs)
    return Enumeration(
        files=files,
        supported_total=supported_total,
        unsupported_by_extension=unsupported,
        walk_truncated=truncated,
    )


@dataclass(slots=True)
class FileOutline:
    """Outline facts for one file."""

    path: str
    roots: list[OutlineNode]
    outcomes: list[QueryOutcome]
    cached: bool
    status: QueryStatus

    @property
    def symbol_count(self) -> int:
        return sum(_count_structural(root) for root in self.roots)


def _structural_children(node: OutlineNode) -> list[OutlineNode]:
    return [child for child in node.children if child.kind not in _NESTED_DATA_KINDS]


def _count_structural(node: OutlineNode) -> int:
    return 1 + sum(_count_structural(child) for child in _structural_children(node))


@dataclass(slots=True)
class OutlineResult:
    """Outcome of one directory outline."""

    files: list[FileOutline]
    enumeration: Enumeration
    status: QueryStatus
    duration_ms: int
    stop_reason: str | None = None
    """``time`` when the wall-clock budget stopped the walk early."""
    files_not_queried: int = 0
    """Enumerated files skipped because the time budget ran out."""
    server_outcomes: list[QueryOutcome] = field(default_factory=list)
    """Flattened per-file server outcomes for provenance/footer."""


SymbolFetcher = Callable[[str], Awaitable[tuple[list[QueryOutcome], bool]]]


async def outline_directory(
    directory: str,
    *,
    fetch_symbols: SymbolFetcher,
    limits: OutlineLimits,
    cwd: str | None,
) -> OutlineResult:
    """Enumerate files under ``directory`` and gather their outlines in order.

    ``fetch_symbols`` returns ``(outcomes, cached)`` for an absolute path;
    files are processed sequentially so one slow server cannot fan out into
    a burst of parallel document opens.
    """
    started = monotonic()
    deadline = started + limits.time_budget_s
    enumeration = enumerate_source_files(directory, max_files=limits.max_files)
    files: list[FileOutline] = []
    stop_reason: str | None = None
    processed = 0
    for path in enumeration.files:
        remaining = deadline - monotonic()
        if remaining <= 0:
            stop_reason = "time"
            break
        try:
            # Bound the fetch itself, not only the loop: one slow server
            # (spawn, cold start, query) must not consume the whole budget.
            outcomes, cached = await asyncio.wait_for(fetch_symbols(path), timeout=remaining)
        except TimeoutError:
            stop_reason = "time"
            break
        processed += 1
        items = [item for outcome in outcomes for item in outcome.items]
        files.append(
            FileOutline(
                path=relative_path(path, cwd),
                roots=build_outline(items, cwd=cwd),
                outcomes=outcomes,
                cached=cached,
                status=aggregate_status(outcomes),
            )
        )
    server_outcomes = [outcome for entry in files for outcome in entry.outcomes]
    if not files:
        status = QueryStatus.EMPTY if not enumeration.files else QueryStatus.TIMEOUT
    elif stop_reason or any(
        entry.status in (QueryStatus.TIMEOUT, QueryStatus.FAILED, QueryStatus.PARTIAL)
        for entry in files
    ):
        status = QueryStatus.PARTIAL
    elif all(entry.status is QueryStatus.UNSUPPORTED for entry in files):
        status = QueryStatus.UNSUPPORTED
    elif all(entry.status in (QueryStatus.EMPTY, QueryStatus.UNSUPPORTED) for entry in files):
        status = QueryStatus.EMPTY
    else:
        status = QueryStatus.OK
    return OutlineResult(
        files=files,
        enumeration=enumeration,
        status=status,
        duration_ms=int((monotonic() - started) * 1000),
        stop_reason=stop_reason,
        files_not_queried=len(enumeration.files) - processed,
        server_outcomes=server_outcomes,
    )


@dataclass(slots=True)
class OutlineRendering:
    """Rendered outline text plus the facts reported about it."""

    text: str
    files_shown: int
    symbols_shown: int
    truncated: bool
    truncated_reason: str | None
    items: list[dict[str, Any]]


def _render_file(entry: FileOutline, limits: OutlineLimits, indent: str = "  ") -> list[str]:
    lines: list[str] = []
    shown = 0
    total = entry.symbol_count

    def walk(node: OutlineNode, depth: int) -> None:
        nonlocal shown
        if shown >= limits.max_symbols_per_file:
            return
        span = f"L{node.line}" if node.end_line <= node.line else f"L{node.line}-{node.end_line}"
        detail = f"  {node.detail[:MAX_SNIPPET_CHARS]}" if node.detail else ""
        lines.append(f"{indent * (depth + 1)}{node.kind} {node.name} ({span}){detail}")
        shown += 1
        if depth + 1 >= limits.max_depth:
            return
        for child in _structural_children(node):
            walk(child, depth + 1)

    for root in entry.roots:
        walk(root, 0)
    omitted = total - shown
    if omitted > 0:
        lines.append(f"{indent}... {omitted} more symbol(s)")
    return lines


def _file_header(entry: FileOutline) -> str:
    if entry.status is QueryStatus.UNSUPPORTED:
        return f"{entry.path}: unsupported (no server negotiated documentSymbol)"
    if entry.status in (QueryStatus.TIMEOUT, QueryStatus.FAILED) and not entry.roots:
        return f"{entry.path}: {entry.status.value}"
    count = entry.symbol_count
    label = f"{entry.path}: {count} symbol{'' if count == 1 else 's'}"
    if entry.status is QueryStatus.PARTIAL:
        label += " (partial)"
    return label


def render_outline(result: OutlineResult, *, limits: OutlineLimits) -> OutlineRendering:
    """Render files in order until the byte budget is exhausted."""
    blocks: list[str] = []
    items: list[dict[str, Any]] = []
    used = 0
    files_shown = 0
    symbols_shown = 0
    truncated_reason: str | None = None
    for entry in result.files:
        block_lines = [_file_header(entry), *_render_file(entry, limits)]
        block = "\n".join(block_lines)
        size = len(block.encode("utf-8")) + 1
        if used + size > limits.max_bytes and files_shown > 0:
            truncated_reason = "bytes"
            break
        blocks.append(block)
        used += size
        files_shown += 1
        symbols_shown += min(entry.symbol_count, limits.max_symbols_per_file)
        items.append(
            {
                "path": entry.path,
                "status": entry.status.value,
                "symbol_count": entry.symbol_count,
                "cached": entry.cached,
                "symbols": [
                    root.to_metadata() for root in entry.roots[: limits.max_symbols_per_file]
                ],
            }
        )

    notes: list[str] = []
    hidden_files = len(result.files) - files_shown
    if hidden_files > 0:
        notes.append(f"... {hidden_files} more file(s) not shown (output budget)")
    if result.files_not_queried > 0:
        notes.append(f"... {result.files_not_queried} file(s) not queried (time budget)")
    beyond_cap = result.enumeration.supported_total - len(result.enumeration.files)
    if beyond_cap > 0:
        notes.append(
            f"... {beyond_cap} more supported file(s) beyond limit={limits.max_files} "
            "(raise limit or outline a subdirectory)"
        )
    if result.enumeration.walk_truncated:
        notes.append("... directory walk stopped early (too many entries)")
    unsupported = result.enumeration.unsupported_by_extension
    if unsupported:
        top = unsupported.most_common(MAX_UNSUPPORTED_EXTENSIONS_SHOWN)
        rest = sum(unsupported.values()) - sum(count for _, count in top)
        parts = ", ".join(f"{ext} ({count})" for ext, count in top)
        if rest > 0:
            parts += f", +{rest} other"
        notes.append(f"skipped {sum(unsupported.values())} file(s) without a server: {parts}")

    text = "\n".join([*blocks, *notes])
    truncated = (
        truncated_reason is not None
        or result.files_not_queried > 0
        or beyond_cap > 0
        or result.enumeration.walk_truncated
    )
    if truncated and truncated_reason is None:
        truncated_reason = result.stop_reason or "files"
    return OutlineRendering(
        text=text,
        files_shown=files_shown,
        symbols_shown=symbols_shown,
        truncated=truncated,
        truncated_reason=truncated_reason if truncated else None,
        items=items,
    )
