"""Executor-native LSP query tool.

One ``lsp`` tool exposes deliberate semantic navigation.  Every operation
returns compact text (see :mod:`cognis.tools.executor.lsp.format`) plus
bounded metadata describing status, counts, truncation and per-server
provenance.  Raw protocol payloads never reach the model.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, replace
from typing import Any, Literal

from cognis.models.tool import ToolResult
from cognis.tools.executor.lsp.diagnostics import format_diagnostics_for_llm
from cognis.tools.executor.lsp.format import (
    Listing,
    bound_output,
    build_outline,
    clamp_limit,
    format_hover,
    format_locations,
    format_outline,
    format_workspace_symbols,
    make_snippet_loader,
    normalize_locations,
    normalize_symbols,
    relative_path,
)
from cognis.tools.executor.lsp.hierarchy import Direction, HierarchyLimits, format_call_tree
from cognis.tools.executor.lsp.outline import OutlineLimits, outline_directory, render_outline
from cognis.tools.executor.lsp.query import QueryOutcome, QueryStatus, aggregate_status
from cognis.tools.executor.lsp.types import DiagnosticFreshness
from cognis.tools.executor.paths import resolve_path, runtime_working_directory
from cognis.tools.registry import ToolExecutionContext

OperationKind = Literal[
    "position", "document", "workspace", "capabilities", "diagnostics", "hierarchy", "outline"
]


@dataclass(slots=True, frozen=True)
class OperationSpec:
    """Static description of one tool operation."""

    name: str
    kind: OperationKind
    manager_method: str | None
    lsp_method: str | None


_OPERATIONS: dict[str, OperationSpec] = {
    spec.name: spec
    for spec in (
        OperationSpec("goToDefinition", "position", "definition", "textDocument/definition"),
        OperationSpec(
            "typeDefinition", "position", "type_definition", "textDocument/typeDefinition"
        ),
        OperationSpec(
            "goToImplementation", "position", "implementation", "textDocument/implementation"
        ),
        OperationSpec("findReferences", "position", "references", "textDocument/references"),
        OperationSpec("hover", "position", "hover", "textDocument/hover"),
        OperationSpec(
            "documentSymbol", "document", "document_symbol", "textDocument/documentSymbol"
        ),
        OperationSpec("workspaceSymbol", "workspace", "workspace_symbol", "workspace/symbol"),
        OperationSpec("incomingCalls", "hierarchy", None, "callHierarchy/incomingCalls"),
        OperationSpec("outgoingCalls", "hierarchy", None, "callHierarchy/outgoingCalls"),
        OperationSpec("outline", "outline", None, "textDocument/documentSymbol"),
        OperationSpec("capabilities", "capabilities", None, None),
        OperationSpec("diagnostics", "diagnostics", None, None),
    )
}

#: Operations reported by ``capabilities``, keyed by the LSP method that gates them.
_METHOD_TO_OPERATIONS: dict[str, tuple[str, ...]] = {
    "textDocument/definition": ("goToDefinition",),
    "textDocument/typeDefinition": ("typeDefinition",),
    "textDocument/implementation": ("goToImplementation",),
    "textDocument/references": ("findReferences",),
    "textDocument/hover": ("hover",),
    "textDocument/documentSymbol": ("documentSymbol", "outline"),
    "workspace/symbol": ("workspaceSymbol",),
    "textDocument/prepareCallHierarchy": ("incomingCalls", "outgoingCalls"),
}

_STATUS_HINTS: dict[QueryStatus, str] = {
    QueryStatus.EMPTY: "No results. The symbol may be unresolved or defined outside the workspace.",
    QueryStatus.UNSUPPORTED: (
        "The available server does not support this operation. Use grep as a fallback."
    ),
    QueryStatus.TIMEOUT: "The language server did not answer in time. Retry or use grep.",
    QueryStatus.FAILED: "The language server request failed. Use grep as a fallback.",
}


@dataclass(slots=True)
class _Request:
    operation: OperationSpec
    raw_path: str
    resolved_path: str
    line: int
    character: int
    query: str
    limit: int
    depth: Any = None
    raw_limit: Any = None


async def handle_lsp(arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
    """Run an LSP query against the current workspace."""

    lsp = context.runtime_metadata.get("lsp_manager")
    if lsp is None or not hasattr(lsp, "prepare_file") or not hasattr(lsp, "has_clients"):
        return ToolResult(output="LSP is not available in this executor.", is_error=True)

    request_or_error = _parse_request(arguments, context)
    if isinstance(request_or_error, ToolResult):
        return request_or_error
    request = request_or_error
    cwd = runtime_working_directory(context.runtime_metadata)
    display_path = relative_path(request.resolved_path, cwd)

    spec = request.operation
    if spec.kind == "outline":
        if os.path.isdir(request.resolved_path):
            return await _handle_outline(lsp, request, display_path, cwd)
        # A single-file outline is the documentSymbol operation.
        spec = _OPERATIONS["documentSymbol"]
        request = replace(request, operation=spec)

    if not await lsp.has_clients(request.resolved_path):
        ext = os.path.splitext(request.resolved_path)[1] or "(no extension)"
        return ToolResult(
            output=(f"No LSP server available for {ext} files. Use grep and read instead."),
            is_error=True,
            metadata=_metadata(request.operation.name, QueryStatus.UNSUPPORTED, [], None, ""),
        )

    if spec.kind == "capabilities":
        return await _handle_capabilities(lsp, request, display_path)
    if spec.kind == "diagnostics":
        return await _handle_diagnostics(lsp, request, display_path, cwd)
    if spec.kind == "hierarchy":
        return await _handle_hierarchy(lsp, request, display_path, cwd)

    assert spec.manager_method is not None
    method = getattr(lsp, spec.manager_method)
    if spec.kind == "workspace":
        outcomes: list[QueryOutcome] = await method(request.resolved_path, request.query)
    elif spec.kind == "document":
        outcomes = await method(request.resolved_path)
    else:
        outcomes = await method(request.resolved_path, request.line - 1, request.character - 1)

    items = [item for outcome in outcomes for item in outcome.items]
    status = aggregate_status(outcomes)
    listing = await _render(spec, items, request, cwd)

    target = _target_label(spec, display_path, request)
    header = f"{spec.name} {target}: {_count_label(listing, status)}"
    body_parts = [header]
    if listing.text:
        body_parts.append(listing.text)
    hint = _STATUS_HINTS.get(status)
    if hint and not listing.text:
        body_parts.append(hint)
    footer = _server_footer(outcomes)
    if footer:
        body_parts.append(footer)
    output, clipped = bound_output("\n".join(body_parts))

    is_error = status in (QueryStatus.TIMEOUT, QueryStatus.FAILED) and not items
    return ToolResult(
        output=output,
        is_error=is_error,
        metadata=_metadata(
            spec.name,
            status,
            outcomes,
            listing,
            output,
            title=f"{spec.name} {target}",
            truncated=listing.truncated or clipped,
        ),
    )


def _parse_request(
    arguments: dict[str, Any], context: ToolExecutionContext
) -> _Request | ToolResult:
    operation = str(arguments.get("operation") or "")
    spec = _OPERATIONS.get(operation)
    if spec is None:
        return ToolResult(
            output=(
                f"Unsupported LSP operation: {operation}. "
                f"Valid operations: {', '.join(_OPERATIONS)}."
            ),
            is_error=True,
        )

    query = str(arguments.get("query") or "")
    if spec.kind == "workspace" and not query.strip():
        return ToolResult(output="workspaceSymbol requires a non-empty query.", is_error=True)

    line = 1
    character = 1
    if spec.kind in ("position", "hierarchy"):
        line_value = arguments.get("line")
        character_value = arguments.get("character")
        if line_value is None or character_value is None:
            return ToolResult(
                output=f"{operation} requires both line and character arguments (1-based).",
                is_error=True,
            )
        try:
            line = int(line_value)
            character = int(character_value)
        except (TypeError, ValueError):
            return ToolResult(output="line and character must be integers.", is_error=True)
        if line < 1 or character < 1:
            return ToolResult(output="line and character are 1-based.", is_error=True)

    raw_path = str(arguments.get("file_path") or "")
    if not raw_path:
        return ToolResult(output="file_path is required.", is_error=True)
    try:
        resolved_path = str(resolve_path(raw_path, context=context))
    except ValueError as exc:
        return ToolResult(output=str(exc), is_error=True)
    if not os.path.exists(resolved_path):
        return ToolResult(output=f"Path does not exist: {raw_path}", is_error=True)
    if not os.path.isfile(resolved_path) and not (
        spec.kind == "outline" and os.path.isdir(resolved_path)
    ):
        return ToolResult(output=f"Not a file: {raw_path}", is_error=True)

    return _Request(
        operation=spec,
        raw_path=raw_path,
        resolved_path=resolved_path,
        line=line,
        character=character,
        query=query.strip(),
        limit=clamp_limit(arguments.get("limit")),
        depth=arguments.get("depth"),
        raw_limit=arguments.get("limit"),
    )


async def _render(
    spec: OperationSpec, items: list[Any], request: _Request, cwd: str | None
) -> Listing:
    if spec.name == "hover":
        return format_hover(items)
    if spec.name == "documentSymbol":
        return format_outline(build_outline(items, cwd=cwd), limit=request.limit)
    if spec.name == "workspaceSymbol":
        return format_workspace_symbols(normalize_symbols(items, cwd=cwd), limit=request.limit)
    locations = normalize_locations(items, cwd=cwd)
    if spec.name == "findReferences":
        cache: dict[str, list[str] | None] = {}
        loader = make_snippet_loader(cwd=cwd, cache=cache)
        return await asyncio.to_thread(
            format_locations, locations, limit=request.limit, snippet_loader=loader
        )
    return format_locations(locations, limit=request.limit)


def _target_label(spec: OperationSpec, display_path: str, request: _Request) -> str:
    if spec.kind in ("position", "hierarchy"):
        return f"{display_path}:{request.line}:{request.character}"
    if spec.kind == "workspace":
        return f"{request.query!r}"
    return display_path


def _count_label(listing: Listing, status: QueryStatus) -> str:
    if status is QueryStatus.UNSUPPORTED:
        return "unsupported"
    if status in (QueryStatus.TIMEOUT, QueryStatus.FAILED) and listing.total == 0:
        return status.value
    noun = "result" if listing.total == 1 else "results"
    label = f"{listing.total} {noun}"
    if listing.truncated and listing.shown < listing.total:
        label += f" (showing {listing.shown})"
    if status is QueryStatus.PARTIAL:
        label += ", partial"
    return label


def _server_footer(outcomes: list[QueryOutcome]) -> str:
    notes = [
        f"{outcome.server_id}: {outcome.status.value}"
        + (f" ({outcome.message})" if outcome.message else "")
        for outcome in outcomes
        if outcome.status not in (QueryStatus.OK, QueryStatus.EMPTY)
    ]
    if not notes:
        return ""
    return "servers: " + "; ".join(notes)


def _metadata(
    operation: str,
    status: QueryStatus,
    outcomes: list[QueryOutcome],
    listing: Listing | None,
    output: str,
    *,
    title: str | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "operation": operation,
        "status": status.value,
        "result_count": listing.total if listing else 0,
        "shown": listing.shown if listing else 0,
        "truncated": truncated,
        "output_bytes": len(output.encode("utf-8")),
        "servers": [
            {
                "server_id": outcome.server_id,
                "status": outcome.status.value,
                "duration_ms": outcome.duration_ms,
            }
            for outcome in outcomes
        ],
        "result": listing.items if listing else [],
    }
    if title:
        data["title"] = title
    return data


async def _handle_hierarchy(
    lsp: Any, request: _Request, display_path: str, cwd: str | None
) -> ToolResult:
    spec = request.operation
    direction: Direction = "incoming" if spec.name == "incomingCalls" else "outgoing"
    if not hasattr(lsp, "call_hierarchy"):
        return ToolResult(output="Call hierarchy is not available in this executor.", is_error=True)
    limits = HierarchyLimits.from_arguments(request.depth)
    outcomes, result = await lsp.call_hierarchy(
        request.resolved_path,
        request.line - 1,
        request.character - 1,
        direction=direction,
        limits=limits,
        cwd=cwd,
    )
    target = f"{display_path}:{request.line}:{request.character}"
    title = f"{spec.name} {target}"
    if result is None:
        status = aggregate_status(outcomes)
        output = "\n".join(
            part
            for part in (
                f"{spec.name} {target}: unsupported",
                _STATUS_HINTS[QueryStatus.UNSUPPORTED],
                _server_footer(outcomes),
            )
            if part
        )
        return ToolResult(
            output=output,
            metadata=_metadata(spec.name, status, outcomes, None, output, title=title),
        )

    listing = format_call_tree(result, direction=direction)
    noun = "caller" if direction == "incoming" else "callee"
    if result.status in (QueryStatus.TIMEOUT, QueryStatus.FAILED) and not result.roots:
        count = result.status.value
    else:
        count = f"{result.edge_count} {noun}{'' if result.edge_count == 1 else 's'}"
        count += f", depth {result.depth_reached}"
        if result.stop_reason:
            count += f", partial ({result.stop_reason})"
    body_parts = [f"{spec.name} {target}: {count}"]
    if listing.text:
        body_parts.append(listing.text)
    elif result.status is QueryStatus.EMPTY:
        body_parts.append("No callable symbol at this position, or no calls found.")
    else:
        hint = _STATUS_HINTS.get(result.status)
        if hint:
            body_parts.append(hint)
    footer = _server_footer([o for o in outcomes if o.status is not QueryStatus.PARTIAL])
    if footer:
        body_parts.append(footer)
    output, clipped = bound_output("\n".join(body_parts))
    metadata = _metadata(
        spec.name,
        result.status,
        outcomes,
        listing,
        output,
        title=title,
        truncated=listing.truncated or clipped,
    )
    metadata["depth_reached"] = result.depth_reached
    metadata["edge_count"] = result.edge_count
    metadata["node_count"] = result.node_count
    if result.stop_reason:
        metadata["stop_reason"] = result.stop_reason
    return ToolResult(
        output=output,
        is_error=result.status in (QueryStatus.TIMEOUT, QueryStatus.FAILED) and not result.roots,
        metadata=metadata,
    )


async def _handle_outline(
    lsp: Any, request: _Request, display_path: str, cwd: str | None
) -> ToolResult:
    spec = request.operation
    title = f"{spec.name} {display_path}/"
    if not hasattr(lsp, "document_symbol_cached"):
        return ToolResult(output="Outline is not available in this executor.", is_error=True)
    limits = OutlineLimits.from_arguments(request.raw_limit)
    result = await outline_directory(
        request.resolved_path,
        fetch_symbols=lsp.document_symbol_cached,
        limits=limits,
        cwd=cwd,
    )
    rendering = render_outline(result, limits=limits)
    supported = result.enumeration.supported_total
    if not result.files:
        if result.enumeration.files:
            summary = "timeout"
        elif supported == 0:
            summary = "no supported source files"
        else:
            summary = "0 files"
    else:
        summary = f"{rendering.files_shown} of {supported} file{'' if supported == 1 else 's'}"
        summary += f", {rendering.symbols_shown} symbols"
        if result.status is QueryStatus.PARTIAL:
            summary += ", partial"
    body_parts = [f"{title}: {summary}"]
    if rendering.text:
        body_parts.append(rendering.text)
    if supported == 0:
        body_parts.append("No files with a configured language server. Use glob and read instead.")
    server_outcomes = _dedupe_server_outcomes(result.server_outcomes)
    footer = _server_footer(server_outcomes)
    if footer:
        body_parts.append(footer)
    output, clipped = bound_output("\n".join(body_parts))
    metadata = _metadata(
        spec.name,
        result.status,
        server_outcomes,
        None,
        output,
        title=title,
        truncated=rendering.truncated or clipped,
    )
    metadata["result"] = rendering.items
    metadata["result_count"] = rendering.symbols_shown
    metadata["shown"] = rendering.symbols_shown
    metadata["files_shown"] = rendering.files_shown
    metadata["files_supported"] = supported
    metadata["files_unsupported"] = sum(result.enumeration.unsupported_by_extension.values())
    metadata["files_cached"] = sum(1 for entry in result.files if entry.cached)
    if rendering.truncated_reason:
        metadata["stop_reason"] = rendering.truncated_reason
    return ToolResult(
        output=output,
        is_error=result.status in (QueryStatus.TIMEOUT, QueryStatus.FAILED) and not result.files,
        metadata=metadata,
    )


_STATUS_SEVERITY = (
    QueryStatus.FAILED,
    QueryStatus.TIMEOUT,
    QueryStatus.UNSUPPORTED,
    QueryStatus.PARTIAL,
    QueryStatus.EMPTY,
    QueryStatus.OK,
)


def _dedupe_server_outcomes(outcomes: list[QueryOutcome]) -> list[QueryOutcome]:
    """Collapse per-file outcomes to the worst status seen per server."""
    worst: dict[str, QueryOutcome] = {}
    for outcome in outcomes:
        current = worst.get(outcome.server_id)
        if current is None or _STATUS_SEVERITY.index(outcome.status) < _STATUS_SEVERITY.index(
            current.status
        ):
            worst[outcome.server_id] = outcome
    return [worst[key] for key in sorted(worst)]


async def _handle_capabilities(lsp: Any, request: _Request, display_path: str) -> ToolResult:
    prepared = await lsp.prepare_file(request.resolved_path)
    lines = [f"capabilities {display_path}:"]
    servers: list[dict[str, Any]] = []
    if not prepared:
        lines.append("no language server could be started for this file")
    for entry in prepared:
        client = entry.client
        supported = client.supported_methods(uri=entry.uri, language_id=entry.language_id)
        operations = sorted(
            operation
            for method, names in _METHOD_TO_OPERATIONS.items()
            if supported.get(method)
            for operation in names
        )
        unsupported = sorted(
            operation
            for method, names in _METHOD_TO_OPERATIONS.items()
            if not supported.get(method)
            for operation in names
        )
        lines.append(f"{client.server_id}: {', '.join(operations) or 'none'}")
        if unsupported:
            lines.append(f"  unsupported: {', '.join(unsupported)}")
        servers.append(
            {
                "server_id": client.server_id,
                "status": QueryStatus.OK.value,
                "operations": operations,
            }
        )
    output = "\n".join(lines)
    status = QueryStatus.OK if prepared else QueryStatus.UNSUPPORTED
    return ToolResult(
        output=output,
        metadata={
            "operation": "capabilities",
            "status": status.value,
            "result_count": len(servers),
            "shown": len(servers),
            "truncated": False,
            "output_bytes": len(output.encode("utf-8")),
            "servers": servers,
            "result": servers,
            "title": f"capabilities {display_path}",
        },
    )


async def _handle_diagnostics(
    lsp: Any, request: _Request, display_path: str, cwd: str | None
) -> ToolResult:
    """Run every semantic server for the file and report fresh diagnostics.

    Unlike edit-time injection, this path deliberately includes heavyweight
    analyzers (for example Pyright for Python) because the agent asked.
    """
    collection = await lsp.touch_file(request.resolved_path, wait=True, purpose="semantic")
    waits = list(getattr(collection, "waits", []))
    snapshots = collection.snapshots_by_path.get(request.resolved_path, [])
    diagnostics = [diag for snapshot in snapshots for diag in snapshot.diagnostics]
    body = format_diagnostics_for_llm(
        {request.resolved_path: diagnostics}, request.resolved_path, cwd=cwd
    )
    error_count = sum(1 for diag in diagnostics if diag.is_error)
    warning_count = sum(1 for diag in diagnostics if diag.is_warning)
    fresh = [wait for wait in waits if wait.status in _FRESH_STATES]
    if not waits:
        status = QueryStatus.UNSUPPORTED
    elif fresh:
        status = QueryStatus.OK if diagnostics else QueryStatus.EMPTY
        if len(fresh) < len(waits):
            status = QueryStatus.PARTIAL
    elif any(wait.status is DiagnosticFreshness.TIMEOUT for wait in waits):
        status = QueryStatus.TIMEOUT
    else:
        status = QueryStatus.FAILED

    lines = [f"diagnostics {display_path}: {error_count} error(s), {warning_count} warning(s)"]
    if body:
        lines.append(body)
    elif status in (QueryStatus.EMPTY, QueryStatus.OK):
        lines.append("no errors or warnings")
    elif status is QueryStatus.UNSUPPORTED:
        lines.append("no language server produced diagnostics for this file")
    notes = [
        f"{wait.server_id}: {wait.status.value}"
        for wait in waits
        if wait.status not in _FRESH_STATES
    ]
    if notes:
        lines.append("servers: " + "; ".join(notes))
    output, clipped = bound_output("\n".join(lines))
    return ToolResult(
        output=output,
        is_error=status in (QueryStatus.TIMEOUT, QueryStatus.FAILED),
        metadata={
            "operation": "diagnostics",
            "status": status.value,
            "result_count": len(diagnostics),
            "shown": len(diagnostics),
            "truncated": clipped,
            "output_bytes": len(output.encode("utf-8")),
            "servers": [
                {
                    "server_id": wait.server_id,
                    "status": wait.status.value,
                    "duration_ms": wait.duration_ms,
                }
                for wait in waits
            ],
            "result": {"errors": error_count, "warnings": warning_count},
            "title": f"diagnostics {display_path}",
        },
    )


_FRESH_STATES = (DiagnosticFreshness.FRESH, DiagnosticFreshness.FRESH_UNVERSIONED)
