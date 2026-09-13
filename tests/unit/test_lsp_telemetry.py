"""Unit tests for controller-side LSP telemetry derived from tool result metadata."""

from __future__ import annotations

from typing import Any

import pytest
from prometheus_client import REGISTRY

from cognis.core import lsp_telemetry
from cognis.core.lsp_telemetry import record_lsp_tool_result


def _value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels or None) or 0.0


def _hist_count(name: str, **labels: str) -> float:
    return _value(f"{name}_count", **labels)


def _hist_sum(name: str, **labels: str) -> float:
    return _value(f"{name}_sum", **labels)


def _edit_metadata(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "status": "fresh",
        "injection": "injected",
        "injected_bytes": 300,
        "estimated_tokens": 75,
        "error_count": 2,
        "warning_count": 1,
        "suppressed_unchanged_count": 0,
        "status_counts": {"fresh": 1, "timeout": 1},
        "waits": [{"server_id": "ruff", "uri": "file:///secret/path.py", "status": "fresh"}],
    }
    data.update(overrides)
    return {"lsp_diagnostics": data}


class TestEditDiagnostics:
    def test_counts_status_injection_waits_and_severity(self) -> None:
        before = {
            "diag": _value("cognis_lsp_edit_diagnostics_total", status="fresh"),
            "inj": _value("cognis_lsp_edit_injection_total", outcome="injected"),
            "wait_fresh": _value("cognis_lsp_edit_wait_total", status="fresh"),
            "wait_timeout": _value("cognis_lsp_edit_wait_total", status="timeout"),
            "err": _value("cognis_lsp_edit_diagnostics_by_severity_total", severity="error"),
            "warn": _value("cognis_lsp_edit_diagnostics_by_severity_total", severity="warning"),
            "bytes_count": _hist_count("cognis_lsp_edit_injected_bytes"),
            "bytes_sum": _hist_sum("cognis_lsp_edit_injected_bytes"),
        }
        record_lsp_tool_result("edit", _edit_metadata(), 12)

        assert _value("cognis_lsp_edit_diagnostics_total", status="fresh") == before["diag"] + 1
        assert _value("cognis_lsp_edit_injection_total", outcome="injected") == before["inj"] + 1
        assert _value("cognis_lsp_edit_wait_total", status="fresh") == before["wait_fresh"] + 1
        assert _value("cognis_lsp_edit_wait_total", status="timeout") == before["wait_timeout"] + 1
        assert (
            _value("cognis_lsp_edit_diagnostics_by_severity_total", severity="error")
            == before["err"] + 2
        )
        assert (
            _value("cognis_lsp_edit_diagnostics_by_severity_total", severity="warning")
            == before["warn"] + 1
        )
        assert _hist_count("cognis_lsp_edit_injected_bytes") == before["bytes_count"] + 1
        assert _hist_sum("cognis_lsp_edit_injected_bytes") == before["bytes_sum"] + 300

    def test_bytes_only_observed_when_injected(self) -> None:
        before = _hist_count("cognis_lsp_edit_injected_bytes")
        record_lsp_tool_result(
            "write", _edit_metadata(injection="clean", injected_bytes=20, error_count=0), None
        )
        assert _hist_count("cognis_lsp_edit_injected_bytes") == before
        assert _value("cognis_lsp_edit_injection_total", outcome="clean") >= 1

    @pytest.mark.parametrize("tool", ["edit", "multiedit", "write"])
    def test_all_edit_tools_are_counted(self, tool: str) -> None:
        before = _value("cognis_lsp_edit_diagnostics_total", status="unavailable")
        record_lsp_tool_result(tool, _edit_metadata(status="unavailable", injection="none"), 1)
        assert _value("cognis_lsp_edit_diagnostics_total", status="unavailable") == before + 1

    def test_unknown_values_map_to_other(self) -> None:
        before_status = _value("cognis_lsp_edit_diagnostics_total", status="other")
        before_wait = _value("cognis_lsp_edit_wait_total", status="other")
        record_lsp_tool_result(
            "edit",
            _edit_metadata(
                status="/home/user/secret.py",
                injection="SELECT *",
                status_counts={"file:///x": 3, "fresh": "not-an-int", "stale": -1},
            ),
            1,
        )
        assert _value("cognis_lsp_edit_diagnostics_total", status="other") == before_status + 1
        assert _value("cognis_lsp_edit_wait_total", status="other") == before_wait + 3
        assert _value("cognis_lsp_edit_injection_total", outcome="other") >= 1

    def test_missing_or_malformed_metadata_is_ignored(self) -> None:
        before = _value("cognis_lsp_edit_diagnostics_total", status="other")
        record_lsp_tool_result("edit", None, 1)
        record_lsp_tool_result("edit", {"lsp_diagnostics": "nope"}, 1)
        record_lsp_tool_result("edit", {}, 1)
        record_lsp_tool_result("read", _edit_metadata(), 1)
        assert _value("cognis_lsp_edit_diagnostics_total", status="other") == before


