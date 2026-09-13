"""Unit tests for the LSP client."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest

from cognis.tools.executor.lsp.client import (
    MAX_RESPONSE_ITEMS,
    LSPClient,
    _normalize_lsp_result_list,
    file_uri,
    uri_to_path,
)
from cognis.tools.executor.lsp.types import DiagnosticFreshness, DiagnosticSeverity


class TestResultNormalization:
    """Server replies are untrusted and only a bounded prefix is inspected."""

    def test_inspects_bounded_prefix_only(self) -> None:
        class Tripwire(list):
            """A list that fails if iterated past the inspection cap."""

            def __iter__(self):  # type: ignore[no-untyped-def]
                for index, item in enumerate(super().__iter__()):
                    assert index <= MAX_RESPONSE_ITEMS, "walked past the intake cap"
                    yield item

        reply = Tripwire([{"i": n} for n in range(MAX_RESPONSE_ITEMS * 3)])
        items = _normalize_lsp_result_list(reply)
        assert len(items) == MAX_RESPONSE_ITEMS + 1

    def test_drops_non_dict_entries_and_wraps_scalars(self) -> None:
        assert _normalize_lsp_result_list([1, "x", None, {"a": 1}]) == [{"a": 1}]
        assert _normalize_lsp_result_list({"a": 1}) == [{"a": 1}]
        assert _normalize_lsp_result_list(None) == []


class TestFileUri:
    """Test file URI conversion functions."""

    def test_file_uri_absolute(self) -> None:
        uri = file_uri("/home/user/project/src/foo.py")
        assert uri.startswith("file:///")
        assert "foo.py" in uri

    def test_uri_to_path(self) -> None:
        path = uri_to_path("file:///home/user/project/src/foo.py")
        assert path == "/home/user/project/src/foo.py"

    def test_roundtrip(self) -> None:
        original = "/home/user/project/src/foo.py"
        assert uri_to_path(file_uri(original)) == original


class TestPublishDiagnostics:
    """Test the publishDiagnostics notification handler."""

    def test_handle_publish_diagnostics(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client._handle_publish_diagnostics(
            {
                "uri": "file:///src/foo.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 9, "character": 3},
                            "end": {"line": 9, "character": 10},
                        },
                        "severity": 1,
                        "code": "E001",
                        "source": "pyright",
                        "message": "undefined variable",
                    },
                    {
                        "range": {
                            "start": {"line": 15, "character": 0},
                            "end": {"line": 15, "character": 5},
                        },
                        "severity": 2,
                        "message": "unused import",
                    },
                ],
            }
        )
        diags = client.get_diagnostics("file:///src/foo.py")
        assert "file:///src/foo.py" in diags
        assert len(diags["file:///src/foo.py"]) == 2
        assert diags["file:///src/foo.py"][0].severity == DiagnosticSeverity.ERROR
        assert diags["file:///src/foo.py"][0].message == "undefined variable"
        assert diags["file:///src/foo.py"][1].severity == DiagnosticSeverity.WARNING

    def test_handle_empty_diagnostics(self) -> None:
        """Empty diagnostics should clear previous diagnostics for the URI."""
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client._handle_publish_diagnostics({"uri": "file:///src/foo.py", "diagnostics": []})
        # get_diagnostics with URI filter returns {} when list is empty
        diags = client.get_diagnostics("file:///src/foo.py")
        assert diags == {}
        # But internal state has the key with an empty list
        assert client._diagnostics["file:///src/foo.py"] == []

    def test_stale_versioned_diagnostics_do_not_replace_fresh_snapshot(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        uri = "file:///src/foo.py"
        client._mark_document_updated(uri, 2)

        client._handle_publish_diagnostics({"uri": uri, "version": 1, "diagnostics": []})

        assert client.get_diagnostic_snapshots(uri) == {}
        assert client.get_diagnostics(uri) == {}

    def test_matching_versioned_diagnostics_are_fresh(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        uri = "file:///src/foo.py"
        client._mark_document_updated(uri, 2)

        client._handle_publish_diagnostics({"uri": uri, "version": 2, "diagnostics": []})

        snapshot = client.get_diagnostic_snapshots(uri)[uri]
        assert snapshot.freshness is DiagnosticFreshness.FRESH
        assert snapshot.diagnostic_version == 2
        assert snapshot.document_version == 2

    def test_unversioned_diagnostics_after_update_are_marked_fresh_unversioned(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        uri = "file:///src/foo.py"
        client._mark_document_updated(uri, 3)

        client._handle_publish_diagnostics({"uri": uri, "diagnostics": []})

        snapshot = client.get_diagnostic_snapshots(uri)[uri]
        assert snapshot.freshness is DiagnosticFreshness.FRESH_UNVERSIONED

    def test_handle_malformed_diagnostic(self) -> None:
        """Malformed diagnostics should be skipped, not crash."""
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client._handle_publish_diagnostics(
            {
                "uri": "file:///src/foo.py",
                "diagnostics": [
                    "not a dict",
                    {"range": "invalid"},
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 1},
                        },
                        "message": "valid diagnostic",
                    },
                ],
            }
        )
        diags = client.get_diagnostics("file:///src/foo.py")
        # At least the valid diagnostic should be present
        assert len(diags["file:///src/foo.py"]) >= 1

    def test_diagnostics_signals_event(self) -> None:
        """Publishing diagnostics should signal the wait event."""
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        uri = "file:///src/foo.py"
        event = asyncio.Event()
        client._diag_events[uri] = event
        assert not event.is_set()

        client._handle_publish_diagnostics({"uri": uri, "diagnostics": []})
        assert event.is_set()


class TestGetDiagnostics:
    """Test diagnostic retrieval."""

    def test_get_all_diagnostics(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client._handle_publish_diagnostics(
            {
                "uri": "file:///a.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 1},
                        },
                        "message": "err a",
                    }
                ],
            }
        )
        client._handle_publish_diagnostics(
            {
                "uri": "file:///b.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 1},
                        },
                        "message": "err b",
                    }
                ],
            }
        )
        all_diags = client.get_diagnostics()
        assert len(all_diags) == 2
        assert "file:///a.py" in all_diags
        assert "file:///b.py" in all_diags

    def test_get_specific_uri(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client._handle_publish_diagnostics(
            {
                "uri": "file:///a.py",
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 1},
                        },
                        "message": "err",
                    }
                ],
            }
        )
        specific = client.get_diagnostics("file:///a.py")
        assert "file:///a.py" in specific

    def test_get_nonexistent_uri(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        result = client.get_diagnostics("file:///nonexistent.py")
        assert result == {}

    def test_has_pending_diagnostics(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")

        assert not client.has_pending_diagnostics("file:///a.py")
        client._pending_diagnostics.add("file:///a.py")
        assert client.has_pending_diagnostics("file:///a.py")


class TestCapabilities:
    """Negotiated capability tracking."""

    def test_unknown_before_handshake_is_attempted(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        assert client.capabilities is None
        assert client.supports("textDocument/definition")

    def test_static_capabilities_gate_methods(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client.capabilities = {
            "definitionProvider": True,
            "referencesProvider": {"workDoneProgress": False},
            "hoverProvider": False,
        }
        assert client.supports("textDocument/definition")
        assert client.supports("textDocument/references")
        assert not client.supports("textDocument/hover")
        assert not client.supports("textDocument/documentSymbol")
        assert not client.supports("callHierarchy/incomingCalls")
        # Methods without a capability key are not gated.
        assert client.supports("textDocument/didOpen")

    def test_supported_methods_reports_every_gated_method(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client.capabilities = {"definitionProvider": True}
        methods = client.supported_methods()
        assert methods["textDocument/definition"] is True
        assert methods["workspace/symbol"] is False
        assert "callHierarchy/outgoingCalls" in methods

    @pytest.mark.asyncio()
    async def test_dynamic_registration_extends_support(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client.capabilities = {}
        client._dispatch(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "client/registerCapability",
                "params": {
                    "registrations": [
                        {
                            "id": "reg-1",
                            "method": "textDocument/references",
                            "registerOptions": {
                                "documentSelector": [{"language": "python", "scheme": "file"}]
                            },
                        },
                        {"id": "reg-2", "method": "textDocument/prepareCallHierarchy"},
                        "malformed",
                        {"id": 3, "method": "textDocument/hover"},
                    ]
                },
            }
        )
        assert client.supports("textDocument/references", language_id="python")
        assert client.supports(
            "textDocument/references", uri="file:///src/a.py", language_id="python"
        )
        assert not client.supports("textDocument/references", language_id="go")
        assert not client.supports("textDocument/references", uri="untitled:x")
        # Alias: call hierarchy sub-methods are covered by the prepare registration.
        assert client.supports("callHierarchy/incomingCalls")
        assert not client.supports("textDocument/hover")

    def test_dynamic_registration_pattern_selector(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client.capabilities = {}
        client._handle_register_capability(
            {
                "registrations": [
                    {
                        "id": "reg-1",
                        "method": "textDocument/documentSymbol",
                        "registerOptions": {"documentSelector": [{"pattern": "**/*.svelte"}]},
                    }
                ]
            }
        )
        assert client.supports("textDocument/documentSymbol", uri="file:///src/App.svelte")
        assert not client.supports("textDocument/documentSymbol", uri="file:///src/app.ts")

    @pytest.mark.asyncio()
    async def test_unregister_removes_dynamic_support(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client.capabilities = {}
        client._handle_register_capability(
            {"registrations": [{"id": "reg-1", "method": "textDocument/hover"}]}
        )
        assert client.supports("textDocument/hover")
        client._dispatch(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "client/unregisterCapability",
                "params": {"unregisterations": [{"id": "reg-1"}]},
            }
        )
        assert not client.supports("textDocument/hover")

    def test_unregister_accepts_spec_spelling(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client.capabilities = {}
        client._handle_register_capability(
            {"registrations": [{"id": "reg-1", "method": "textDocument/hover"}]}
        )
        client._handle_unregister_capability({"unregistrations": [{"id": "reg-1"}]})
        assert not client.supports("textDocument/hover")

    @pytest.mark.asyncio()
    async def test_close_resets_negotiated_state(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client.capabilities = {"definitionProvider": True}
        client._handle_register_capability(
            {"registrations": [{"id": "reg-1", "method": "textDocument/hover"}]}
        )
        await client.close()
        assert client.capabilities is None
        assert client._dynamic_registrations == {}
        assert client.supports("textDocument/hover")  # unknown again, attempted


class TestInitialize:
    @pytest.mark.asyncio()
    async def test_initialize_announces_workspace_and_stores_capabilities(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///home/u/proj")
        sent: list[tuple[str, dict | None]] = []

        async def fake_request(method: str, params: dict | None, *, timeout: float = 30.0):
            sent.append((method, params))
            return {"capabilities": {"hoverProvider": True}, "serverInfo": {"name": "Fake"}}

        async def fake_notify(method: str, params: dict | None) -> None:
            sent.append((method, params))

        client._request = fake_request  # type: ignore[method-assign]
        client._notify = fake_notify  # type: ignore[method-assign]
        fake_process = MagicMock()
        fake_process.pid = 42

        async def fake_exec(*_: object, **__: object) -> object:
            return fake_process

        with_patch = pytest.MonkeyPatch()
        with_patch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        with_patch.setattr(client, "_reader_loop", _noop)
        with_patch.setattr(client, "_drain_stderr", _noop)
        try:
            await client.start()
        finally:
            with_patch.undo()

        init_method, init_params = sent[0]
        assert init_method == "initialize"
        assert init_params is not None
        assert init_params["rootUri"] == "file:///home/u/proj"
        assert init_params["workspaceFolders"] == [{"uri": "file:///home/u/proj", "name": "proj"}]
        text_caps = init_params["capabilities"]["textDocument"]
        assert text_caps["documentSymbol"]["hierarchicalDocumentSymbolSupport"] is True
        assert text_caps["definition"]["dynamicRegistration"] is True
        assert init_params["capabilities"]["workspace"]["symbol"]["dynamicRegistration"] is True
        assert sent[1] == ("initialized", {})
        assert client.capabilities == {"hoverProvider": True}
        assert client.server_name == "Fake"
        assert client.supports("textDocument/hover")
        assert not client.supports("textDocument/definition")


async def _noop() -> None:
    return None


class TestQueryPayloads:
    """Exact request payloads for query methods."""

    @pytest.mark.asyncio()
    async def test_type_definition_payload(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        seen: list[tuple[str, dict | None]] = []

        async def fake_request(method: str, params: dict | None, *, timeout: float = 30.0):
            seen.append((method, params))

        client._request = fake_request  # type: ignore[method-assign]
        result = await client.type_definition("/src/a.py", 3, 4)
        assert result == []
        assert seen == [
            (
                "textDocument/typeDefinition",
                {
                    "textDocument": {"uri": "file:///src/a.py"},
                    "position": {"line": 3, "character": 4},
                },
            )
        ]

    @pytest.mark.asyncio()
    async def test_scalar_and_malformed_results_are_dropped(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")

        async def fake_request(method: str, params: dict | None, *, timeout: float = 30.0):
            return ["junk", 3, {"uri": "file:///src/a.py", "range": {}}]

        client._request = fake_request  # type: ignore[method-assign]
        assert await client.definition("/src/a.py", 0, 0) == [
            {"uri": "file:///src/a.py", "range": {}}
        ]


class TestDispatch:
    """Test the message dispatch logic."""

    def test_configuration_response_returns_matching_sections(self) -> None:
        client = LSPClient(
            "pyright",
            "test-cmd",
            [],
            "file:///tmp",
            workspace_configuration={"python": {"analysis": {"diagnosticMode": "openFilesOnly"}}},
        )

        result = client._configuration_response(
            [{"section": "python"}, {"section": "missing"}, {"scopeUri": "file:///tmp/a.py"}]
        )

        assert result == [{"analysis": {"diagnosticMode": "openFilesOnly"}}, {}, {}]

    def test_configuration_response_ignores_malformed_items(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")

        assert client._configuration_response(["bad", {"section": "python"}]) == [{}, {}]
        assert client._configuration_response({"section": "python"}) == []

    def test_configuration_sections_extracts_log_context(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")

        assert client._configuration_sections(
            ["bad", {"section": "python"}, {"section": 123}, {"scopeUri": "file:///tmp/a.py"}]
        ) == [None, "python", None, None]
        assert client._configuration_sections({"section": "python"}) == []

    @pytest.mark.asyncio()
    async def test_dispatch_logs_workspace_configuration_context(self, caplog) -> None:
        caplog.set_level(logging.INFO, logger="cognis.tools.executor.lsp.client")
        client = LSPClient(
            "pyright",
            "test-cmd",
            [],
            "file:///tmp",
            workspace_configuration={"python": {"analysis": {}}},
        )

        client._dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "workspace/configuration",
                "params": {"items": [{"section": "python"}]},
            }
        )
        await asyncio.sleep(0)

        assert "server_id=pyright" in caplog.text
        assert "requested_sections=['python']" in caplog.text

    @pytest.mark.asyncio()
    async def test_wait_for_diagnostics_tracks_pending_state(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        uri = "file:///src/foo.py"

        task = asyncio.create_task(client.wait_for_diagnostics(uri, timeout_ms=1000))
        await asyncio.sleep(0)
        assert client.has_pending_diagnostics(uri)

        client._handle_publish_diagnostics({"uri": uri, "diagnostics": []})
        result = await task

        assert not client.has_pending_diagnostics(uri)
        assert result.status is DiagnosticFreshness.FRESH_UNVERSIONED

    @pytest.mark.asyncio()
    async def test_wait_for_diagnostics_times_out_without_stale_cache(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        uri = "file:///src/foo.py"
        client._mark_document_updated(uri, 2)
        client._handle_publish_diagnostics({"uri": uri, "version": 1, "diagnostics": []})

        result = await client.wait_for_diagnostics(uri, target_version=2, timeout_ms=1)

        assert result.status is DiagnosticFreshness.TIMEOUT
        assert result.snapshot is None

    @pytest.mark.asyncio()
    async def test_wait_for_diagnostics_debounces_first_fresh_batch(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        uri = "file:///src/foo.py"
        client._mark_document_updated(uri, 1)

        task = asyncio.create_task(
            client.wait_for_diagnostics(uri, target_version=1, timeout_ms=1000, debounce_ms=50)
        )
        await asyncio.sleep(0)
        client._handle_publish_diagnostics({"uri": uri, "version": 1, "diagnostics": []})
        await asyncio.sleep(0.01)
        client._handle_publish_diagnostics(
            {
                "uri": uri,
                "version": 1,
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 1},
                        },
                        "severity": 1,
                        "message": "late error",
                    }
                ],
            }
        )

        result = await task

        assert result.status is DiagnosticFreshness.FRESH
        assert result.error_count == 1

    @pytest.mark.asyncio()
    async def test_wait_for_diagnostics_debounces_preexisting_fresh_snapshot(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        uri = "file:///src/foo.py"
        client._mark_document_updated(uri, 1)
        client._handle_publish_diagnostics({"uri": uri, "version": 1, "diagnostics": []})

        task = asyncio.create_task(
            client.wait_for_diagnostics(uri, target_version=1, timeout_ms=1000, debounce_ms=50)
        )
        await asyncio.sleep(0.01)
        client._handle_publish_diagnostics(
            {
                "uri": uri,
                "version": 1,
                "diagnostics": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 1},
                        },
                        "severity": 1,
                        "message": "late preexisting error",
                    }
                ],
            }
        )

        result = await task

        assert result.status is DiagnosticFreshness.FRESH
        assert result.error_count == 1

    @pytest.mark.asyncio()
    async def test_wait_for_diagnostics_continues_after_stale_batch(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        uri = "file:///src/foo.py"
        client._mark_document_updated(uri, 2)

        task = asyncio.create_task(
            client.wait_for_diagnostics(uri, target_version=2, timeout_ms=1000, debounce_ms=10)
        )
        await asyncio.sleep(0)
        client._handle_publish_diagnostics({"uri": uri, "version": 1, "diagnostics": []})
        await asyncio.sleep(0.03)
        client._handle_publish_diagnostics({"uri": uri, "version": 2, "diagnostics": []})

        result = await task

        assert result.status is DiagnosticFreshness.FRESH
        assert result.target_version == 2
        assert result.snapshot is not None
        assert result.snapshot.diagnostic_version == 2

    @pytest.mark.asyncio()
    async def test_dispatch_response(self) -> None:
        """Responses should resolve pending futures."""
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict] = loop.create_future()
        client._pending[1] = future
        client._dispatch({"id": 1, "result": {"capabilities": {}}})
        assert future.done()
        assert future.result() == {"id": 1, "result": {"capabilities": {}}}

    def test_dispatch_ignores_unknown_notification(self) -> None:
        """Unknown notifications should not crash."""
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client._dispatch({"method": "unknown/notification", "params": {}})
        # Should not raise

    def test_dispatch_log_message(self) -> None:
        """window/logMessage should not crash."""
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client._dispatch({"method": "window/logMessage", "params": {"type": 3, "message": "info"}})

    def test_is_alive_before_start(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        assert not client.is_alive

    def test_is_alive_after_close(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client._closed = True
        assert not client.is_alive


class TestWorkDoneProgress:
    """``$/progress`` tracking used for the cold-start query wait."""

    def _progress(self, client: LSPClient, token: str | int, kind: str) -> None:
        client._dispatch(
            {"method": "$/progress", "params": {"token": token, "value": {"kind": kind}}}
        )

    @pytest.mark.asyncio()
    async def test_begin_end_toggles_idle(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        assert not client.progress_active
        self._progress(client, "load", "begin")
        assert client.progress_active
        self._progress(client, "load", "report")
        assert client.progress_active
        self._progress(client, 2, "begin")
        self._progress(client, "load", "end")
        assert client.progress_active
        self._progress(client, 2, "end")
        assert not client.progress_active

    @pytest.mark.asyncio()
    async def test_create_request_is_answered(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        sent: list[dict] = []

        async def fake_send(message: dict) -> None:
            sent.append(message)

        client._send = fake_send  # type: ignore[method-assign]
        client._dispatch(
            {"id": 9, "method": "window/workDoneProgress/create", "params": {"token": "t"}}
        )
        await asyncio.sleep(0)
        assert sent == [{"jsonrpc": "2.0", "id": 9, "result": None}]
        assert not client.progress_active

    @pytest.mark.asyncio()
    async def test_wait_returns_after_grace_without_progress(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        assert await client.wait_for_progress_idle(grace_s=0.01, timeout_s=1.0) is True

    @pytest.mark.asyncio()
    async def test_wait_blocks_until_end(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        self._progress(client, "load", "begin")

        async def finish() -> None:
            await asyncio.sleep(0.02)
            self._progress(client, "load", "end")

        task = asyncio.create_task(finish())
        assert await client.wait_for_progress_idle(grace_s=0.01, timeout_s=1.0) is True
        await task

    @pytest.mark.asyncio()
    async def test_wait_catches_progress_that_begins_during_grace(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")

        async def late_begin() -> None:
            await asyncio.sleep(0.01)
            self._progress(client, "load", "begin")

        task = asyncio.create_task(late_begin())
        assert await client.wait_for_progress_idle(grace_s=0.2, timeout_s=0.05) is False
        await task
        assert client.progress_active

    @pytest.mark.asyncio()
    async def test_malformed_progress_is_ignored(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        client._dispatch({"method": "$/progress", "params": "nope"})
        client._dispatch(
            {"method": "$/progress", "params": {"token": None, "value": {"kind": "begin"}}}
        )
        client._dispatch({"method": "$/progress", "params": {"token": "x", "value": "begin"}})
        assert not client.progress_active

    @pytest.mark.asyncio()
    async def test_close_resets_progress(self) -> None:
        client = LSPClient("test", "test-cmd", [], "file:///tmp")
        self._progress(client, "load", "begin")
        await client.close()
        assert not client.progress_active
        assert await client.wait_for_progress_idle(grace_s=0.01, timeout_s=0.1) is True
