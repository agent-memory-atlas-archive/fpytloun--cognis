"""Unit tests for the executor ``lsp`` tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from cognis.models.tool import ExecutorHandle
from cognis.tools.executor.lsp.manager import PreparedClient
from cognis.tools.executor.lsp.query import QueryOutcome, QueryStatus
from cognis.tools.executor.lsp.tool import handle_lsp
from cognis.tools.executor.lsp.types import (
    Diagnostic,
    DiagnosticFreshness,
    DiagnosticSeverity,
    DiagnosticSnapshot,
    DiagnosticWaitResult,
    Position,
    Range,
)
from cognis.tools.registry import ToolExecutionContext


def _context(runtime_metadata: dict[str, Any] | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(
        executor_handle=ExecutorHandle(executor_id="test", executor_type="in_process"),
        runtime_metadata=runtime_metadata or {},
        execution_scope_id="scope-1",
    )


def _loc(path: str, line: int, col: int) -> dict[str, Any]:
    return {
        "uri": f"file://{path}",
        "range": {
            "start": {"line": line, "character": col},
            "end": {"line": line, "character": col + 1},
        },
    }


class _FakeLsp:
    """Manager double returning canned outcomes per operation."""

    def __init__(self, outcomes: dict[str, list[QueryOutcome]], *, clients: bool = True) -> None:
        self._outcomes = outcomes
        self._clients = clients
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.prepared: list[PreparedClient] = []

    async def prepare_file(self, *_: Any, **__: Any) -> list[PreparedClient]:
        return self.prepared

    async def has_clients(self, *_: Any, **__: Any) -> bool:
        return self._clients

    def __getattr__(self, name: str) -> Any:
        if name not in self._outcomes:
            raise AttributeError(name)

        async def method(*args: Any) -> list[QueryOutcome]:
            self.calls.append((name, args))
            return self._outcomes[name]

        return method


@pytest.fixture()
def workspace(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "pkg" / "sample.py"
    target.parent.mkdir()
    target.write_text("def value():\n    return 1\n\nprint(value())\n")
    return tmp_path, target


class TestValidation:
    @pytest.mark.asyncio()
    async def test_unknown_operation(self, workspace: tuple[Path, Path]) -> None:
        _, target = workspace
        result = await handle_lsp(
            {"operation": "explode", "file_path": str(target)},
            _context({"lsp_manager": _FakeLsp({})}),
        )
        assert result.is_error
        assert "Unsupported LSP operation" in result.output
        assert "goToDefinition" in result.output

    @pytest.mark.asyncio()
    async def test_position_required(self, workspace: tuple[Path, Path]) -> None:
        _, target = workspace
        result = await handle_lsp(
            {"operation": "goToDefinition", "file_path": str(target)},
            _context({"lsp_manager": _FakeLsp({})}),
        )
        assert result.is_error
        assert "requires both line and character" in result.output

    @pytest.mark.asyncio()
    async def test_position_must_be_one_based(self, workspace: tuple[Path, Path]) -> None:
        _, target = workspace
        result = await handle_lsp(
            {"operation": "hover", "file_path": str(target), "line": 0, "character": 1},
            _context({"lsp_manager": _FakeLsp({})}),
        )
        assert result.is_error
        assert "1-based" in result.output

    @pytest.mark.asyncio()
    async def test_workspace_symbol_requires_query(self, workspace: tuple[Path, Path]) -> None:
        _, target = workspace
        result = await handle_lsp(
            {"operation": "workspaceSymbol", "file_path": str(target), "query": " "},
            _context({"lsp_manager": _FakeLsp({})}),
        )
        assert result.is_error
        assert "requires a non-empty query" in result.output

    @pytest.mark.asyncio()
    async def test_missing_manager(self, workspace: tuple[Path, Path]) -> None:
        _, target = workspace
        result = await handle_lsp(
            {"operation": "documentSymbol", "file_path": str(target)}, _context({})
        )
        assert result.is_error
        assert "not available" in result.output

    @pytest.mark.asyncio()
    async def test_missing_file(self, tmp_path: Path) -> None:
        result = await handle_lsp(
            {"operation": "documentSymbol", "file_path": str(tmp_path / "nope.py")},
            _context({"lsp_manager": _FakeLsp({})}),
        )
        assert result.is_error
        assert "does not exist" in result.output

    @pytest.mark.asyncio()
    async def test_no_server_for_extension(self, workspace: tuple[Path, Path]) -> None:
        _, target = workspace
        result = await handle_lsp(
            {"operation": "documentSymbol", "file_path": str(target)},
            _context({"lsp_manager": _FakeLsp({}, clients=False)}),
        )
        assert result.is_error
        assert "No LSP server available for .py files" in result.output
        assert result.metadata is not None
        assert result.metadata["status"] == "unsupported"


class TestOutput:
    @pytest.mark.asyncio()
    async def test_definition_compact_output(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        outcomes = [
            QueryOutcome(
                server_id="pyright",
                status=QueryStatus.OK,
                items=[_loc(str(target), 0, 4), _loc(str(target), 0, 4)],
                duration_ms=12,
            ),
            QueryOutcome(
                server_id="ruff", status=QueryStatus.UNSUPPORTED, message="method not negotiated"
            ),
        ]
        lsp = _FakeLsp({"definition": outcomes})
        result = await handle_lsp(
            {
                "operation": "goToDefinition",
                "file_path": "pkg/sample.py",
                "line": 4,
                "character": 7,
            },
            _context({"lsp_manager": lsp, "working_directory": str(root)}),
        )

        assert not result.is_error
        assert result.output.splitlines() == [
            "goToDefinition pkg/sample.py:4:7: 1 result",
            "pkg/sample.py",
            "  1:5",
            "servers: ruff: unsupported (method not negotiated)",
        ]
        assert "file://" not in result.output
        assert lsp.calls == [("definition", (str(target), 3, 6))]
        metadata = result.metadata
        assert metadata is not None
        assert metadata["operation"] == "goToDefinition"
        assert metadata["status"] == "ok"
        assert metadata["result_count"] == 1
        assert metadata["truncated"] is False
        assert metadata["output_bytes"] == len(result.output.encode())
        assert metadata["servers"] == [
            {"server_id": "pyright", "status": "ok", "duration_ms": 12},
            {"server_id": "ruff", "status": "unsupported", "duration_ms": 0},
        ]
        assert metadata["result"] == [
            {"path": "pkg/sample.py", "line": 1, "column": 5, "end_line": 1, "end_column": 6}
        ]

    @pytest.mark.asyncio()
    async def test_references_include_source_lines_and_limit(
        self, workspace: tuple[Path, Path]
    ) -> None:
        root, target = workspace
        outcomes = [
            QueryOutcome(
                server_id="pyright",
                status=QueryStatus.OK,
                items=[_loc(str(target), 3, 6), _loc(str(target), 0, 4)],
            )
        ]
        result = await handle_lsp(
            {
                "operation": "findReferences",
                "file_path": str(target),
                "line": 1,
                "character": 5,
                "limit": 1,
            },
            _context(
                {"lsp_manager": _FakeLsp({"references": outcomes}), "working_directory": str(root)}
            ),
        )
        assert result.output.splitlines() == [
            "findReferences pkg/sample.py:1:5: 2 results (showing 1)",
            "pkg/sample.py",
            "  1:5  def value():",
            "... 1 more (raise limit to see them)",
        ]
        assert result.metadata is not None
        assert result.metadata["truncated"] is True
        assert result.metadata["shown"] == 1

    @pytest.mark.asyncio()
    async def test_references_never_read_outside_workspace(
        self, workspace: tuple[Path, Path], tmp_path: Path
    ) -> None:
        """Server-supplied locations must not turn into reads of arbitrary files."""
        root, target = workspace
        secret = tmp_path.parent / f"{tmp_path.name}-outside" / "secret.txt"
        secret.parent.mkdir()
        secret.write_text("TOP-SECRET-LINE\n")
        link = root / "pkg" / "link.txt"
        link.symlink_to(secret)
        outcomes = [
            QueryOutcome(
                server_id="pyright",
                status=QueryStatus.OK,
                items=[
                    _loc(str(secret), 0, 0),
                    _loc(str(link), 0, 0),
                    {"uri": "https://example.com/x", "range": _loc("/x", 0, 0)["range"]},
                    _loc(str(target), 0, 4),
                ],
            )
        ]
        result = await handle_lsp(
            {"operation": "findReferences", "file_path": str(target), "line": 1, "character": 5},
            _context(
                {"lsp_manager": _FakeLsp({"references": outcomes}), "working_directory": str(root)}
            ),
        )
        assert "TOP-SECRET" not in result.output
        assert "example.com" not in result.output
        assert "  1:5  def value():" in result.output
        assert result.metadata is not None
        assert result.metadata["result_count"] == 3  # https location dropped, paths kept

    @pytest.mark.asyncio()
    async def test_empty_result_has_hint(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        outcomes = [QueryOutcome(server_id="pyright", status=QueryStatus.EMPTY)]
        result = await handle_lsp(
            {
                "operation": "goToImplementation",
                "file_path": str(target),
                "line": 1,
                "character": 5,
            },
            _context(
                {
                    "lsp_manager": _FakeLsp({"implementation": outcomes}),
                    "working_directory": str(root),
                }
            ),
        )
        assert not result.is_error
        assert result.output.startswith("goToImplementation pkg/sample.py:1:5: 0 results")
        assert "No results" in result.output

    @pytest.mark.asyncio()
    async def test_all_unsupported_is_not_an_error(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        outcomes = [
            QueryOutcome(
                server_id="ruff", status=QueryStatus.UNSUPPORTED, message="method not negotiated"
            )
        ]
        result = await handle_lsp(
            {"operation": "typeDefinition", "file_path": str(target), "line": 1, "character": 5},
            _context(
                {
                    "lsp_manager": _FakeLsp({"type_definition": outcomes}),
                    "working_directory": str(root),
                }
            ),
        )
        assert not result.is_error
        assert "typeDefinition pkg/sample.py:1:5: unsupported" in result.output
        assert "Use grep as a fallback" in result.output
        assert result.metadata is not None
        assert result.metadata["status"] == "unsupported"

    @pytest.mark.asyncio()
    async def test_timeout_without_results_is_error(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        outcomes = [
            QueryOutcome(
                server_id="pyright", status=QueryStatus.TIMEOUT, message="no response within 8s"
            )
        ]
        result = await handle_lsp(
            {"operation": "hover", "file_path": str(target), "line": 1, "character": 5},
            _context(
                {"lsp_manager": _FakeLsp({"hover": outcomes}), "working_directory": str(root)}
            ),
        )
        assert result.is_error
        assert "hover pkg/sample.py:1:5: timeout" in result.output
        assert "pyright: timeout (no response within 8s)" in result.output

    @pytest.mark.asyncio()
    async def test_partial_results_keep_data(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        outcomes = [
            QueryOutcome(server_id="a", status=QueryStatus.OK, items=[_loc(str(target), 0, 0)]),
            QueryOutcome(server_id="b", status=QueryStatus.FAILED, message="server exited"),
        ]
        result = await handle_lsp(
            {"operation": "goToDefinition", "file_path": str(target), "line": 1, "character": 1},
            _context(
                {"lsp_manager": _FakeLsp({"definition": outcomes}), "working_directory": str(root)}
            ),
        )
        assert not result.is_error
        assert "1 result, partial" in result.output
        assert "b: failed (server exited)" in result.output
        assert result.metadata is not None
        assert result.metadata["status"] == "partial"

    @pytest.mark.asyncio()
    async def test_hover_text(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        outcomes = [
            QueryOutcome(
                server_id="pyright",
                status=QueryStatus.OK,
                items=[
                    {
                        "contents": {
                            "kind": "markdown",
                            "value": "```python\n(function) def value() -> int\n```",
                        }
                    }
                ],
            )
        ]
        result = await handle_lsp(
            {"operation": "hover", "file_path": str(target), "line": 1, "character": 5},
            _context(
                {"lsp_manager": _FakeLsp({"hover": outcomes}), "working_directory": str(root)}
            ),
        )
        assert result.output.splitlines()[0] == "hover pkg/sample.py:1:5: 1 result"
        assert "(function) def value() -> int" in result.output

    @pytest.mark.asyncio()
    async def test_document_symbol_outline(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        outcomes = [
            QueryOutcome(
                server_id="pyright",
                status=QueryStatus.OK,
                items=[
                    {
                        "name": "value",
                        "kind": 12,
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 1, "character": 12},
                        },
                    }
                ],
            )
        ]
        lsp = _FakeLsp({"document_symbol": outcomes})
        result = await handle_lsp(
            {"operation": "documentSymbol", "file_path": str(target)},
            _context({"lsp_manager": lsp, "working_directory": str(root)}),
        )
        assert result.output.splitlines() == [
            "documentSymbol pkg/sample.py: 1 result",
            "function value (L1-2)",
        ]
        assert lsp.calls == [("document_symbol", (str(target),))]

    @pytest.mark.asyncio()
    async def test_workspace_symbol_listing(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        outcomes = [
            QueryOutcome(
                server_id="pyright",
                status=QueryStatus.OK,
                items=[{"name": "value", "kind": 12, "location": _loc(str(target), 0, 4)}],
            )
        ]
        lsp = _FakeLsp({"workspace_symbol": outcomes})
        result = await handle_lsp(
            {"operation": "workspaceSymbol", "file_path": str(target), "query": "val"},
            _context({"lsp_manager": lsp, "working_directory": str(root)}),
        )
        assert result.output.splitlines() == [
            "workspaceSymbol 'val': 1 result",
            "function value  pkg/sample.py:1",
        ]
        assert lsp.calls == [("workspace_symbol", (str(target), "val"))]


class TestCapabilitiesOperation:
    @pytest.mark.asyncio()
    async def test_reports_supported_operations_per_server(
        self, workspace: tuple[Path, Path]
    ) -> None:
        root, target = workspace
        client = MagicMock()
        client.server_id = "pyright"
        client.supported_methods.return_value = {
            "textDocument/definition": True,
            "textDocument/references": True,
            "textDocument/hover": False,
            "workspace/symbol": True,
        }
        lsp = _FakeLsp({})
        lsp.prepared = [
            PreparedClient(
                client=client,
                client_key="pyright:/w",
                uri="file:///x",
                language_id="python",
                version=0,
            )
        ]
        result = await handle_lsp(
            {"operation": "capabilities", "file_path": str(target)},
            _context({"lsp_manager": lsp, "working_directory": str(root)}),
        )
        assert result.output.splitlines() == [
            "capabilities pkg/sample.py:",
            "pyright: findReferences, goToDefinition, workspaceSymbol",
            (
                "  unsupported: documentSymbol, goToImplementation, hover, incomingCalls, "
                "outgoingCalls, outline, typeDefinition"
            ),
        ]
        client.supported_methods.assert_called_once_with(uri="file:///x", language_id="python")
        assert result.metadata is not None
        assert result.metadata["status"] == "ok"

    @pytest.mark.asyncio()
    async def test_no_prepared_clients(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        result = await handle_lsp(
            {"operation": "capabilities", "file_path": str(target)},
            _context({"lsp_manager": _FakeLsp({}), "working_directory": str(root)}),
        )
        assert "no language server could be started" in result.output
        assert result.metadata is not None
        assert result.metadata["status"] == "unsupported"


class TestDiagnosticsOperation:
    @pytest.mark.asyncio()
    async def test_reports_fresh_diagnostics(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        uri = f"file://{target}"
        diag = Diagnostic(
            range=Range(start=Position(line=1, character=4), end=Position(line=1, character=5)),
            severity=DiagnosticSeverity.ERROR,
            code="E1",
            source="pyright",
            message="bad",
        )
        snapshot = DiagnosticSnapshot(
            server_id="pyright",
            uri=uri,
            document_version=0,
            diagnostic_version=0,
            received_sequence=1,
            received_at_monotonic=0.0,
            diagnostics=[diag],
            freshness=DiagnosticFreshness.FRESH,
        )
        collection = MagicMock()
        collection.waits = [
            DiagnosticWaitResult(
                server_id="pyright",
                uri=uri,
                target_version=0,
                status=DiagnosticFreshness.FRESH,
                duration_ms=5,
                snapshot=snapshot,
            ),
            DiagnosticWaitResult(
                server_id="ruff",
                uri=uri,
                target_version=0,
                status=DiagnosticFreshness.TIMEOUT,
                duration_ms=10_000,
            ),
        ]
        collection.snapshots_by_path = {str(target): [snapshot]}

        lsp = _FakeLsp({})
        touch_calls: list[dict[str, Any]] = []

        async def touch_file(path: str, **kwargs: Any) -> MagicMock:
            touch_calls.append({"path": path, **kwargs})
            return collection

        lsp.touch_file = touch_file  # type: ignore[attr-defined]
        result = await handle_lsp(
            {"operation": "diagnostics", "file_path": str(target)},
            _context({"lsp_manager": lsp, "working_directory": str(root)}),
        )
        assert touch_calls == [{"path": str(target), "wait": True, "purpose": "semantic"}]
        lines = result.output.splitlines()
        assert lines[0] == "diagnostics pkg/sample.py: 1 error(s), 0 warning(s)"
        assert "pkg/sample.py:2:5 error: bad (E1)" in result.output
        assert lines[-1] == "servers: ruff: timeout"
        assert not result.is_error
        assert result.metadata is not None
        assert result.metadata["status"] == "partial"
        assert result.metadata["result"] == {"errors": 1, "warnings": 0}

    @pytest.mark.asyncio()
    async def test_clean_file(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        collection = MagicMock()
        collection.waits = [
            DiagnosticWaitResult(
                server_id="ruff",
                uri=f"file://{target}",
                target_version=0,
                status=DiagnosticFreshness.FRESH_UNVERSIONED,
                duration_ms=5,
            )
        ]
        collection.snapshots_by_path = {}
        lsp = _FakeLsp({})

        async def touch_file(*_: Any, **__: Any) -> MagicMock:
            return collection

        lsp.touch_file = touch_file  # type: ignore[attr-defined]
        result = await handle_lsp(
            {"operation": "diagnostics", "file_path": str(target)},
            _context({"lsp_manager": lsp, "working_directory": str(root)}),
        )
        assert result.output.splitlines() == [
            "diagnostics pkg/sample.py: 0 error(s), 0 warning(s)",
            "no errors or warnings",
        ]
        assert result.metadata is not None
        assert result.metadata["status"] == "empty"
