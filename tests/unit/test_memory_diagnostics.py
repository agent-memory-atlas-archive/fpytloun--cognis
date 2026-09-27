import asyncio
import tracemalloc
from unittest.mock import Mock

import pytest

from cognis.core.memory_diagnostics import MemoryDiagnostics


@pytest.mark.asyncio
async def test_disabled_and_pod_selection(monkeypatch):
    monkeypatch.delenv("COGNIS_MEMORY_PROFILING", raising=False)
    diagnostics = MemoryDiagnostics()
    diagnostics.start()
    assert diagnostics.task is None
    await diagnostics.stop()
    monkeypatch.setenv("COGNIS_MEMORY_PROFILING", "true")
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_POD", "selected-pod")
    monkeypatch.setattr("socket.gethostname", lambda: "other-pod")
    assert not MemoryDiagnostics().enabled


@pytest.mark.asyncio
async def test_sampler_lifecycle_and_external_tracer(monkeypatch):
    monkeypatch.setenv("COGNIS_MEMORY_PROFILING", "true")
    monkeypatch.delenv("COGNIS_MEMORY_PROFILE_POD", raising=False)
    monkeypatch.setattr(tracemalloc, "is_tracing", lambda: True)
    stop = Mock()
    monkeypatch.setattr(tracemalloc, "stop", stop)
    diagnostics = MemoryDiagnostics()
    sampled = asyncio.Event()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(diagnostics, "sample", lambda: loop.call_soon_threadsafe(sampled.set))
    diagnostics.start()
    await asyncio.wait_for(sampled.wait(), 2)
    await diagnostics.stop()
    assert diagnostics.task.done()
    stop.assert_not_called()


def test_configuration_bounds(monkeypatch):
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_TRACEBACK_DEPTH", "100")
    diagnostics = MemoryDiagnostics()
    assert diagnostics.interval == 10
    assert diagnostics.depth == 10


def test_snapshots_default_to_full_traceback_depth(monkeypatch):
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_SNAPSHOTS", "true")
    monkeypatch.delenv("COGNIS_MEMORY_PROFILE_TRACEBACK_DEPTH", raising=False)
    assert MemoryDiagnostics().depth == 10


def test_default_samples_never_take_or_retain_snapshots(monkeypatch):
    monkeypatch.delenv("COGNIS_MEMORY_PROFILE_SNAPSHOTS", raising=False)
    snapshot = Mock(side_effect=AssertionError("expensive snapshot in counters-only mode"))
    monkeypatch.setattr(tracemalloc, "take_snapshot", snapshot)
    diagnostics = MemoryDiagnostics()
    for _ in range(3):
        diagnostics.sample()
    snapshot.assert_not_called()
    assert diagnostics.previous is None


def test_snapshots_require_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_SNAPSHOTS", "true")
    snapshot = Mock()
    snapshot.statistics.return_value = []
    take = Mock(return_value=snapshot)
    monkeypatch.setattr(tracemalloc, "take_snapshot", take)
    diagnostics = MemoryDiagnostics()
    diagnostics.mark_application_started()
    diagnostics.sample()
    diagnostics.sample()
    assert take.call_count == 2
    assert diagnostics.previous == {}
    snapshot.statistics.assert_called_with("traceback")


def test_snapshots_log_complete_tracebacks_and_counts(monkeypatch, caplog):
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_SNAPSHOTS", "true")
    frame_a = Mock(__str__=Mock(return_value="cognis/caller.py:10"))
    frame_b = Mock(__str__=Mock(return_value="json/decoder.py:354"))
    statistic = Mock(traceback=(frame_a, frame_b), size=1234, count=7)
    snapshot = Mock()
    snapshot.statistics.return_value = [statistic]
    monkeypatch.setattr(tracemalloc, "take_snapshot", Mock(return_value=snapshot))
    diagnostics = MemoryDiagnostics()
    diagnostics.mark_application_started()
    diagnostics.previous = {("cognis/caller.py:10", "json/decoder.py:354"): (234, 2)}

    with caplog.at_level("INFO", logger="cognis.core.memory_diagnostics"):
        diagnostics.sample()

    assert "(('cognis/caller.py:10', 'json/decoder.py:354'), 1234, 7)" in caplog.text
    assert "(('cognis/caller.py:10', 'json/decoder.py:354'), 1000, 5)" in caplog.text


def test_snapshot_deltas_include_released_tracebacks(monkeypatch, caplog):
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_SNAPSHOTS", "true")
    snapshot = Mock()
    snapshot.statistics.return_value = []
    monkeypatch.setattr(tracemalloc, "take_snapshot", Mock(return_value=snapshot))
    diagnostics = MemoryDiagnostics()
    diagnostics.mark_application_started()
    diagnostics.previous = {("cognis/released.py:20",): (2048, 12)}

    with caplog.at_level("INFO", logger="cognis.core.memory_diagnostics"):
        diagnostics.sample()

    assert "(('cognis/released.py:20',), -2048, -12)" in caplog.text


def test_snapshots_wait_for_application_startup(monkeypatch):
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_SNAPSHOTS", "true")
    take = Mock()
    monkeypatch.setattr(tracemalloc, "take_snapshot", take)
    diagnostics = MemoryDiagnostics()

    diagnostics.sample()

    take.assert_not_called()
    assert diagnostics.previous is None
