"""Controller-side metrics for executor LSP activity.

Executors have no metrics endpoint, so LSP facts travel to the controller
as bounded fields in tool result metadata and are counted here at the tool
routing boundary.  Two paths are measured separately:

* automatic post-edit diagnostics injected by ``edit``/``multiedit``/``write``
  (metadata key ``lsp_diagnostics``);
* deliberate ``lsp`` tool operations.

Every label value is validated against a fixed enum before use.  Paths,
symbols, queries, URIs, error text and server identifiers never become
labels; server outcomes stay in the audited result metadata only.
"""

from __future__ import annotations

import logging
from typing import Any

from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

LSP_EDIT_TOOLS = frozenset({"edit", "multiedit", "write", "apply_patch"})
LSP_TOOL_NAME = "lsp"

EDIT_DIAGNOSTIC_STATUSES = frozenset({"fresh", "timeout", "failed", "unavailable"})
EDIT_INJECTION_OUTCOMES = frozenset({"injected", "clean", "suppressed_unchanged", "none"})
EDIT_WAIT_STATUSES = frozenset(
    {"fresh", "fresh_unversioned", "stale", "timeout", "unavailable", "failed"}
)
TOOL_OPERATIONS = frozenset(
    {
        "goToDefinition",
        "typeDefinition",
        "goToImplementation",
        "findReferences",
        "hover",
        "documentSymbol",
        "workspaceSymbol",
        "incomingCalls",
        "outgoingCalls",
        "outline",
        "capabilities",
        "diagnostics",
    }
)
TOOL_STATUSES = frozenset({"ok", "empty", "unsupported", "partial", "timeout", "failed"})
OTHER = "other"
# Metadata comes from an untrusted executor; numbers above this are junk.
_MAX_INT = 2**53

_BYTES_BUCKETS = (256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
_SECONDS_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20)

LSP_EDIT_DIAGNOSTICS_TOTAL = Counter(
    "cognis_lsp_edit_diagnostics_total",
    "Post-edit LSP diagnostic collections by overall freshness status",
    labelnames=("status",),
)
LSP_EDIT_INJECTION_TOTAL = Counter(
    "cognis_lsp_edit_injection_total",
    "Post-edit LSP injection outcome",
    labelnames=("outcome",),
)
LSP_EDIT_WAIT_TOTAL = Counter(
    "cognis_lsp_edit_wait_total",
    "Per-server post-edit diagnostic waits by freshness status",
    labelnames=("status",),
)
LSP_EDIT_DIAGNOSTICS_BY_SEVERITY_TOTAL = Counter(
    "cognis_lsp_edit_diagnostics_by_severity_total",
    "Fresh post-edit diagnostics received, by severity",
    labelnames=("severity",),
)
LSP_EDIT_INJECTED_BYTES = Histogram(
    "cognis_lsp_edit_injected_bytes",
    "Bytes of LSP diagnostics text appended to edit results",
    buckets=_BYTES_BUCKETS,
)
LSP_TOOL_OPERATIONS_TOTAL = Counter(
    "cognis_lsp_tool_operations_total",
    "Deliberate lsp tool calls by operation and status",
    labelnames=("operation", "status"),
)
LSP_TOOL_DURATION_SECONDS = Histogram(
    "cognis_lsp_tool_duration_seconds",
    "Executor-side duration of lsp tool calls",
    labelnames=("operation",),
    buckets=_SECONDS_BUCKETS,
)
LSP_TOOL_OUTPUT_BYTES = Histogram(
    "cognis_lsp_tool_output_bytes",
    "Output bytes returned by lsp tool calls",
    labelnames=("operation",),
    buckets=_BYTES_BUCKETS,
)
LSP_TOOL_TRUNCATED_TOTAL = Counter(
    "cognis_lsp_tool_truncated_total",
    "lsp tool calls whose output was truncated by a limit or budget",
    labelnames=("operation",),
)
LSP_TOOL_HIERARCHY_EDGES = Histogram(
    "cognis_lsp_tool_hierarchy_edges",
    "Edges returned by call hierarchy operations",
    buckets=(1, 5, 10, 20, 50, 100, 200),
)


def _label(value: Any, allowed: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in allowed else OTHER


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return min(int(value), _MAX_INT)


def record_lsp_tool_result(tool_name: str, metadata: Any, duration_ms: Any) -> None:
    """Count LSP facts carried by one tool result.

    No-op for tools that are neither an edit tool nor ``lsp``, and for
    results without the expected metadata shape.  Never raises.
    """
    if not isinstance(metadata, dict):
        return
    try:
        if tool_name in LSP_EDIT_TOOLS:
            _record_edit_diagnostics(metadata.get("lsp_diagnostics"))
        elif tool_name == LSP_TOOL_NAME:
            _record_tool_operation(metadata, duration_ms)
    except Exception:
        # Telemetry must never fail tool result routing.
        logger.debug("lsp telemetry: failed to record tool result", exc_info=True)


def _record_edit_diagnostics(data: Any) -> None:
    if not isinstance(data, dict):
        return
    LSP_EDIT_DIAGNOSTICS_TOTAL.labels(
        status=_label(data.get("status"), EDIT_DIAGNOSTIC_STATUSES)
    ).inc()
    LSP_EDIT_INJECTION_TOTAL.labels(
        outcome=_label(data.get("injection"), EDIT_INJECTION_OUTCOMES)
    ).inc()
    status_counts = data.get("status_counts")
    if isinstance(status_counts, dict):
        for status, count in status_counts.items():
            amount = _non_negative_int(count)
            if amount:
                LSP_EDIT_WAIT_TOTAL.labels(status=_label(status, EDIT_WAIT_STATUSES)).inc(amount)
    errors = _non_negative_int(data.get("error_count"))
    if errors:
        LSP_EDIT_DIAGNOSTICS_BY_SEVERITY_TOTAL.labels(severity="error").inc(errors)
    warnings = _non_negative_int(data.get("warning_count"))
    if warnings:
        LSP_EDIT_DIAGNOSTICS_BY_SEVERITY_TOTAL.labels(severity="warning").inc(warnings)
    injected = _non_negative_int(data.get("injected_bytes"))
    if injected is not None and data.get("injection") == "injected":
        LSP_EDIT_INJECTED_BYTES.observe(injected)


def _record_tool_operation(metadata: dict[str, Any], duration_ms: Any) -> None:
    operation = _label(metadata.get("operation"), TOOL_OPERATIONS)
    status = _label(metadata.get("status"), TOOL_STATUSES)
    LSP_TOOL_OPERATIONS_TOTAL.labels(operation=operation, status=status).inc()
    duration = _non_negative_int(duration_ms)
    if duration is not None:
        LSP_TOOL_DURATION_SECONDS.labels(operation=operation).observe(duration / 1000)
    output_bytes = _non_negative_int(metadata.get("output_bytes"))
    if output_bytes is not None:
        LSP_TOOL_OUTPUT_BYTES.labels(operation=operation).observe(output_bytes)
    if metadata.get("truncated") is True:
        LSP_TOOL_TRUNCATED_TOTAL.labels(operation=operation).inc()
    edges = _non_negative_int(metadata.get("edge_count"))
    if edges is not None and operation in ("incomingCalls", "outgoingCalls"):
        LSP_TOOL_HIERARCHY_EDGES.observe(edges)
