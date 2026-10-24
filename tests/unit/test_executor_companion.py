"""Companion CLI contract: injected commands only, no installed service operations."""

from __future__ import annotations

import json
import signal
import subprocess
from unittest.mock import Mock

import pytest

from cognis.executor import __main__ as cli
from cognis.executor import service


def test_companion_status_and_operation_reobserve(monkeypatch):
    calls = []
    state = "stopped"

    def run(argv):
        nonlocal state
        calls.append(tuple(argv))
        if "list" in argv and "--versions" in argv:
            return subprocess.CompletedProcess(argv, 0, "installed", "")
        if "--json" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    [
                        {
                            "name": "cognis-executor",
                            "status": state,
                            "user": service.getpass.getuser(),
                        }
                    ]
                ),
                "",
            )
        state = "started"
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(service, "_run", run)
    manager = service.MacOSServiceManager(brew="/opt/homebrew/bin/brew")
    assert manager.companion_operation("start")["code"] == "configuration_required"
    assert not any("start" in argv for argv in calls)
    result = manager.companion_operation("start", configured=True)
    assert result["state"] == "running"
    assert result["controller"] == "unknown"
    assert calls[-1][-1] == "--json"


def test_foreign_owner_and_unknown_status_never_mutate(monkeypatch):
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, "installed", ""),
            subprocess.CompletedProcess(
                [],
                0,
                json.dumps([{"name": "cognis-executor", "status": "started", "user": "root"}]),
                "",
            ),
        ]
    )
    monkeypatch.setattr(service, "_run", run)
    result = service.MacOSServiceManager(brew="/opt/homebrew/bin/brew").companion_operation("stop")
    assert result["code"] == "ownership_unknown"
    assert run.call_count == 2


def test_log_preview_withholds_all_free_form_content(tmp_path, monkeypatch):
    log = tmp_path / "service.log"
    log.write_text("2026-10-15 00:00:00 INFO token=SECRET https://private.invalid/chat\n" * 1000)
    manager = service.MacOSServiceManager(brew="/opt/homebrew/bin/brew")
    monkeypatch.setattr(manager, "_log_paths", lambda: (log, log))
    preview = manager._companion_log_summary()
    assert "SECRET" not in json.dumps(preview)
    assert "https:" not in json.dumps(preview)
    assert len(json.dumps(preview)) < 512
    link = tmp_path / "link.log"
    link.symlink_to(log)
    monkeypatch.setattr(manager, "_log_paths", lambda: (link, link))
    assert manager._companion_log_summary() == ["stderr: unavailable", "stdout: unavailable"]


def test_cli_json_does_not_print_configuration_or_probe(monkeypatch, capsys):
    monkeypatch.setattr(
        service,
        "companion_service",
        lambda action, **kwargs: {
            "schema": 1,
            "state": "stopped",
            "owned": True,
            "controller": "unknown",
            "ok": True,
            "code": "observed",
        },
    )
    monkeypatch.setattr(
        cli, "load_config", Mock(side_effect=AssertionError("must not read config"))
    )
    assert cli._lifecycle(cli._build_parser().parse_args(["status", "--json"])) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == 1


def test_timeout_is_unknown_and_not_retried(monkeypatch):
    monkeypatch.setattr(service.MacOSServiceManager, "_installed", lambda self: True)
    run = Mock(side_effect=subprocess.TimeoutExpired("brew", 30))
    monkeypatch.setattr(service, "_run", run)
    assert (
        service.MacOSServiceManager(brew="/opt/homebrew/bin/brew").companion_status()["state"]
        == "unknown"
    )
    assert run.call_count == 1


def test_cli_term_unwinds_subprocess_supervision_and_restores_handler(monkeypatch):
    handlers = []
    previous = signal.SIG_DFL

    def set_handler(sig, handler):
        assert sig == signal.SIGTERM
        handlers.append(handler)
        return previous

    def interrupted(action, **kwargs):
        handlers[0](signal.SIGTERM, None)

    monkeypatch.setattr(signal, "signal", set_handler)
    monkeypatch.setattr(service, "companion_service", interrupted)
    with pytest.raises(SystemExit) as result:
        cli._companion_service("status")
    assert result.value.code == 128 + signal.SIGTERM
    assert handlers[-1] is previous
