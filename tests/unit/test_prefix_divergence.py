"""Tests for content-free provider prompt-prefix divergence diagnostics."""

from __future__ import annotations

import logging

import pytest

from cognis.providers.llm.prefix_divergence import (
    PromptPrefixTracker,
    first_difference_path,
    item_kind,
)


def _observe(tracker: PromptPrefixTracker, items: list, *, head: object = "tools-a", model="m"):
    return tracker.observe(
        session_id="sess_1",
        channel="responses_input",
        provider_id="codex",
        model=model,
        llm_request_id="llmr_1",
        head=head,
        items=items,
    )


def test_append_only_requests_do_not_report_divergence() -> None:
    tracker = PromptPrefixTracker()
    first = [{"role": "user", "content": "a"}]
    assert _observe(tracker, first) is None
    assert _observe(tracker, [*first, {"role": "assistant", "content": "b"}]) is None


def test_rewritten_history_reports_first_changed_item_without_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tracker = PromptPrefixTracker()
    secret = "super secret prompt text"
    _observe(
        tracker,
        [
            {"role": "system", "content": "env"},
            {"role": "developer", "content": secret},
            {"role": "user", "content": "q1"},
        ],
    )
    with caplog.at_level(logging.INFO, logger="cognis.providers.llm.prefix_divergence"):
        result = _observe(
            tracker,
            [
                {"role": "system", "content": "env"},
                {"role": "user", "content": "q1"},
                {"role": "user", "content": "q2"},
            ],
        )

    assert result is not None
    assert result["divergence_index"] == 1
    assert result["previous_item_kind"] == "developer"
    assert result["item_kind"] == "user"
    assert result["item_found_in_previous_at"] == [2]
    assert result["difference_path"] == ".content<str@0 len 24->2>"
    assert secret not in caplog.text
    assert "q1" not in caplog.text


def test_truncated_request_reports_divergence_at_new_end() -> None:
    tracker = PromptPrefixTracker()
    _observe(tracker, [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
    result = _observe(tracker, [{"role": "user", "content": "a"}])
    assert result is not None
    assert result["divergence_index"] == 1
    assert result["item_kind"] is None


def test_other_model_or_tool_head_does_not_replace_main_baseline() -> None:
    tracker = PromptPrefixTracker()
    main = [{"role": "user", "content": "a"}]
    _observe(tracker, main)
    assert _observe(tracker, [{"role": "user", "content": "aux"}], head="tools-b") is None
    assert _observe(tracker, [{"role": "user", "content": "aux"}], model="other") is None
    assert _observe(tracker, [*main, {"role": "assistant", "content": "b"}]) is None


def test_missing_session_is_ignored() -> None:
    tracker = PromptPrefixTracker()
    assert (
        tracker.observe(
            session_id=None,
            channel="messages",
            provider_id="p",
            model="m",
            llm_request_id=None,
            head=None,
            items=[{"role": "user", "content": "a"}],
        )
        is None
    )


def test_tracker_bounds_tracked_sessions() -> None:
    tracker = PromptPrefixTracker(max_tracked=2)
    for session in ("s1", "s2", "s3"):
        tracker.observe(
            session_id=session,
            channel="messages",
            provider_id="p",
            model="m",
            llm_request_id=None,
            head=None,
            items=[{"role": "user", "content": session}],
        )
    assert len(tracker._snapshots) == 2


def test_content_bearing_keys_are_redacted_in_structured_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tracker = PromptPrefixTracker()
    secret_key = "alice@example.com"
    _observe(tracker, [{"role": "assistant", "_envelope": {"input": {"to": "x"}}}])
    with caplog.at_level(logging.INFO, logger="cognis.providers.llm.prefix_divergence"):
        result = _observe(
            tracker,
            [{"role": "assistant", "_envelope": {"input": {"to": "x", secret_key: "y"}}}],
        )
    assert result is not None
    assert result["difference_path"] == "._envelope.input.<key><added>"
    record = next(r for r in caplog.records if r.getMessage() == "LLM prompt prefix diverged")
    assert secret_key not in repr(record.__dict__["extra_data"])


@pytest.mark.parametrize("secret_key", ["_alice@example.com", "_secret_name"])
def test_nested_underscore_keys_are_redacted(secret_key: str) -> None:
    tracker = PromptPrefixTracker()
    _observe(tracker, [{"role": "assistant", "_envelope": {"input": {}}}])
    result = _observe(tracker, [{"role": "assistant", "_envelope": {"input": {secret_key: 1}}}])
    assert result is not None
    assert result["difference_path"] == "._envelope.input.<key><added>"
    assert secret_key not in repr(result)


def test_unsafe_top_level_underscore_key_is_redacted() -> None:
    tracker = PromptPrefixTracker()
    _observe(tracker, [{"role": "user"}])
    result = _observe(tracker, [{"role": "user", "_alice@example.com": 1}])
    assert result is not None
    assert result["difference_path"] == ".<key><added>"


def test_item_kind_ignores_arbitrary_type_and_role_values() -> None:
    tracker = PromptPrefixTracker()
    _observe(tracker, [{"role": "secret role", "type": "Secret Type!", "content": "a"}])
    result = _observe(tracker, [{"role": "secret role", "type": "Secret Type!", "content": "b"}])
    assert result is not None
    assert result["item_kind"] == "other"


@pytest.mark.parametrize("role", [None, 1, ["user"], {"role": "user"}])
def test_item_kind_ignores_non_string_roles(role: object) -> None:
    assert item_kind({"role": role}) == "dict"


def test_observe_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    tracker = PromptPrefixTracker()

    def explode(**_: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(tracker, "_observe", explode)
    assert _observe(tracker, [{"role": "user", "content": "a"}]) is None


def test_provider_is_part_of_the_baseline_key() -> None:
    tracker = PromptPrefixTracker()
    _observe(tracker, [{"role": "user", "content": "a"}])
    other = tracker.observe(
        session_id="sess_1",
        channel="responses_input",
        provider_id="other",
        model="m",
        llm_request_id=None,
        head="tools-a",
        items=[{"role": "user", "content": "different"}],
    )
    assert other is None


def test_first_difference_path_is_structural() -> None:
    before = {"type": "reasoning", "encrypted_content": "abc", "summary": [{"text": "x"}]}
    after = {"type": "reasoning", "summary": [{"text": "x"}]}
    assert first_difference_path(before, after) == ".encrypted_content<removed>"
    assert first_difference_path([1, 2], [1, 2, 3]) == "<len 2->3>"
