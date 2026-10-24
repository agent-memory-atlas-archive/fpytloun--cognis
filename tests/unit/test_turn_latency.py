from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from cognis.core import turn_latency


def test_phase_metrics_have_fixed_labels_and_are_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    histogram = Mock()
    monkeypatch.setattr(turn_latency, "LATENCY", histogram)
    turn_latency.observe("request_prepare", 0.25)
    histogram.labels.assert_called_once_with(phase="request_prepare", outcome="success")
    histogram.labels.return_value.observe.assert_called_once_with(0.25)
    histogram.labels.reset_mock()
    turn_latency.observe("request_prepare", 1, "unbounded-error-message")
    histogram.labels.assert_not_called()
    histogram.labels.side_effect = RuntimeError("metrics unavailable")
    turn_latency.observe("request_prepare", 1)


@pytest.mark.parametrize("naive_created", [False, True])
@pytest.mark.parametrize("naive_claimed", [False, True])
def test_first_claim_supports_both_database_timestamp_forms(
    monkeypatch: pytest.MonkeyPatch, naive_created: bool, naive_claimed: bool
) -> None:
    observer = Mock()
    monkeypatch.setattr(turn_latency, "observe", observer)
    created = datetime(2026, 1, 1, tzinfo=UTC)
    claimed = created + timedelta(seconds=2)
    if naive_created:
        created = created.replace(tzinfo=None)
    if naive_claimed:
        claimed = claimed.replace(tzinfo=None)
    turn_latency.observe_first_claim(created, claimed, 1)
    observer.assert_called_once_with("first_claim_wait", 2)
    observer.reset_mock()
    turn_latency.observe_first_claim(created, claimed, 2)
    observer.assert_not_called()
    observer.side_effect = RuntimeError("metrics unavailable")
    turn_latency.observe_first_claim(created, claimed, 1)


@pytest.mark.parametrize(
    ("exception", "outcome"),
    [(None, "success"), (ValueError("failure"), "error"), (asyncio.CancelledError(), "cancelled")],
)
def test_phase_measurement_preserves_errors_and_cancellation(
    monkeypatch: pytest.MonkeyPatch, exception: BaseException | None, outcome: str
) -> None:
    observer = Mock()
    monkeypatch.setattr(turn_latency, "observe", observer)
    monkeypatch.setattr(turn_latency, "perf_counter", Mock(side_effect=[1.0, 1.25]))
    if exception is None:
        with turn_latency.measure("submit_total"):
            pass
    else:
        with pytest.raises(type(exception)) as raised, turn_latency.measure("submit_total"):
            raise exception
        assert raised.value is exception
    observer.assert_called_once_with("submit_total", 0.25, outcome)
