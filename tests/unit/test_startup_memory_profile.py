"""The operator wrapper must not profile a disabled or unselected controller."""

import builtins
import runpy
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/scripts/startup-memory-profile.py"


@pytest.mark.parametrize("flag,pod", [("", ""), ("false", ""), ("0", ""), ("true", "other")])
def test_disabled_wrapper_execs_without_importing_memray(monkeypatch, flag, pod):
    namespace = runpy.run_path(str(SCRIPT))
    monkeypatch.setenv("COGNIS_MEMORY_PROFILING", flag)
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_POD", pod)
    monkeypatch.setattr("socket.gethostname", lambda: "selected")
    execv = Mock()
    monkeypatch.setattr("os.execv", execv)
    original_import = builtins.__import__

    def checked_import(name, *args, **kwargs):
        assert name != "memray"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    namespace["main"]()
    execv.assert_called_once_with("/opt/venv/bin/cognis-controller", ["cognis-controller", "serve"])


@pytest.mark.parametrize("timer_fires", [False, True])
def test_enabled_wrapper_stops_tracker_exactly_once(monkeypatch, timer_fires):
    namespace = runpy.run_path(str(SCRIPT))
    monkeypatch.setenv("COGNIS_MEMORY_PROFILING", "true")
    monkeypatch.setenv("COGNIS_MEMORY_PROFILE_POD", "selected")
    monkeypatch.setattr("socket.gethostname", lambda: "selected")
    tracker = MagicMock()
    monkeypatch.setitem(sys.modules, "memray", SimpleNamespace(Tracker=Mock(return_value=tracker)))
    timer = Mock()

    def make_timer(seconds, stop):
        assert seconds == 90
        if timer_fires:
            timer.start.side_effect = stop
        return timer

    monkeypatch.setattr("threading.Timer", make_timer)
    monkeypatch.setattr("runpy.run_path", Mock(side_effect=RuntimeError("controller exit")))
    monkeypatch.setattr(sys, "argv", [])
    with pytest.raises(RuntimeError, match="controller exit"):
        namespace["main"]()
    tracker.__enter__.assert_called_once()
    tracker.__exit__.assert_called_once_with(None, None, None)
    timer.cancel.assert_called_once()


def test_timer_and_controller_exit_race_closes_once(monkeypatch):
    namespace = runpy.run_path(str(SCRIPT))
    monkeypatch.setenv("COGNIS_MEMORY_PROFILING", "1")
    monkeypatch.delenv("COGNIS_MEMORY_PROFILE_POD", raising=False)
    tracker = MagicMock()
    monkeypatch.setitem(sys.modules, "memray", SimpleNamespace(Tracker=Mock(return_value=tracker)))
    barrier = threading.Barrier(2, timeout=5)
    workers = []

    def make_timer(seconds, stop):
        def expire():
            barrier.wait()
            stop()

        worker = threading.Thread(target=expire)
        workers.append(worker)
        return SimpleNamespace(start=worker.start, cancel=lambda: None, daemon=True)

    monkeypatch.setattr("threading.Timer", make_timer)
    monkeypatch.setattr("runpy.run_path", lambda *args, **kwargs: barrier.wait())
    monkeypatch.setattr(sys, "argv", [])
    namespace["main"]()
    workers[0].join(timeout=5)
    assert not workers[0].is_alive()
    tracker.__exit__.assert_called_once_with(None, None, None)
