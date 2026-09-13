"""Unit tests for compact LSP result formatting."""

from __future__ import annotations

from pathlib import Path

from cognis.tools.executor.lsp.format import (
    LocationItem,
    bound_output,
    build_outline,
    clamp_limit,
    format_hover,
    format_locations,
    format_outline,
    format_workspace_symbols,
    location_from_payload,
    make_snippet_loader,
    normalize_locations,
    normalize_symbols,
    relative_path,
)


def _loc(path: str, line: int, col: int) -> dict:
    return {
        "uri": f"file://{path}",
        "range": {
            "start": {"line": line, "character": col},
            "end": {"line": line, "character": col + 3},
        },
    }


class TestLocations:
    def test_location_is_relative_and_one_based(self) -> None:
        item = location_from_payload(_loc("/w/src/a.py", 4, 2), cwd="/w")
        assert item == LocationItem("src/a.py", 5, 3, 5, 6)

    def test_location_link_prefers_selection_range(self) -> None:
        raw = {
            "targetUri": "file:///w/b.py",
            "targetRange": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 9, "character": 0},
            },
            "targetSelectionRange": {
                "start": {"line": 1, "character": 4},
                "end": {"line": 1, "character": 7},
            },
        }
        item = location_from_payload(raw, cwd="/w")
        assert item is not None
        assert (item.line, item.column) == (2, 5)

    def test_malformed_payloads_are_dropped(self) -> None:
        items = normalize_locations(
            [
                "junk",
                {"uri": 3},
                {"uri": "file:///w/a.py"},
                {"uri": "file:///w/a.py", "range": {"start": {"line": -1, "character": 0}}},
                {"uri": "file:///w/a.py", "range": {"start": {"line": "x", "character": 0}}},
                _loc("/w/a.py", 0, 0),
            ],
            cwd="/w",
        )
        assert [(i.path, i.line, i.column) for i in items] == [("a.py", 1, 1)]

    def test_dedup_and_order_are_deterministic(self) -> None:
        items = normalize_locations(
            [
                _loc("/w/b.py", 3, 0),
                _loc("/w/a.py", 9, 0),
                _loc("/w/a.py", 2, 5),
                _loc("/w/a.py", 2, 5),
                _loc("/w/a.py", 2, 1),
            ],
            cwd="/w",
        )
        assert [(i.path, i.line, i.column) for i in items] == [
            ("a.py", 3, 2),
            ("a.py", 3, 6),
            ("a.py", 10, 1),
            ("b.py", 4, 1),
        ]

    def test_paths_outside_cwd_stay_absolute(self) -> None:
        assert relative_path("/other/x.py", "/w") == "/other/x.py"
        assert relative_path("/w/x.py", None) == "/w/x.py"

    def test_format_groups_by_file_and_truncates(self) -> None:
        items = normalize_locations(
            [_loc("/w/a.py", 0, 0), _loc("/w/a.py", 5, 0), _loc("/w/b.py", 0, 0)], cwd="/w"
        )
        listing = format_locations(items, limit=2)
        assert listing.text == "a.py\n  1:1\n  6:1\n... 1 more (raise limit to see them)"
        assert listing.total == 3
        assert listing.shown == 2
        assert listing.truncated
        assert listing.items == [
            {"path": "a.py", "line": 1, "column": 1, "end_line": 1, "end_column": 4},
            {"path": "a.py", "line": 6, "column": 1, "end_line": 6, "end_column": 4},
        ]
        assert "file://" not in listing.text

    def test_snippet_loader_reads_trimmed_lines_once(self, tmp_path: Path) -> None:
        target = tmp_path / "a.py"
        target.write_text("first\n    second = " + "x" * 200 + "\n")
        cache: dict[str, list[str] | None] = {}
        loader = make_snippet_loader(cwd=str(tmp_path), cache=cache)
        assert loader("a.py", 1) == "first"
        snippet = loader("a.py", 2)
        assert snippet is not None
        assert snippet.startswith("second = xxx") and snippet.endswith("...")
        assert len(snippet) == 120
        assert loader("a.py", 99) is None
        assert loader("missing.py", 1) is None
        assert len(cache) == 2

        listing = format_locations(
            normalize_locations([_loc(str(target), 0, 0)], cwd=str(tmp_path)),
            limit=10,
            snippet_loader=loader,
        )
        assert listing.text == "a.py\n  1:1  first"

    def test_clamp_limit(self) -> None:
        assert clamp_limit(None) == 50
        assert clamp_limit("5") == 50
        assert clamp_limit(True) == 50
        assert clamp_limit(0) == 1
        assert clamp_limit(10_000) == 200
        assert clamp_limit(7) == 7


