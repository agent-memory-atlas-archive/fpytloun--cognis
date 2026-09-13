"""Offline benchmark for the executor ``lsp`` tool on the Cognis repository.

Measures, per navigation task:

* bytes and estimated tokens of the compact tool output versus the raw
  protocol result serialized the way the tool did before compaction
  (``json.dumps(result, indent=2)``);
* cold (first call after server spawn) and warm latency.

It needs pyright on PATH or in the LSP cache and does not install anything.
No LLM is involved: this quantifies the token and latency effect of the
tool itself, not agent behavior.

Note: in this repository ``cognis`` is a regular package with
``pkgutil.extend_path`` (``packages/common/src/cognis/__init__.py``), which
pyright does not follow, so cross-package ``cognis.*`` imports are
unresolved here and definitions/references stay within the resolved
package.  Tasks therefore target same-file symbols.  Cross-file navigation
is covered by ``tests/integration/test_lsp_real_servers.py``.

Run from the repository root::

    uv run python tests/benchmarks/lsp_navigation/run_benchmark.py [--json out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cognis.models.tool import ExecutorHandle
from cognis.tools.executor.lsp.manager import LSPManager
from cognis.tools.executor.lsp.tool import handle_lsp
from cognis.tools.registry import ToolExecutionContext

REPO = Path(__file__).resolve().parents[3]
LSP_DIR = "packages/executor/src/cognis/tools/executor/lsp"


@dataclass(slots=True)
class Task:
    name: str
    operation: str
    file_path: str
    anchor: str | None = None
    """Text to locate; the position is the first character of ``symbol`` inside it."""
    symbol: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


TASKS: list[Task] = [
    Task(
        "def:PreparedClient",
        "goToDefinition",
        f"{LSP_DIR}/manager.py",
        "-> list[PreparedClient]:",
        "PreparedClient",
    ),
    Task(
        "refs:handle_lsp",
        "findReferences",
        f"{LSP_DIR}/tool.py",
        "async def handle_lsp(",
        "handle_lsp",
    ),
    Task(
        "refs:prepare_file",
        "findReferences",
        f"{LSP_DIR}/manager.py",
        "async def prepare_file(",
        "prepare_file",
    ),
    Task("hover:LSPManager", "hover", f"{LSP_DIR}/manager.py", "class LSPManager:", "LSPManager"),
    Task("symbols:manager.py", "documentSymbol", f"{LSP_DIR}/manager.py"),
    Task("symbols:client.py", "documentSymbol", f"{LSP_DIR}/client.py"),
    Task(
        "ws:LSPManager", "workspaceSymbol", f"{LSP_DIR}/manager.py", extra={"query": "LSPManager"}
    ),
    Task(
        "callers:prepare_file",
        "incomingCalls",
        f"{LSP_DIR}/manager.py",
        "async def prepare_file(",
        "prepare_file",
        {"depth": 2},
    ),
    Task(
        "callees:handle_lsp",
        "outgoingCalls",
        f"{LSP_DIR}/tool.py",
        "async def handle_lsp(",
        "handle_lsp",
        {"depth": 1},
    ),
    Task("outline:lsp", "outline", LSP_DIR),
]


def _locate(path: Path, anchor: str, symbol: str) -> tuple[int, int]:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        index = line.find(anchor)
        if index >= 0:
            return number, index + anchor.find(symbol) + 1
    raise SystemExit(f"anchor {anchor!r} not found in {path}")


def _estimate_tokens(text: str) -> int:
    return (len(text.encode("utf-8")) + 3) // 4


async def _raw_bytes(manager: LSPManager, task: Task, args: dict[str, Any]) -> int | None:
    """Serialize the protocol result the way the pre-compaction tool did."""
    path = str(REPO / task.file_path)
    line = int(args.get("line", 1)) - 1
    character = int(args.get("character", 1)) - 1
    method = {
        "goToDefinition": manager.definition,
        "findReferences": manager.references,
        "hover": manager.hover,
        "documentSymbol": manager.document_symbol,
        "workspaceSymbol": manager.workspace_symbol,
    }.get(task.operation)
    if method is None:
        return None
    if task.operation == "documentSymbol":
        outcomes = await manager.document_symbol(path)
    elif task.operation == "workspaceSymbol":
        outcomes = await manager.workspace_symbol(path, str(args["query"]))
    else:
        outcomes = await method(path, line, character)  # type: ignore[call-arg]
    items = [item for outcome in outcomes for item in outcome.items]
    return len(json.dumps(items, indent=2).encode("utf-8"))


async def run() -> dict[str, Any]:
    manager = LSPManager(enabled=True, auto_install=False)
    context = ToolExecutionContext(
        executor_handle=ExecutorHandle(executor_id="bench", executor_type="in_process"),
        runtime_metadata={"lsp_manager": manager, "working_directory": str(REPO)},
        execution_scope_id="bench",
    )
    rows: list[dict[str, Any]] = []
    try:
        for task in TASKS:
            args: dict[str, Any] = {
                "operation": task.operation,
                "file_path": str(REPO / task.file_path),
                **task.extra,
            }
            if task.anchor and task.symbol:
                line, character = _locate(REPO / task.file_path, task.anchor, task.symbol)
                args.update(line=line, character=character)

            start = time.perf_counter()
            first = await handle_lsp(args, context)
            cold_ms = int((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            second = await handle_lsp(args, context)
            warm_ms = int((time.perf_counter() - start) * 1000)

            meta = second.metadata or {}
            compact = second.output
            raw = await _raw_bytes(manager, task, args)
            rows.append(
                {
                    "task": task.name,
                    "operation": task.operation,
                    "status": meta.get("status"),
                    "result_count": meta.get("result_count"),
                    "truncated": meta.get("truncated"),
                    "compact_bytes": len(compact.encode("utf-8")),
                    "compact_tokens": _estimate_tokens(compact),
                    "raw_json_bytes": raw,
                    "raw_json_tokens": _estimate_tokens(" " * raw) if raw is not None else None,
                    "cold_ms": cold_ms,
                    "warm_ms": warm_ms,
                    "first_status": (first.metadata or {}).get("status"),
                }
            )
    finally:
        await manager.cleanup()
    return {"repo": str(REPO), "rows": rows}


def _print(report: dict[str, Any]) -> None:
    header = f"{'task':22} {'status':8} {'n':>4} {'compact':>8} {'raw':>8} {'ratio':>6} {'cold':>7} {'warm':>6}"
    print(header)
    print("-" * len(header))
    total_compact = 0
    total_raw = 0
    for row in report["rows"]:
        raw = row["raw_json_bytes"]
        ratio = f"{raw / row['compact_bytes']:.1f}x" if raw and row["compact_bytes"] else "-"
        total_compact += row["compact_bytes"]
        total_raw += raw or 0
        print(
            f"{row['task']:22} {str(row['status']):8} {str(row['result_count']):>4} "
            f"{row['compact_bytes']:>8} {str(raw if raw is not None else '-'):>8} {ratio:>6} "
            f"{row['cold_ms']:>5}ms {row['warm_ms']:>4}ms"
        )
    if total_raw:
        print(
            f"\ncompactable operations: {total_raw} raw bytes -> {total_compact} compact bytes "
            f"({total_raw / max(total_compact, 1):.1f}x smaller, "
            f"~{_estimate_tokens(' ' * total_raw) - _estimate_tokens(' ' * total_compact)} tokens saved)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write the report as JSON to this path")
    options = parser.parse_args()
    report = asyncio.run(run())
    _print(report)
    if options.json:
        options.json.write_text(json.dumps(report, indent=2))
        print(f"\nwrote {options.json}")
    sys.exit(0)


if __name__ == "__main__":
    main()