class TestToolOperations:
    def test_counts_operation_status_duration_bytes_truncation(self) -> None:
        before_ops = _value(
            "cognis_lsp_tool_operations_total", operation="findReferences", status="ok"
        )
        before_dur = _hist_count("cognis_lsp_tool_duration_seconds", operation="findReferences")
        before_bytes = _hist_sum("cognis_lsp_tool_output_bytes", operation="findReferences")
        before_trunc = _value("cognis_lsp_tool_truncated_total", operation="findReferences")
        record_lsp_tool_result(
            "lsp",
            {
                "operation": "findReferences",
                "status": "ok",
                "output_bytes": 1500,
                "truncated": True,
                "result": [{"path": "pkg/secret.py", "line": 3}],
                "servers": [{"server_id": "pyright", "status": "ok"}],
            },
            250,
        )
        assert (
            _value("cognis_lsp_tool_operations_total", operation="findReferences", status="ok")
            == before_ops + 1
        )
        assert (
            _hist_count("cognis_lsp_tool_duration_seconds", operation="findReferences")
            == before_dur + 1
        )
        assert (
            _hist_sum("cognis_lsp_tool_output_bytes", operation="findReferences")
            == before_bytes + 1500
        )
        assert (
            _value("cognis_lsp_tool_truncated_total", operation="findReferences")
            == before_trunc + 1
        )

    def test_hierarchy_edges_only_for_hierarchy_operations(self) -> None:
        before = _hist_count("cognis_lsp_tool_hierarchy_edges")
        record_lsp_tool_result(
            "lsp", {"operation": "incomingCalls", "status": "partial", "edge_count": 7}, 90
        )
        record_lsp_tool_result(
            "lsp", {"operation": "documentSymbol", "status": "ok", "edge_count": 7}, 90
        )
        assert _hist_count("cognis_lsp_tool_hierarchy_edges") == before + 1

    def test_unknown_operation_and_status_map_to_other(self) -> None:
        before = _value("cognis_lsp_tool_operations_total", operation="other", status="other")
        record_lsp_tool_result(
            "lsp", {"operation": "textDocument/secret", "status": "boom: /etc/passwd"}, "fast"
        )
        assert (
            _value("cognis_lsp_tool_operations_total", operation="other", status="other")
            == before + 1
        )

    def test_edit_metadata_on_lsp_tool_is_not_counted_as_edit(self) -> None:
        before = _value("cognis_lsp_edit_diagnostics_total", status="fresh")
        record_lsp_tool_result("lsp", _edit_metadata() | {"operation": "hover", "status": "ok"}, 1)
        assert _value("cognis_lsp_edit_diagnostics_total", status="fresh") == before


class TestLabelHygiene:
    def test_all_label_values_come_from_fixed_enums(self) -> None:
        metrics = (
            lsp_telemetry.LSP_EDIT_DIAGNOSTICS_TOTAL,
            lsp_telemetry.LSP_EDIT_INJECTION_TOTAL,
            lsp_telemetry.LSP_EDIT_WAIT_TOTAL,
            lsp_telemetry.LSP_EDIT_DIAGNOSTICS_BY_SEVERITY_TOTAL,
            lsp_telemetry.LSP_TOOL_OPERATIONS_TOTAL,
            lsp_telemetry.LSP_TOOL_DURATION_SECONDS,
            lsp_telemetry.LSP_TOOL_OUTPUT_BYTES,
            lsp_telemetry.LSP_TOOL_TRUNCATED_TOTAL,
        )
        allowed = (
            lsp_telemetry.EDIT_DIAGNOSTIC_STATUSES
            | lsp_telemetry.EDIT_INJECTION_OUTCOMES
            | lsp_telemetry.EDIT_WAIT_STATUSES
            | lsp_telemetry.TOOL_OPERATIONS
            | lsp_telemetry.TOOL_STATUSES
            | {"error", "warning", lsp_telemetry.OTHER}
        )
        # Drive every branch with hostile values first so label sets are populated.
        record_lsp_tool_result(
            "edit",
            _edit_metadata(status="../x", injection="file:///y", status_counts={"z": 1}),
            1,
        )
        record_lsp_tool_result("lsp", {"operation": "rm -rf", "status": "q"}, 1)
        for metric in metrics:
            for sample in metric.collect()[0].samples:
                for key, value in sample.labels.items():
                    if key in ("le",):
                        continue
                    assert value in allowed, (metric, key, value)


class TestRobustness:
    def test_apply_patch_is_an_edit_tool(self) -> None:
        before = _value("cognis_lsp_edit_diagnostics_total", status="fresh")
        record_lsp_tool_result("apply_patch", _edit_metadata(), 3)
        assert _value("cognis_lsp_edit_diagnostics_total", status="fresh") == before + 1

    def test_huge_numbers_never_raise(self) -> None:
        record_lsp_tool_result(
            "lsp",
            {"operation": "hover", "status": "ok", "output_bytes": 10**400, "edge_count": 2**70},
            10**400,
        )
        record_lsp_tool_result(
            "edit", _edit_metadata(injected_bytes=10**400, error_count=10**400), 10**400
        )

    def test_recorder_isolates_internal_failures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_: Any, **__: Any) -> None:
            raise RuntimeError("registry exploded")

        monkeypatch.setattr(lsp_telemetry.LSP_TOOL_OPERATIONS_TOTAL, "labels", boom)
        record_lsp_tool_result("lsp", {"operation": "hover", "status": "ok"}, 1)