class TestSymbols:
    def test_workspace_symbols(self) -> None:
        items = normalize_symbols(
            [
                {
                    "name": "run",
                    "kind": 12,
                    "location": _loc("/w/b.py", 10, 0),
                    "containerName": "Runner",
                },
                {"name": "run", "kind": 12, "location": _loc("/w/b.py", 10, 0)},
                {"name": "Runner", "kind": 5, "location": {"uri": "file:///w/a.py"}},
                {"kind": 5, "location": _loc("/w/a.py", 0, 0)},
            ],
            cwd="/w",
        )
        listing = format_workspace_symbols(items, limit=10)
        assert listing.text == "class Runner  a.py\nfunction run  b.py:11  in Runner"
        assert listing.total == 2

    def test_outline_from_hierarchical_symbols(self) -> None:
        raw = [
            {
                "name": "Runner",
                "kind": 5,
                "detail": "class Runner(Base)",
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 20, "character": 0},
                },
                "children": [
                    {
                        "name": "stop",
                        "kind": 6,
                        "range": {
                            "start": {"line": 10, "character": 4},
                            "end": {"line": 12, "character": 0},
                        },
                    },
                    {
                        "name": "run",
                        "kind": 6,
                        "detail": "def run(self) -> None",
                        "range": {
                            "start": {"line": 2, "character": 4},
                            "end": {"line": 8, "character": 0},
                        },
                    },
                ],
            },
            {
                "name": "main",
                "kind": 12,
                "range": {
                    "start": {"line": 22, "character": 0},
                    "end": {"line": 22, "character": 9},
                },
            },
        ]
        listing = format_outline(build_outline(raw, cwd="/w"), limit=50)
        assert listing.text.splitlines() == [
            "class Runner (L1-21)  class Runner(Base)",
            "  method run (L3-9)  def run(self) -> None",
            "  method stop (L11-13)",
            "function main (L23)",
        ]
        assert listing.total == 4
        assert listing.items[0]["children"][0]["name"] == "run"

    def test_outline_limit_and_depth(self) -> None:
        deep = {
            "name": "a",
            "kind": 5,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            "children": [
                {
                    "name": "b",
                    "kind": 5,
                    "range": {
                        "start": {"line": 1, "character": 0},
                        "end": {"line": 1, "character": 0},
                    },
                    "children": [
                        {
                            "name": "c",
                            "kind": 5,
                            "range": {
                                "start": {"line": 2, "character": 0},
                                "end": {"line": 2, "character": 0},
                            },
                        }
                    ],
                }
            ],
        }
        listing = format_outline(build_outline([deep], cwd=None), limit=50, max_depth=2)
        assert listing.text.splitlines() == [
            "class a (L1)",
            "  class b (L2)",
            "    ... 1 nested symbol(s)",
        ]
        limited = format_outline(build_outline([deep], cwd=None), limit=1)
        assert limited.truncated
        assert limited.text.endswith("... 2 more symbol(s) (raise limit to see them)")

    def test_outline_intake_is_bounded_against_hostile_payloads(self) -> None:
        """Deep nesting, wide fan-out and huge trees stop at fixed budgets."""

        def sym(name: str, children: list) -> dict:
            return {
                "name": name,
                "kind": 5,
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
                "children": children,
            }

        deep: dict = sym("leaf", [])
        for i in range(10_000):
            deep = sym(f"n{i}", [deep])
        roots = build_outline([deep], cwd=None)  # must not raise RecursionError
        depth = 0
        node = roots[0]
        while node.children:
            node = node.children[0]
            depth += 1
        assert depth < 16

        wide = sym("wide", [sym(f"c{i}", []) for i in range(5_000)])
        assert len(build_outline([wide], cwd=None)[0].children) == 500

        forest = [sym(f"r{i}", [sym(f"c{i}-{j}", []) for j in range(10)]) for i in range(2_000)]
        total = sum(1 + len(root.children) for root in build_outline(forest, cwd=None))
        assert total <= 5000

    def test_non_file_uris_are_dropped(self) -> None:
        assert (
            location_from_payload(
                {"uri": "https://x/y", "range": _loc("/a", 0, 0)["range"]}, cwd=None
            )
            is None
        )
        assert (
            location_from_payload(
                {"uri": "untitled:1", "range": _loc("/a", 0, 0)["range"]}, cwd=None
            )
            is None
        )
        assert (
            normalize_symbols(
                [{"name": "n", "kind": 5, "location": {"uri": "https://x"}}], cwd=None
            )
            == []
        )

    def test_snippet_loader_stays_inside_workspace(self, tmp_path: Path) -> None:
        root = tmp_path / "w"
        root.mkdir()
        (root / "in.py").write_text("inside\n")
        outside = tmp_path / "secret.txt"
        outside.write_text("secret\n")
        (root / "link.txt").symlink_to(outside)
        load = make_snippet_loader(cwd=str(root), cache={})
        assert load("in.py", 1) == "inside"
        assert load(str(outside), 1) is None
        assert load("link.txt", 1) is None
        assert load("../secret.txt", 1) is None
        assert make_snippet_loader(cwd=None, cache={})(str(root / "in.py"), 1) is None

    def test_outline_from_flat_symbols_and_merge_dedup(self) -> None:
        flat = [
            {"name": "Runner", "kind": 5, "location": _loc("/w/a.py", 0, 0)},
            {
                "name": "run",
                "kind": 6,
                "location": _loc("/w/a.py", 2, 0),
                "containerName": "Runner",
            },
        ]
        hierarchical = {
            "name": "Runner",
            "kind": 5,
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 5, "character": 0}},
        }
        roots = build_outline([hierarchical, *flat], cwd="/w")
        assert [r.name for r in roots] == ["Runner"]
        assert [c.name for c in roots[0].children] == []  # hierarchical root wins


class TestHover:
    def test_hover_markup_variants_deduplicated(self) -> None:
        listing = format_hover(
            [
                {"contents": {"kind": "markdown", "value": "```python\ndef f()\n```"}},
                {"contents": {"language": "python", "value": "def f()"}},
                {"contents": ["plain", {"language": "python", "value": "def f()"}]},
                {"contents": {"kind": "markdown", "value": "```python\ndef f()\n```"}},
                "junk",
            ]
        )
        # The fenced block appears twice as identical text and once combined with "plain".
        assert listing.total == 2
        assert listing.text.startswith("```python\ndef f()\n```")
        assert "plain" in listing.text

    def test_hover_truncates(self) -> None:
        listing = format_hover([{"contents": "x" * 5000}], max_chars=100)
        assert listing.truncated
        assert listing.text.endswith("(hover text truncated)")


class TestBoundOutput:
    def test_bound_output_clips_bytes(self) -> None:
        text, clipped = bound_output("é" * 100, max_bytes=21)
        assert clipped
        assert text.startswith("é" * 10)
        assert text.endswith("(output truncated)")
        assert bound_output("ok") == ("ok", False)
