"""Unit tests for bounded call hierarchy traversal and the tool operations."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from cognis.models.tool import ExecutorHandle
from cognis.tools.executor.lsp.hierarchy import (
    HierarchyLimits,
    HierarchyResult,
    format_call_tree,
    traverse_call_hierarchy,
)
from cognis.tools.executor.lsp.manager import LSPManager, PreparedClient
from cognis.tools.executor.lsp.query import QueryStatus
from cognis.tools.executor.lsp.tool import handle_lsp
from cognis.tools.registry import ToolExecutionContext

ROOT = "/project"


def _item(name: str, line: int, *, path: str = "a.py", kind: int = 12) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "uri": f"file://{ROOT}/{path}",
        "range": {
            "start": {"line": line, "character": 0},
            "end": {"line": line + 5, "character": 0},
        },
        "selectionRange": {
            "start": {"line": line, "character": 4},
            "end": {"line": line, "character": 4 + len(name)},
        },
    }


def _call(item: dict[str, Any], *from_lines: int, direction: str = "incoming") -> dict[str, Any]:
    key = "from" if direction == "incoming" else "to"
    return {
        key: item,
        "fromRanges": [
            {"start": {"line": n, "character": 8}, "end": {"line": n, "character": 12}}
            for n in from_lines
        ],
    }


class _Graph:
    """Fake client whose call graph is a dict of name -> list[(item, lines)]."""

    def __init__(
        self,
        roots: list[dict[str, Any]],
        edges: dict[str, list[dict[str, Any]]],
        *,
        direction: str = "incoming",
    ) -> None:
        self.server_id = "pyright"
        self.is_alive = True
        self.roots = roots
        self.edges = edges
        self.direction = direction
        self.requests: list[str] = []
        self.delay = 0.0

    async def prepare_call_hierarchy(self, *_: Any) -> list[dict[str, Any]]:
        self.requests.append("prepare")
        return self.roots

    async def _calls(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        self.requests.append(item["name"])
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.edges.get(item["name"], [])

    incoming_calls = _calls
    outgoing_calls = _calls


def _key(item: dict[str, Any]) -> str:
    return item["name"]


class TestTraversal:
    @pytest.mark.asyncio()
    async def test_call_sites_and_call_lists_are_bounded(self) -> None:
        """Hostile ``fromRanges`` and call lists stop at fixed intake caps."""
        from cognis.tools.executor.lsp.hierarchy import (
            MAX_RAW_CALL_SITES,
            MAX_RAW_CALLS,
            _call_site_lines,
        )

        ranges = [
            {"start": {"line": n, "character": 0}, "end": {"line": n, "character": 1}}
            for n in range(MAX_RAW_CALL_SITES * 5)
        ]
        assert len(_call_site_lines(ranges)) == MAX_RAW_CALL_SITES

        target = _item("target", 10)
        # All-malformed call list far larger than the cap, followed by one valid
        # edge that must NOT be reached: the cap bounds inspection, not validity.
        calls: list[Any] = ["junk"] * (MAX_RAW_CALLS + 10)
        calls.append({"from": _item("late_caller", 99), "fromRanges": []})
        client = _Graph([target], {"target": calls})
        result = await traverse_call_hierarchy(
            client,  # type: ignore[arg-type]
            "/project/a.py",
            10,
            4,
            direction="incoming",
            limits=HierarchyLimits(),
            cwd=ROOT,
        )
        assert result.edge_count == 0

    @pytest.mark.asyncio()
    async def test_incoming_tree_with_call_sites(self) -> None:
        target = _item("target", 10)
        caller_a = _item("caller_a", 20, path="b.py")
        caller_b = _item("caller_b", 30, path="c.py", kind=6)
        top = _item("top", 40, path="d.py")
        client = _Graph(
            [target],
            {
                "target": [_call(caller_a, 22, 25), _call(caller_b, 33)],
                "caller_a": [_call(top, 41)],
            },
        )
        result = await traverse_call_hierarchy(
            client,
            f"{ROOT}/a.py",
            10,
            4,
            direction="incoming",
            limits=HierarchyLimits(),
            cwd=ROOT,
        )

        assert result.status is QueryStatus.OK
        assert result.stop_reason is None
        assert result.node_count == 4
        assert result.edge_count == 3
        assert result.depth_reached == 2
        root = result.roots[0]
        assert (root.name, root.path, root.line) == ("target", "a.py", 11)
        assert [c.name for c in root.children] == ["caller_a", "caller_b"]
        assert root.children[0].call_sites == [23, 26]
        assert root.children[1].kind == "method"
        assert root.children[0].children[0].name == "top"
        listing = format_call_tree(result, direction="incoming")
        assert listing.text.splitlines() == [
            "function target  a.py:11",
            "  function caller_a  b.py:21  (called from line 23, 26)",
            "    function top  d.py:41  (called from line 42)",
            "  method caller_b  c.py:31  (called from line 34)",
        ]
        assert listing.truncated is False

    @pytest.mark.asyncio()
    async def test_outgoing_uses_to_key(self) -> None:
        source = _item("source", 1)
        callee = _item("callee", 50)
        client = _Graph(
            [source], {"source": [_call(callee, 3, direction="outgoing")]}, direction="outgoing"
        )
        result = await traverse_call_hierarchy(
            client,
            f"{ROOT}/a.py",
            1,
            4,
            direction="outgoing",
            limits=HierarchyLimits(),
            cwd=ROOT,
        )
        assert [c.name for c in result.roots[0].children] == ["callee"]
        text = format_call_tree(result, direction="outgoing").text
        assert "(call at line 4)" in text

    @pytest.mark.asyncio()
    async def test_cycle_is_marked_and_not_expanded(self) -> None:
        a = _item("a", 1)
        b = _item("b", 10)
        client = _Graph([a], {"a": [_call(b, 2)], "b": [_call(a, 11)]})
        result = await traverse_call_hierarchy(
            client,
            f"{ROOT}/a.py",
            1,
            4,
            direction="incoming",
            limits=HierarchyLimits(),
            cwd=ROOT,
        )
        assert result.status is QueryStatus.OK
        back_edge = result.roots[0].children[0].children[0]
        assert back_edge.name == "a"
        assert back_edge.note == "cycle"
        assert back_edge.children == []
        assert client.requests == ["prepare", "a", "b"]
        assert "already shown)" in format_call_tree(result, direction="incoming").text

    @pytest.mark.asyncio()
    async def test_depth_limit_is_partial(self) -> None:
        chain = [_item(f"n{i}", i * 10) for i in range(5)]
        edges = {f"n{i}": [_call(chain[i + 1], i * 10 + 1)] for i in range(4)}
        client = _Graph([chain[0]], edges)
        result = await traverse_call_hierarchy(
            client,
            f"{ROOT}/a.py",
            0,
            4,
            direction="incoming",
            limits=HierarchyLimits(max_depth=2),
            cwd=ROOT,
        )
        assert result.status is QueryStatus.PARTIAL
        assert result.stop_reason == "depth"
        assert result.depth_reached == 2
        assert client.requests == ["prepare", "n0", "n1"]
        leaf = result.roots[0].children[0].children[0]
        assert leaf.note == "depth"
        assert "depth limit)" in format_call_tree(result, direction="incoming").text

    @pytest.mark.asyncio()
    async def test_breadth_limit_per_node(self) -> None:
        root = _item("root", 0)
        callers = [_item(f"c{i}", i + 1) for i in range(5)]
        client = _Graph([root], {"root": [_call(c, 99) for c in callers]})
        result = await traverse_call_hierarchy(
            client,
            f"{ROOT}/a.py",
            0,
            4,
            direction="incoming",
            limits=HierarchyLimits(max_breadth=2),
            cwd=ROOT,
        )
        assert [c.name for c in result.roots[0].children] == ["c0", "c1"]
        assert result.roots[0].note == "breadth"
        assert result.edge_count == 2
        assert "(more callers omitted)" in format_call_tree(result, direction="incoming").text

    @pytest.mark.asyncio()
    async def test_node_and_edge_limits(self) -> None:
        root = _item("root", 0)
        callers = [_item(f"c{i}", i + 1) for i in range(6)]
        client = _Graph([root], {"root": [_call(c, 99) for c in callers]})

        nodes = await traverse_call_hierarchy(
            client,
            f"{ROOT}/a.py",
            0,
            4,
            direction="incoming",
            limits=HierarchyLimits(max_nodes=3),
            cwd=ROOT,
        )
        assert nodes.status is QueryStatus.PARTIAL
        assert nodes.stop_reason == "nodes"
        assert nodes.node_count == 3

        edges = await traverse_call_hierarchy(
            client,
            f"{ROOT}/a.py",
            0,
            4,
            direction="incoming",
            limits=HierarchyLimits(max_edges=4),
            cwd=ROOT,
        )
        assert edges.status is QueryStatus.PARTIAL
        assert edges.stop_reason == "edges"
        assert edges.edge_count == 4

    @pytest.mark.asyncio()
    async def test_time_budget_returns_partial_tree(self) -> None:
        root = _item("root", 0)
        c1 = _item("c1", 1)
        c2 = _item("c2", 2)
        client = _Graph([root], {"root": [_call(c1, 5)], "c1": [_call(c2, 6)]})
        client.delay = 0.2
        result = await traverse_call_hierarchy(
            client,
            f"{ROOT}/a.py",
            0,
            4,
            direction="incoming",
            limits=HierarchyLimits(time_budget_s=0.3),
            cwd=ROOT,
        )
        assert result.status is QueryStatus.PARTIAL
        assert result.stop_reason == "time"
        assert [c.name for c in result.roots[0].children] == ["c1"]
        assert result.roots[0].children[0].note == "limit"

    @pytest.mark.asyncio()
    async def test_prepare_timeout(self) -> None:
        client = _Graph([], {})

        async def slow_prepare(*_: Any) -> list[dict[str, Any]]:
            await asyncio.sleep(1)
            return []

        client.prepare_call_hierarchy = slow_prepare  # type: ignore[method-assign]
        result = await traverse_call_hierarchy(
            client,
            f"{ROOT}/a.py",
            0,
            4,
            direction="incoming",
            limits=HierarchyLimits(time_budget_s=0.1),
            cwd=ROOT,
        )
        assert result.status is QueryStatus.TIMEOUT
        assert result.stop_reason == "time"

    @pytest.mark.asyncio()
    async def test_server_exit_mid_traversal(self) -> None:
        root = _item("root", 0)
        c1 = _item("c1", 1)
        client = _Graph([root], {"root": [_call(c1, 5)]})

        async def dying(item: dict[str, Any]) -> list[dict[str, Any]]:
            if item["name"] == "c1":
                client.is_alive = False
                raise RuntimeError("closed")
            return client.edges[item["name"]]

        client.incoming_calls = dying  # type: ignore[method-assign]
        result = await traverse_call_hierarchy(
            client,
            f"{ROOT}/a.py",
            0,
            4,
            direction="incoming",
            limits=HierarchyLimits(),
            cwd=ROOT,
        )
        assert result.status is QueryStatus.PARTIAL
        assert result.stop_reason == "server_exited"
        assert [c.name for c in result.roots[0].children] == ["c1"]

    @pytest.mark.asyncio()
    async def test_prepare_failure_and_empty(self) -> None:
        failing = _Graph([], {})
        failing.prepare_call_hierarchy = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        failed = await traverse_call_hierarchy(
            failing,
            f"{ROOT}/a.py",
            0,
            4,
            direction="incoming",
            limits=HierarchyLimits(),
            cwd=ROOT,
        )
        assert failed.status is QueryStatus.FAILED
        assert failed.stop_reason == "request_failed"

        empty = await traverse_call_hierarchy(
            _Graph([], {}),
            f"{ROOT}/a.py",
            0,
            4,
            direction="incoming",
            limits=HierarchyLimits(),
            cwd=ROOT,
        )
        assert empty.status is QueryStatus.EMPTY
        assert empty.roots == []

    @pytest.mark.asyncio()
    async def test_malformed_items_are_skipped(self) -> None:
        root = _item("root", 0)
        client = _Graph(
            [root, {"name": "no-uri"}, "scalar"],  # type: ignore[list-item]
            {"root": [{"from": {"name": 3}}, 7, _call(_item("ok", 9), 1)]},
        )
        result = await traverse_call_hierarchy(
            client,
            f"{ROOT}/a.py",
            0,
            4,
            direction="incoming",
            limits=HierarchyLimits(),
            cwd=ROOT,
        )
        assert len(result.roots) == 1
        assert [c.name for c in result.roots[0].children] == ["ok"]

    def test_limits_from_arguments_clamps(self) -> None:
        assert HierarchyLimits.from_arguments(None).max_depth == 3
        assert HierarchyLimits.from_arguments(0).max_depth == 1
        assert HierarchyLimits.from_arguments(99).max_depth == 5
        assert HierarchyLimits.from_arguments(True).max_depth == 3
        assert HierarchyLimits.from_arguments("2").max_depth == 3


def _prepared(server_id: str, *, supports: bool) -> tuple[PreparedClient, MagicMock]:
    client = MagicMock()
    client.server_id = server_id
    client.is_alive = True
    client.supports.return_value = supports
    client.prepare_call_hierarchy = AsyncMock(return_value=[_item("f", 0)])
    client.incoming_calls = AsyncMock(return_value=[])
    client.outgoing_calls = AsyncMock(return_value=[])
    entry = PreparedClient(
        client=client,
        client_key=f"{server_id}:{ROOT}",
        uri=f"file://{ROOT}/a.py",
        language_id="python",
        version=0,
    )
    return entry, client


class TestManagerCallHierarchy:
    @pytest.mark.asyncio()
    async def test_first_capable_client_owns_traversal(self) -> None:
        manager = LSPManager(enabled=True)
        ruff_entry, ruff = _prepared("ruff", supports=False)
        pyright_entry, pyright = _prepared("pyright", supports=True)
        other_entry, other = _prepared("other", supports=True)
        manager.prepare_file = AsyncMock(return_value=[ruff_entry, pyright_entry, other_entry])  # type: ignore[method-assign]

        outcomes, result = await manager.call_hierarchy(
            f"{ROOT}/a.py", 0, 4, direction="incoming", cwd=ROOT
        )

        assert result is not None
        assert result.status is QueryStatus.OK
        assert [(o.server_id, o.status) for o in outcomes] == [
            ("pyright", QueryStatus.OK),
            ("ruff", QueryStatus.UNSUPPORTED),
            ("other", QueryStatus.UNSUPPORTED),
        ]
        pyright.prepare_call_hierarchy.assert_awaited_once()
        pyright.incoming_calls.assert_awaited_once()
        other.prepare_call_hierarchy.assert_not_awaited()
        ruff.prepare_call_hierarchy.assert_not_awaited()
        assert manager._last_access[f"pyright:{ROOT}"] > 0

    @pytest.mark.asyncio()
    async def test_no_capable_client(self) -> None:
        manager = LSPManager(enabled=True)
        entry, _ = _prepared("ruff", supports=False)
        manager.prepare_file = AsyncMock(return_value=[entry])  # type: ignore[method-assign]
        outcomes, result = await manager.call_hierarchy(f"{ROOT}/a.py", 0, 4, direction="outgoing")
        assert result is None
        assert [o.status for o in outcomes] == [QueryStatus.UNSUPPORTED]


def _context(lsp: Any, root: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        executor_handle=ExecutorHandle(executor_id="test", executor_type="in_process"),
        runtime_metadata={"lsp_manager": lsp, "working_directory": str(root)},
        execution_scope_id="scope-1",
    )


class _HierarchyLsp:
    def __init__(self, outcomes: list[Any], result: HierarchyResult | None) -> None:
        self.outcomes = outcomes
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def has_clients(self, *_: Any, **__: Any) -> bool:
        return True

    async def prepare_file(self, *_: Any, **__: Any) -> list[PreparedClient]:
        return []

    async def call_hierarchy(self, path: str, line: int, character: int, **kwargs: Any) -> Any:
        self.calls.append({"path": path, "line": line, "character": character, **kwargs})
        return self.outcomes, self.result


class TestToolOperations:
    @pytest.fixture()
    def workspace(self, tmp_path: Path) -> tuple[Path, Path]:
        target = tmp_path / "pkg" / "sample.py"
        target.parent.mkdir()
        target.write_text("def value():\n    return 1\n\nprint(value())\n")
        return tmp_path, target

    @pytest.mark.asyncio()
    async def test_incoming_calls_renders_tree(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        graph = _Graph([_item("value", 0)], {"value": [_call(_item("main", 3), 3)]})
        traversal = await traverse_call_hierarchy(
            graph,
            str(target),
            0,
            4,
            direction="incoming",
            limits=HierarchyLimits(),
            cwd=str(root),
        )
        from cognis.tools.executor.lsp.query import QueryOutcome

        lsp = _HierarchyLsp(
            [QueryOutcome(server_id="pyright", status=traversal.status, duration_ms=3)], traversal
        )
        result = await handle_lsp(
            {
                "operation": "incomingCalls",
                "file_path": str(target),
                "line": 1,
                "character": 5,
                "depth": 2,
            },
            _context(lsp, root),
        )

        assert result.is_error is False
        assert result.output.splitlines()[0] == "incomingCalls pkg/sample.py:1:5: 1 caller, depth 1"
        assert "  function main  /project/a.py:4  (called from line 4)" in result.output
        call = lsp.calls[0]
        assert (call["line"], call["character"], call["direction"]) == (0, 4, "incoming")
        assert call["limits"].max_depth == 2
        assert result.metadata is not None
        assert result.metadata["operation"] == "incomingCalls"
        assert result.metadata["status"] == "ok"
        assert result.metadata["edge_count"] == 1
        assert result.metadata["depth_reached"] == 1
        assert result.metadata["node_count"] == 2
        assert "file://" not in result.output

    @pytest.mark.asyncio()
    async def test_partial_result_is_labeled(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        chain = [_item(f"n{i}", i) for i in range(4)]
        graph = _Graph(
            [chain[0]],
            {f"n{i}": [_call(chain[i + 1], i, direction="outgoing")] for i in range(3)},
            direction="outgoing",
        )
        traversal = await traverse_call_hierarchy(
            graph,
            str(target),
            0,
            4,
            direction="outgoing",
            limits=HierarchyLimits(max_depth=1),
            cwd=str(root),
        )
        from cognis.tools.executor.lsp.query import QueryOutcome

        lsp = _HierarchyLsp([QueryOutcome(server_id="pyright", status=traversal.status)], traversal)
        result = await handle_lsp(
            {"operation": "outgoingCalls", "file_path": str(target), "line": 1, "character": 5},
            _context(lsp, root),
        )
        assert result.output.splitlines()[0] == (
            "outgoingCalls pkg/sample.py:1:5: 1 callee, depth 1, partial (depth)"
        )
        assert result.metadata is not None
        assert result.metadata["status"] == "partial"
        assert result.metadata["truncated"] is True
        assert result.metadata["stop_reason"] == "depth"

    @pytest.mark.asyncio()
    async def test_unsupported_when_no_server_negotiated(
        self, workspace: tuple[Path, Path]
    ) -> None:
        root, target = workspace
        from cognis.tools.executor.lsp.query import QueryOutcome

        lsp = _HierarchyLsp(
            [
                QueryOutcome(
                    server_id="ruff",
                    status=QueryStatus.UNSUPPORTED,
                    message="method not negotiated",
                )
            ],
            None,
        )
        result = await handle_lsp(
            {"operation": "incomingCalls", "file_path": str(target), "line": 1, "character": 5},
            _context(lsp, root),
        )
        assert result.output.startswith("incomingCalls pkg/sample.py:1:5: unsupported")
        assert "ruff" in result.output
        assert result.metadata is not None
        assert result.metadata["status"] == "unsupported"

    @pytest.mark.asyncio()
    async def test_requires_position(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        result = await handle_lsp(
            {"operation": "incomingCalls", "file_path": str(target)},
            _context(_HierarchyLsp([], None), root),
        )
        assert result.is_error is True
        assert "line" in result.output

    @pytest.mark.asyncio()
    async def test_failed_traversal_is_error(self, workspace: tuple[Path, Path]) -> None:
        root, target = workspace
        from cognis.tools.executor.lsp.query import QueryOutcome

        failed = HierarchyResult(
            status=QueryStatus.FAILED,
            roots=[],
            node_count=0,
            edge_count=0,
            depth_reached=0,
            duration_ms=1,
            stop_reason="request_failed",
        )
        lsp = _HierarchyLsp([QueryOutcome(server_id="pyright", status=QueryStatus.FAILED)], failed)
        result = await handle_lsp(
            {"operation": "incomingCalls", "file_path": str(target), "line": 1, "character": 5},
            _context(lsp, root),
        )
        assert result.is_error is True
        assert result.output.splitlines()[0] == "incomingCalls pkg/sample.py:1:5: failed"
