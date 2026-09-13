"""Bounded LSP facts attached to edit results, and the Python type-diagnostics switch."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from cognis.models.tool import ExecutorHandle
from cognis.tools.executor.filesystem import handle_edit, handle_read
from cognis.tools.executor.lsp.manager import LSPManager
from cognis.tools.executor.lsp.runtime import resolve_lsp_runtime_config
from cognis.tools.executor.lsp.servers import get_servers_for_extension
from cognis.tools.executor.lsp.types import (
    Diagnostic,
    DiagnosticCollection,
    DiagnosticFreshness,
    DiagnosticSeverity,
    DiagnosticSnapshot,
    DiagnosticWaitResult,
    Position,
    Range,
)
from cognis.tools.registry import ToolExecutionContext


def _diag(severity: DiagnosticSeverity, line: int) -> Diagnostic:
    return Diagnostic(
        range=Range(start=Position(line=line, character=0), end=Position(line=line, character=1)),
        severity=severity,
        code="X1",
        source="ruff",
        message="problem",
    )


class _EditLsp:
    """Manager double returning a canned collection for the edited file."""

    def __init__(self, waits: list[DiagnosticWaitResult], snapshots: dict[str, list[Any]]) -> None:
        self._collection = DiagnosticCollection(waits=waits, snapshots_by_path=snapshots)

    def has_pending_diagnostics(self, *_: Any) -> bool:
        return False

    async def touch_file(self, *_: Any, wait: bool = True, **__: Any) -> DiagnosticCollection:
        return self._collection if wait else DiagnosticCollection()

    def get_diagnostics(self, *_: Any) -> dict[str, list[Any]]:
        return {}

    def get_diagnostic_snapshots(self, *_: Any) -> dict[str, list[Any]]:
        return {}


def _context(lsp: Any, root: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        executor_handle=ExecutorHandle(executor_id="test", executor_type="in_process"),
        runtime_metadata={"lsp_manager": lsp, "working_directory": str(root)},
        execution_scope_id="scope-1",
    )


async def _edit_with(lsp: Any, tmp_path: Path) -> dict[str, Any]:
    target = tmp_path / "m.py"
    target.write_text("x = 1\n")
    context = _context(lsp, tmp_path)
    await handle_read({"file_path": str(target)}, context)
    result = await handle_edit(
        {"file_path": str(target), "old_string": "x = 1", "new_string": "x = 2"}, context
    )
    assert result.metadata is not None
    return result.metadata["lsp_diagnostics"]


def _wait(
    target: Path, status: DiagnosticFreshness, snapshot: DiagnosticSnapshot | None = None
) -> DiagnosticWaitResult:
    return DiagnosticWaitResult(
        server_id="ruff",
        uri=f"file://{target}",
        target_version=1,
        status=status,
        duration_ms=3,
        snapshot=snapshot,
        error_count=sum(
            1
            for d in (snapshot.diagnostics if snapshot else [])
            if d.severity is DiagnosticSeverity.ERROR
        ),
        warning_count=sum(
            1
            for d in (snapshot.diagnostics if snapshot else [])
            if d.severity is DiagnosticSeverity.WARNING
        ),
    )


def _snapshot(target: Path, diagnostics: list[Diagnostic]) -> DiagnosticSnapshot:
    return DiagnosticSnapshot(
        server_id="ruff",
        uri=f"file://{target}",
        document_version=1,
        diagnostic_version=1,
        received_sequence=1,
        received_at_monotonic=0.0,
        diagnostics=diagnostics,
        freshness=DiagnosticFreshness.FRESH,
    )


class TestEditMetadata:
    @pytest.mark.asyncio()
    async def test_injected(self, tmp_path: Path) -> None:
        target = tmp_path / "m.py"
        snap = _snapshot(
            target, [_diag(DiagnosticSeverity.ERROR, 0), _diag(DiagnosticSeverity.WARNING, 0)]
        )
        lsp = _EditLsp([_wait(target, DiagnosticFreshness.FRESH, snap)], {str(target): [snap]})
        data = await _edit_with(lsp, tmp_path)
        assert data["status"] == "fresh"
        assert data["injection"] == "injected"
        assert data["error_count"] == 1
        assert data["warning_count"] == 1
        assert data["suppressed_unchanged_count"] == 0
        assert data["injected_bytes"] > 0
        assert data["estimated_tokens"] == (data["injected_bytes"] + 3) // 4
        assert data["status_counts"] == {"fresh": 1}

    @pytest.mark.asyncio()
    async def test_clean(self, tmp_path: Path) -> None:
        target = tmp_path / "m.py"
        snap = _snapshot(target, [])
        lsp = _EditLsp([_wait(target, DiagnosticFreshness.FRESH, snap)], {str(target): [snap]})
        data = await _edit_with(lsp, tmp_path)
        assert data["injection"] == "clean"
        assert data["error_count"] == 0
        assert data["injected_bytes"] > 0  # the "LSP: clean" notice

    @pytest.mark.asyncio()
    async def test_timeout_is_none(self, tmp_path: Path) -> None:
        target = tmp_path / "m.py"
        lsp = _EditLsp([_wait(target, DiagnosticFreshness.TIMEOUT)], {})
        data = await _edit_with(lsp, tmp_path)
        assert data["status"] == "timeout"
        assert data["injection"] == "none"
        assert data["status_counts"] == {"timeout": 1}

    @pytest.mark.asyncio()
    async def test_unavailable_when_no_waits(self, tmp_path: Path) -> None:
        data = await _edit_with(_EditLsp([], {}), tmp_path)
        assert data["status"] == "unavailable"
        assert data["injection"] == "none"
        assert data["injected_bytes"] == 0

    @pytest.mark.asyncio()
    async def test_unchanged_warning_is_suppressed(self, tmp_path: Path) -> None:
        target = tmp_path / "m.py"
        warning = _diag(DiagnosticSeverity.WARNING, 0)
        snap = _snapshot(target, [warning])
        lsp = _EditLsp([_wait(target, DiagnosticFreshness.FRESH, snap)], {str(target): [snap]})
        context = _context(lsp, tmp_path)
        target.write_text("x = 1\n")
        await handle_read({"file_path": str(target)}, context)
        first = await handle_edit(
            {"file_path": str(target), "old_string": "x = 1", "new_string": "x = 2"}, context
        )
        second = await handle_edit(
            {"file_path": str(target), "old_string": "x = 2", "new_string": "x = 3"}, context
        )
        assert first.metadata is not None and second.metadata is not None
        assert first.metadata["lsp_diagnostics"]["injection"] == "injected"
        data = second.metadata["lsp_diagnostics"]
        assert data["injection"] == "suppressed_unchanged"
        assert data["suppressed_unchanged_count"] == 1
        assert data["warning_count"] == 1


class TestPythonTypeDiagnosticsSwitch:
    def test_default_is_ruff_only(self) -> None:
        ids = [s.server_id for s in get_servers_for_extension(".py", purpose="diagnostics")]
        assert ids == ["ruff"]

    def test_switch_enables_pyright_for_edit_diagnostics(self) -> None:
        ids = [
            s.server_id
            for s in get_servers_for_extension(
                ".py", purpose="diagnostics", python_type_diagnostics=True
            )
        ]
        assert "pyright" in ids
        assert "ruff" in ids

    def test_semantic_purpose_always_includes_pyright(self) -> None:
        ids = [s.server_id for s in get_servers_for_extension(".py", purpose="semantic")]
        assert "pyright" in ids

    def test_runtime_config_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COGNIS_LSP_PYTHON_TYPE_DIAGNOSTICS", raising=False)
        assert resolve_lsp_runtime_config({}).python_type_diagnostics is False
        assert (
            resolve_lsp_runtime_config(
                {"lsp_python_type_diagnostics": True}
            ).python_type_diagnostics
            is True
        )
        assert (
            resolve_lsp_runtime_config(
                {"lsp_python_type_diagnostics": "yes"}
            ).python_type_diagnostics
            is True
        )
        monkeypatch.setenv("COGNIS_LSP_PYTHON_TYPE_DIAGNOSTICS", "1")
        assert resolve_lsp_runtime_config({}).python_type_diagnostics is True
        assert (
            resolve_lsp_runtime_config(
                {"lsp_python_type_diagnostics": False}
            ).python_type_diagnostics
            is False
        )

    def test_manager_passes_switch_to_server_selection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[dict[str, Any]] = []

        def fake_servers(ext: str, **kwargs: Any) -> list[Any]:
            seen.append({"ext": ext, **kwargs})
            return []

        monkeypatch.setattr(
            "cognis.tools.executor.lsp.manager.get_servers_for_extension", fake_servers
        )
        manager = LSPManager(enabled=True, python_type_diagnostics=True)
        asyncio.run(manager.touch_file("/tmp/x.py", wait=False, purpose="diagnostics"))
        assert seen == [{"ext": ".py", "purpose": "diagnostics", "python_type_diagnostics": True}]
