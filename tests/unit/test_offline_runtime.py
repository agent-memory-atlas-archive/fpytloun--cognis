from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

import cognis.knowledgebase.chunking as chunking
import cognis.offline_runtime as offline_runtime
from cognis.providers.llm.litellm import LiteLLMProvider


def _fresh_configure(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for name in (
        "TIKTOKEN_CACHE_DIR",
        "CUSTOM_TIKTOKEN_CACHE_DIR",
        "LITELLM_LOCAL_MODEL_COST_MAP",
        "HF_HUB_OFFLINE",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(offline_runtime, "_configured", False)
    offline_runtime.configure_offline_runtime()


def test_configure_points_tiktoken_at_bundled_litellm_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _fresh_configure(monkeypatch)

    bundled = offline_runtime.bundled_tiktoken_dir()
    assert bundled is not None
    import os

    assert os.environ["TIKTOKEN_CACHE_DIR"] == str(bundled)
    assert os.environ["CUSTOM_TIKTOKEN_CACHE_DIR"] == str(bundled)
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    for name in offline_runtime.REQUIRED_TIKTOKEN_ENCODINGS:
        assert (bundled / offline_runtime.tiktoken_cache_key(name)).is_file(), name


def test_required_encodings_load_strictly_from_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    _fresh_configure(monkeypatch)

    status = offline_runtime.preload_bundled_encodings(strict=True)

    assert status["missing"] == {}
    assert set(status["loaded"]) == set(offline_runtime.REQUIRED_TIKTOKEN_ENCODINGS)


def test_unbundled_tiktoken_asset_fails_fast_without_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fresh_configure(monkeypatch, TIKTOKEN_CACHE_DIR=str(tmp_path))

    from tiktoken_ext import openai_public

    started = time.monotonic()
    with pytest.raises(offline_runtime.BundledAssetUnavailable):
        # Call the constructor directly to bypass tiktoken's in-process registry.
        openai_public.o200k_base()
    assert time.monotonic() - started < 5


def test_strict_preload_raises_when_bundle_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fresh_configure(monkeypatch, TIKTOKEN_CACHE_DIR=str(tmp_path))
    import tiktoken

    def _missing(name: str) -> object:
        from tiktoken_ext import openai_public

        return getattr(openai_public, name)()

    monkeypatch.setattr(tiktoken, "get_encoding", _missing)

    with pytest.raises(offline_runtime.BundledAssetUnavailable):
        offline_runtime.preload_bundled_encodings(strict=True)


def test_count_tokens_char_fallback_is_logged_and_rate_limited(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import tiktoken

    def _unavailable(_: str) -> object:
        raise offline_runtime.BundledAssetUnavailable("not bundled")

    monkeypatch.setattr(tiktoken, "get_encoding", _unavailable)
    provider = LiteLLMProvider(object())  # type: ignore[arg-type]
    caplog.set_level(logging.WARNING, logger="cognis.providers.llm.litellm")

    assert provider.count_tokens("hello world!", "some-unknown-model") == 3
    assert provider.count_tokens("hello world!", "some-unknown-model") == 3

    warnings = [
        record
        for record in caplog.records
        if record.message == "llm: token counting fell back to a less accurate estimator"
    ]
    assert len(warnings) == 1
    data = warnings[0].extra_data  # type: ignore[attr-defined]
    assert data["failed_backend"] == "tiktoken_o200k_base"
    assert data["fallback_backend"] == "chars_div_4"
    assert data["error_type"] == "BundledAssetUnavailable"
    assert provider.token_estimator_identity("some-unknown-model").endswith(":chars_div_4:v1")


def test_count_tokens_primary_backend_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        "cognis.providers.llm.litellm.litellm.token_counter",
        lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    provider = LiteLLMProvider(object())  # type: ignore[arg-type]
    caplog.set_level(logging.WARNING, logger="cognis.providers.llm.litellm")

    assert provider.count_tokens("hello world", "claude-sonnet-4-5") > 0

    warnings = [
        record.extra_data  # type: ignore[attr-defined]
        for record in caplog.records
        if record.message == "llm: token counting fell back to a less accurate estimator"
    ]
    assert warnings and warnings[0]["failed_backend"] == "litellm_native"
    assert warnings[0]["fallback_backend"] == "tiktoken_o200k_base"


def test_unmapped_openai_model_uses_o200k_without_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = LiteLLMProvider(object())  # type: ignore[arg-type]
    caplog.set_level(logging.WARNING, logger="cognis.providers.llm.litellm")

    assert provider.count_tokens("hello world", "openai/gpt-oss-120b") > 0

    assert not [r for r in caplog.records if "token counting fell back" in r.message]


def test_knowledgebase_chunk_count_fallback_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import tiktoken

    def _unavailable(_: str) -> object:
        raise offline_runtime.BundledAssetUnavailable("not bundled")

    monkeypatch.setattr(tiktoken, "get_encoding", _unavailable)
    monkeypatch.setattr(chunking, "_fallback_warn_state", {"last": None, "suppressed": 0})
    caplog.set_level(logging.WARNING, logger="cognis.knowledgebase.chunking")

    assert chunking._default_token_count("abcdefgh") == 2

    assert [
        r
        for r in caplog.records
        if r.message == "knowledgebase: token counting fell back to character estimate"
    ]
