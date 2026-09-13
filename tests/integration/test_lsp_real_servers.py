"""Real language-server smoke tests for the executor ``lsp`` tool.

These tests spawn pinned language servers (pyright, typescript-language-server,
gopls) when they are on PATH or in the Cognis LSP cache.  They never install
anything.  Each server is skipped independently when unavailable, so the
module is safe in CI and useful locally.

Run with::

    uv run pytest tests/integration/test_lsp_real_servers.py -m lsp_real -v
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from cognis.models.tool import ExecutorHandle
from cognis.tools.executor.lsp.install import get_cache_dir, resolve_command
from cognis.tools.executor.lsp.manager import LSPManager
from cognis.tools.executor.lsp.servers import get_server_by_id
from cognis.tools.executor.lsp.tool import handle_lsp
from cognis.tools.registry import ToolExecutionContext

pytestmark = pytest.mark.lsp_real

# Pyright is skipped by the manager under /tmp, so smoke projects live in a
# non-scratch directory.
_PROJECT_BASE = Path(os.environ.get("COGNIS_LSP_SMOKE_DIR", str(Path.home() / ".cache")))


def _server_available(server_id: str) -> bool:
    definition = get_server_by_id(server_id)
    if definition is None:
        return False
    resolved = asyncio.run(
        resolve_command(
            definition.command,
            server_id,
            definition.install_strategy,
            auto_install=False,
            cache_dir=get_cache_dir(),
        )
    )
    return resolved is not None


def _require(server_id: str) -> None:
    if not _server_available(server_id):
        pytest.skip(f"{server_id} not on PATH or in LSP cache")


@pytest.fixture()
def project() -> Iterator[Path]:
    _PROJECT_BASE.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="cognis-lsp-smoke-", dir=_PROJECT_BASE))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture()
async def manager() -> AsyncIterator[LSPManager]:
    instance = LSPManager(enabled=True, auto_install=False, diagnostics_timeout_ms=20_000)
    try:
        yield instance
    finally:
        await instance.cleanup()


def _context(manager: LSPManager, root: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        executor_handle=ExecutorHandle(executor_id="smoke", executor_type="in_process"),
        runtime_metadata={"lsp_manager": manager, "working_directory": str(root)},
        execution_scope_id="scope-smoke",
    )


async def _call(
    manager: LSPManager, root: Path, operation: str, **params: Any
) -> tuple[str, dict[str, Any]]:
    result = await handle_lsp({"operation": operation, **params}, _context(manager, root))
    assert result.metadata is not None, result.output
    return result.output, result.metadata


def _assert_compact(output: str) -> None:
    assert "file://" not in output
    assert '"uri"' not in output
    assert '"range"' not in output


PY_MAIN = '''\
from helpers import add


def compute(a: int, b: int) -> int:
    """Add two numbers through a helper."""
    return add(a, b)


def entry() -> int:
    return compute(1, 2)


class Runner:
    def run(self) -> int:
        return entry()
'''

PY_HELPERS = """\
def add(x: int, y: int) -> int:
    return x + y
"""


class TestPyright:
    @pytest.fixture(autouse=True)
    def _available(self) -> None:
        _require("pyright")

    @pytest.fixture()
    def py_project(self, project: Path) -> Path:
        (project / "pyproject.toml").write_text('[project]\nname = "smoke"\nversion = "0.0.0"\n')
        (project / "main.py").write_text(PY_MAIN)
        (project / "helpers.py").write_text(PY_HELPERS)
        return project

    async def test_definition_crosses_files(self, manager: LSPManager, py_project: Path) -> None:
        # ``add`` inside ``return add(a, b)`` is on line 6, column 12.
        output, meta = await _call(
            manager,
            py_project,
            "goToDefinition",
            file_path=str(py_project / "main.py"),
            line=6,
            character=12,
        )
        _assert_compact(output)
        assert meta["status"] == "ok", output
        assert "helpers.py" in output
        assert "  1:5" in output

    async def test_references_and_limit(self, manager: LSPManager, py_project: Path) -> None:
        output, meta = await _call(
            manager,
            py_project,
            "findReferences",
            file_path=str(py_project / "main.py"),
            line=4,
            character=5,
        )
        _assert_compact(output)
        assert meta["status"] == "ok", output
        assert meta["result_count"] >= 2  # definition + call in entry()
        limited, limited_meta = await _call(
            manager,
            py_project,
            "findReferences",
            file_path=str(py_project / "main.py"),
            line=4,
            character=5,
            limit=1,
        )
        assert limited_meta["truncated"] is True
        assert "more" in limited

    async def test_hover_is_text(self, manager: LSPManager, py_project: Path) -> None:
        output, meta = await _call(
            manager,
            py_project,
            "hover",
            file_path=str(py_project / "main.py"),
            line=4,
            character=5,
        )
        assert meta["status"] == "ok", output
        assert "compute" in output
        _assert_compact(output)

    async def test_document_symbol_outline(self, manager: LSPManager, py_project: Path) -> None:
        output, meta = await _call(
            manager, py_project, "documentSymbol", file_path=str(py_project / "main.py")
        )
        assert meta["status"] == "ok", output
        assert "class Runner" in output
        assert "  method run" in output
        assert "function compute" in output

    async def test_workspace_symbol(self, manager: LSPManager, py_project: Path) -> None:
        output, meta = await _call(
            manager,
            py_project,
            "workspaceSymbol",
            file_path=str(py_project / "main.py"),
            query="compute",
        )
        assert meta["status"] == "ok", output
        assert "main.py:4" in output

    async def test_incoming_calls(self, manager: LSPManager, py_project: Path) -> None:
        output, meta = await _call(
            manager,
            py_project,
            "incomingCalls",
            file_path=str(py_project / "helpers.py"),
            line=1,
            character=5,
            depth=3,
        )
        _assert_compact(output)
        assert meta["status"] in {"ok", "partial"}, output
        assert "compute" in output
        assert "entry" in output  # depth 2
        assert meta["edge_count"] >= 2

    async def test_outgoing_calls(self, manager: LSPManager, py_project: Path) -> None:
        output, meta = await _call(
            manager,
            py_project,
            "outgoingCalls",
            file_path=str(py_project / "main.py"),
            line=14,
            character=9,
            depth=3,
        )
        assert meta["status"] in {"ok", "partial"}, output
        assert "entry" in output
        assert "compute" in output

    async def test_outline_directory(self, manager: LSPManager, py_project: Path) -> None:
        output, meta = await _call(manager, py_project, "outline", file_path=str(py_project))
        assert meta["status"] in {"ok", "partial"}, output
        assert "main.py" in output
        assert "helpers.py" in output
        assert "function add" in output

    async def test_capabilities_and_diagnostics(
        self, manager: LSPManager, py_project: Path
    ) -> None:
        output, meta = await _call(
            manager, py_project, "capabilities", file_path=str(py_project / "main.py")
        )
        assert meta["status"] == "ok", output
        assert "pyright" in output
        assert "incomingCalls" in output
        (py_project / "main.py").write_text(PY_MAIN + "\nbroken = undefined_name\n")
        await manager.touch_file(str(py_project / "main.py"), wait=True, purpose="semantic")
        output, meta = await _call(
            manager, py_project, "diagnostics", file_path=str(py_project / "main.py")
        )
        assert "undefined_name" in output or meta["result_count"] >= 1, output


TS_MAIN = """\
import { add } from "./helpers";

