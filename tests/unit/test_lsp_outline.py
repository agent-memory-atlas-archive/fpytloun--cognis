"""Unit tests for the bounded directory outline operation."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from cognis.models.tool import ExecutorHandle
from cognis.tools.executor.lsp.manager import SYMBOL_CACHE_MAX_ENTRIES, LSPManager
from cognis.tools.executor.lsp.outline import (
    OutlineLimits,
    enumerate_source_files,
    outline_directory,
    render_outline,
)
from cognis.tools.executor.lsp.query import QueryOutcome, QueryStatus
from cognis.tools.executor.lsp.tool import handle_lsp
from cognis.tools.registry import ToolExecutionContext


def _symbol(
    name: str, line: int, kind: int = 12, children: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": name,
        "kind": kind,
        "detail": f"def {name}()" if kind == 12 else "",
        "range": {
            "start": {"line": line, "character": 0},
            "end": {"line": line + 3, "character": 0},
        },
        "selectionRange": {
            "start": {"line": line, "character": 4},
            "end": {"line": line, "character": 8},
        },
    }
    if children:
        data["children"] = children
    return data


def _ok(items: list[dict[str, Any]], server_id: str = "pyright") -> list[QueryOutcome]:
    return [
        QueryOutcome(
            server_id=server_id,
            status=QueryStatus.OK if items else QueryStatus.EMPTY,
            items=items,
            duration_ms=1,
        )
    ]


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "node_modules").mkdir()
    (pkg / ".hidden").mkdir()
    (pkg / "b.py").write_text("def b():\n    pass\n")
    (pkg / "a.py").write_text("class A:\n    def m(self):\n        pass\n")
    (pkg / "sub" / "c.py").write_text("def c():\n    pass\n")
    (pkg / "sub" / "notes.md").write_text("# notes\n")
    (pkg / "data.csv").write_text("1,2\n")
    (pkg / "node_modules" / "x.py").write_text("x = 1\n")
    (pkg / ".hidden" / "y.py").write_text("y = 1\n")
    (pkg / ".env").write_text("SECRET=1\n")
    return pkg


class TestEnumeration:
    def test_deterministic_order_and_ignores(self, tree: Path) -> None:
        result = enumerate_source_files(str(tree), max_files=25)
        assert [os.path.relpath(p, tree) for p in result.files] == ["a.py", "b.py", "sub/c.py"]
        assert result.supported_total == 3
        assert dict(result.unsupported_by_extension) == {".csv": 1, ".md": 1}
        assert result.walk_truncated is False

    def test_cap_counts_beyond_limit(self, tree: Path) -> None:
        result = enumerate_source_files(str(tree), max_files=2)
        assert [os.path.basename(p) for p in result.files] == ["a.py", "b.py"]
        assert result.supported_total == 3

    def test_limits_from_arguments(self) -> None:
        assert OutlineLimits.from_arguments(None).max_files == 25
        assert OutlineLimits.from_arguments(0).max_files == 1
        assert OutlineLimits.from_arguments(500).max_files == 100
        assert OutlineLimits.from_arguments(True).max_files == 25


class TestOutlineDirectory:
    @pytest.mark.asyncio()
    async def test_gathers_in_order_and_renders_budgeted(self, tree: Path) -> None:
        answers = {
            "a.py": _ok(
                [
                    _symbol(
                        "A",
                        0,
                        kind=5,
                        children=[
                            _symbol("attr", 1, kind=13),
                            _symbol("m", 1, kind=6),
                            _symbol("CONST", 2, kind=14),
                        ],
                    ),
                    _symbol("TOP", 9, kind=14),
                ]
            ),
            "b.py": _ok([_symbol("b", 0)]),
            "c.py": _ok([]),
        }
        seen: list[str] = []

        async def fetch(path: str) -> tuple[list[QueryOutcome], bool]:
            seen.append(os.path.basename(path))
            return answers[os.path.basename(path)], os.path.basename(path) == "b.py"

        result = await outline_directory(
            str(tree), fetch_symbols=fetch, limits=OutlineLimits(), cwd=str(tree.parent)
        )
        assert seen == ["a.py", "b.py", "c.py"]
        assert result.status is QueryStatus.OK
        assert [f.path for f in result.files] == ["pkg/a.py", "pkg/b.py", "pkg/sub/c.py"]
        assert [f.cached for f in result.files] == [False, True, False]

        rendering = render_outline(result, limits=OutlineLimits())
        assert rendering.text.splitlines() == [
            "pkg/a.py: 3 symbols",
            "  class A (L1-4)",
            "    method m (L2-5)",
            "  constant TOP (L10-13)",
            "pkg/b.py: 1 symbol",
            "  function b (L1-4)  def b()",
            "pkg/sub/c.py: 0 symbols",
            "skipped 2 file(s) without a server: .csv (1), .md (1)",
        ]
        assert rendering.truncated is False
        assert rendering.files_shown == 3
        assert rendering.symbols_shown == 4
        # Nested data members are attributes, not structure; top-level constants stay.
        assert "attr" not in rendering.text
        assert "CONST" not in rendering.text

    @pytest.mark.asyncio()
    async def test_byte_budget_stops_after_first_file(self, tree: Path) -> None:
        async def fetch(path: str) -> tuple[list[QueryOutcome], bool]:
            return _ok([_symbol(f"f{i}", i) for i in range(20)]), False

        limits = OutlineLimits(max_bytes=200)
        result = await outline_directory(
            str(tree), fetch_symbols=fetch, limits=limits, cwd=str(tree)
        )
        rendering = render_outline(result, limits=limits)
        assert rendering.files_shown == 1
        assert rendering.truncated is True
        assert rendering.truncated_reason == "bytes"
        assert "... 2 more file(s) not shown (output budget)" in rendering.text

    @pytest.mark.asyncio()
    async def test_symbols_per_file_and_depth_limits(self, tree: Path) -> None:
        deep = _symbol(
            "A", 0, kind=5, children=[_symbol("m", 1, kind=6, children=[_symbol("inner", 2)])]
        )
        many = [deep] + [_symbol(f"f{i}", i + 10) for i in range(5)]

        async def fetch(path: str) -> tuple[list[QueryOutcome], bool]:
            return _ok(many), False

        limits = OutlineLimits(max_files=1, max_symbols_per_file=3, max_depth=2)
        result = await outline_directory(
            str(tree), fetch_symbols=fetch, limits=limits, cwd=str(tree)
        )
        rendering = render_outline(result, limits=limits)
        lines = rendering.text.splitlines()
        assert lines[0] == "a.py: 8 symbols"
        assert lines[1:4] == [
            "  class A (L1-4)",
            "    method m (L2-5)",
            "  function f0 (L11-14)  def f0()",
        ]
        assert lines[4] == "  ... 5 more symbol(s)"
        assert "... 2 more supported file(s) beyond limit=1" in rendering.text
        assert rendering.truncated_reason == "files"

    @pytest.mark.asyncio()
    async def test_time_budget_marks_partial(self, tree: Path) -> None:
        async def fetch(path: str) -> tuple[list[QueryOutcome], bool]:
            await asyncio.sleep(0.15)
            return _ok([_symbol("x", 0)]), False

        limits = OutlineLimits(time_budget_s=0.2)
        result = await outline_directory(
            str(tree), fetch_symbols=fetch, limits=limits, cwd=str(tree)
        )
        assert result.status is QueryStatus.PARTIAL
        assert result.stop_reason == "time"
        assert result.files_not_queried >= 1
        rendering = render_outline(result, limits=limits)
        assert "not queried (time budget)" in rendering.text
        assert rendering.truncated is True

    @pytest.mark.asyncio()
    async def test_slow_fetch_is_cut_at_the_deadline(self, tree: Path) -> None:
        """One hung server cannot run past the outline budget."""
        started = asyncio.get_running_loop().time()

        async def fetch(path: str) -> tuple[list[QueryOutcome], bool]:
            await asyncio.sleep(5)
            return _ok([_symbol("x", 0)]), False

        limits = OutlineLimits(time_budget_s=0.1)
        result = await outline_directory(
            str(tree), fetch_symbols=fetch, limits=limits, cwd=str(tree)
        )
        assert asyncio.get_running_loop().time() - started < 1
        assert result.stop_reason == "time"
        assert result.files == []
        assert result.status is QueryStatus.TIMEOUT

    @pytest.mark.asyncio()
    async def test_unsupported_and_failed_files_are_labeled(self, tree: Path) -> None:
        async def fetch(path: str) -> tuple[list[QueryOutcome], bool]:
            name = os.path.basename(path)
            if name == "a.py":
                return [QueryOutcome(server_id="ruff", status=QueryStatus.UNSUPPORTED)], False
            if name == "b.py":
                return [QueryOutcome(server_id="pyright", status=QueryStatus.TIMEOUT)], False
            return _ok([_symbol("c", 0)]), False

        result = await outline_directory(
            str(tree), fetch_symbols=fetch, limits=OutlineLimits(), cwd=str(tree)
        )
        assert result.status is QueryStatus.PARTIAL
        text = render_outline(result, limits=OutlineLimits()).text
        assert "a.py: unsupported (no server negotiated documentSymbol)" in text
        assert "b.py: timeout" in text
        assert "sub/c.py: 1 symbol" in text

    @pytest.mark.asyncio()
    async def test_empty_directory(self, tmp_path: Path) -> None:
        (tmp_path / "README").write_text("x")
        result = await outline_directory(
            str(tmp_path), fetch_symbols=AsyncMock(), limits=OutlineLimits(), cwd=str(tmp_path)
        )
        assert result.status is QueryStatus.EMPTY
        assert result.files == []


class TestSymbolCache:
    @pytest.mark.asyncio()
    async def test_cache_hit_until_file_changes(self, tmp_path: Path) -> None:
        target = tmp_path / "m.py"
        target.write_text("a = 1\n")
        manager = LSPManager(enabled=True)
        manager.document_symbol = AsyncMock(return_value=_ok([_symbol("a", 0)]))  # type: ignore[method-assign]

        first, cached_first = await manager.document_symbol_cached(str(target))
        second, cached_second = await manager.document_symbol_cached(str(target))
        assert cached_first is False
        assert cached_second is True
        assert second is first
        assert manager.document_symbol.await_count == 1

        target.write_text("a = 1\nb = 2\n")
        _, cached_third = await manager.document_symbol_cached(str(target))
        assert cached_third is False
        assert manager.document_symbol.await_count == 2

    @pytest.mark.asyncio()
    async def test_edit_sync_evicts_cache(self, tmp_path: Path) -> None:
        target = tmp_path / "m.py"
        target.write_text("a = 1\n")
        manager = LSPManager(enabled=True)
        manager.document_symbol = AsyncMock(return_value=_ok([_symbol("a", 0)]))  # type: ignore[method-assign]
        await manager.document_symbol_cached(str(target))
        assert str(target) in manager._symbol_cache

        # Diagnostics-purpose sync (an edit) evicts even when the on-disk key is unchanged.
        await manager.touch_file(str(target), wait=False, purpose="diagnostics")
        assert str(target) not in manager._symbol_cache

    @pytest.mark.asyncio()
    async def test_unsuccessful_answers_are_not_cached(self, tmp_path: Path) -> None:
        target = tmp_path / "m.py"
        target.write_text("a = 1\n")
        manager = LSPManager(enabled=True)
        manager.document_symbol = AsyncMock(  # type: ignore[method-assign]
            return_value=[QueryOutcome(server_id="pyright", status=QueryStatus.TIMEOUT)]
        )
        await manager.document_symbol_cached(str(target))
        await manager.document_symbol_cached(str(target))
        assert manager.document_symbol.await_count == 2
        assert manager._symbol_cache == {}

    @pytest.mark.asyncio()
    async def test_cache_is_bounded(self, tmp_path: Path) -> None:
        manager = LSPManager(enabled=True)
        manager.document_symbol = AsyncMock(return_value=_ok([_symbol("a", 0)]))  # type: ignore[method-assign]
        for i in range(SYMBOL_CACHE_MAX_ENTRIES + 5):
            path = tmp_path / f"f{i}.py"
            path.write_text("a = 1\n")
            await manager.document_symbol_cached(str(path))
        assert len(manager._symbol_cache) == SYMBOL_CACHE_MAX_ENTRIES
        assert str(tmp_path / "f0.py") not in manager._symbol_cache

    @pytest.mark.asyncio()
    async def test_missing_file_bypasses_cache(self, tmp_path: Path) -> None:
        manager = LSPManager(enabled=True)
        manager.document_symbol = AsyncMock(return_value=[])  # type: ignore[method-assign]
        outcomes, cached = await manager.document_symbol_cached(str(tmp_path / "missing.py"))
        assert outcomes == []
        assert cached is False


class _OutlineLsp:
    def __init__(self, answers: dict[str, list[QueryOutcome]]) -> None:
        self.answers = answers

    async def prepare_file(self, *_: Any, **__: Any) -> list[Any]:
        return []

    async def has_clients(self, *_: Any, **__: Any) -> bool:
        return True

    async def document_symbol_cached(self, path: str) -> tuple[list[QueryOutcome], bool]:
        return self.answers.get(os.path.basename(path), _ok([])), False

    async def document_symbol(self, path: str) -> list[QueryOutcome]:
        return self.answers.get(os.path.basename(path), _ok([]))


def _context(lsp: Any, root: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        executor_handle=ExecutorHandle(executor_id="test", executor_type="in_process"),
        runtime_metadata={"lsp_manager": lsp, "working_directory": str(root)},
        execution_scope_id="scope-1",
    )


class TestToolOperation:
    @pytest.mark.asyncio()
    async def test_directory_outline(self, tree: Path) -> None:
        lsp = _OutlineLsp({"a.py": _ok([_symbol("A", 0, kind=5)]), "b.py": _ok([_symbol("b", 0)])})
        result = await handle_lsp(
            {"operation": "outline", "file_path": "pkg", "limit": 2}, _context(lsp, tree.parent)
        )
        assert result.is_error is False
        lines = result.output.splitlines()
        assert lines[0] == "outline pkg/: 2 of 3 files, 2 symbols"
        assert lines[1] == "pkg/a.py: 1 symbol"
        assert "... 1 more supported file(s) beyond limit=2" in result.output
        assert "file://" not in result.output
        meta = result.metadata
        assert meta is not None
        assert meta["operation"] == "outline"
        assert meta["status"] == "ok"
        assert meta["files_shown"] == 2
        assert meta["files_supported"] == 3
        assert meta["files_unsupported"] == 2
        assert meta["truncated"] is True
        assert meta["stop_reason"] == "files"
        assert meta["result"][0]["path"] == "pkg/a.py"
        assert meta["result"][0]["symbols"][0]["name"] == "A"

    @pytest.mark.asyncio()
    async def test_file_outline_delegates_to_document_symbol(self, tree: Path) -> None:
        lsp = _OutlineLsp({"a.py": _ok([_symbol("A", 0, kind=5)])})
        result = await handle_lsp(
            {"operation": "outline", "file_path": "pkg/a.py"}, _context(lsp, tree.parent)
        )
        assert result.output.splitlines()[0] == "documentSymbol pkg/a.py: 1 result"
        assert result.metadata is not None
        assert result.metadata["operation"] == "documentSymbol"

    @pytest.mark.asyncio()
    async def test_directory_rejected_for_other_operations(self, tree: Path) -> None:
        result = await handle_lsp(
            {"operation": "documentSymbol", "file_path": "pkg"},
            _context(_OutlineLsp({}), tree.parent),
        )
        assert result.is_error is True
        assert "Not a file" in result.output

    @pytest.mark.asyncio()
    async def test_directory_without_supported_files(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "x.md").write_text("# x\n")
        result = await handle_lsp(
            {"operation": "outline", "file_path": "docs"}, _context(_OutlineLsp({}), tmp_path)
        )
        assert result.is_error is False
        assert result.output.splitlines()[0] == "outline docs/: no supported source files"
        assert "Use glob and read instead" in result.output
        assert result.metadata is not None
        assert result.metadata["status"] == "empty"