export function compute(a: number, b: number): number {
  return add(a, b);
}

export function entry(): number {
  return compute(1, 2);
}
"""

TS_HELPERS = """\
export function add(x: number, y: number): number {
  return x + y;
}
"""


class TestTypeScript:
    @pytest.fixture(autouse=True)
    def _available(self) -> None:
        _require("typescript")

    @pytest.fixture()
    def ts_project(self, project: Path) -> Path:
        (project / "package.json").write_text('{"name": "smoke", "version": "0.0.0"}\n')
        (project / "tsconfig.json").write_text(
            '{"compilerOptions": {"strict": true, "module": "commonjs", "target": "es2020"}}\n'
        )
        (project / "main.ts").write_text(TS_MAIN)
        (project / "helpers.ts").write_text(TS_HELPERS)
        return project

    async def test_definition_and_references(self, manager: LSPManager, ts_project: Path) -> None:
        output, meta = await _call(
            manager,
            ts_project,
            "goToDefinition",
            file_path=str(ts_project / "main.ts"),
            line=4,
            character=10,
        )
        _assert_compact(output)
        assert meta["status"] == "ok", output
        assert "helpers.ts" in output
        output, meta = await _call(
            manager,
            ts_project,
            "findReferences",
            file_path=str(ts_project / "helpers.ts"),
            line=1,
            character=17,
        )
        assert meta["status"] == "ok", output
        assert "main.ts" in output

    async def test_incoming_calls(self, manager: LSPManager, ts_project: Path) -> None:
        output, meta = await _call(
            manager,
            ts_project,
            "incomingCalls",
            file_path=str(ts_project / "helpers.ts"),
            line=1,
            character=17,
            depth=2,
        )
        assert meta["status"] in {"ok", "partial"}, output
        assert "compute" in output

    async def test_document_symbol(self, manager: LSPManager, ts_project: Path) -> None:
        output, meta = await _call(
            manager, ts_project, "documentSymbol", file_path=str(ts_project / "main.ts")
        )
        assert meta["status"] == "ok", output
        assert "function compute" in output
        assert "function entry" in output


GO_MAIN = """\
package main

func add(x int, y int) int {
\treturn x + y
}

func compute(a int, b int) int {
\treturn add(a, b)
}

func main() {
\t_ = compute(1, 2)
}
"""


class TestGopls:
    @pytest.fixture(autouse=True)
    def _available(self) -> None:
        _require("gopls")

    @pytest.fixture()
    def go_project(self, project: Path) -> Path:
        (project / "go.mod").write_text("module smoke\n\ngo 1.21\n")
        (project / "main.go").write_text(GO_MAIN)
        return project

    async def test_definition_and_calls(self, manager: LSPManager, go_project: Path) -> None:
        output, meta = await _call(
            manager,
            go_project,
            "goToDefinition",
            file_path=str(go_project / "main.go"),
            line=8,
            character=9,
        )
        _assert_compact(output)
        assert meta["status"] == "ok", output
        assert "main.go" in output and "3:6" in output
        output, meta = await _call(
            manager,
            go_project,
            "incomingCalls",
            file_path=str(go_project / "main.go"),
            line=3,
            character=6,
            depth=2,
        )
        assert meta["status"] in {"ok", "partial"}, output
        assert "compute" in output
        assert "main" in output
