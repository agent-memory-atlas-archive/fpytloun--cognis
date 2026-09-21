from types import SimpleNamespace
from unittest.mock import AsyncMock, create_autospec

import pytest

from cognis.core.canonical_history import CanonicalHistoryUnavailable
from cognis.core.session import SessionManager
from cognis.core.workflow_engine import WorkflowEngine


@pytest.mark.asyncio
async def test_full_input_history_failure_stops_and_marks_target_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = object.__new__(WorkflowEngine)
    engine._providers = SimpleNamespace()
    engine._session_cache = SimpleNamespace()
    engine._session_manager = create_autospec(SessionManager, instance=True)
    monkeypatch.setattr(
        "cognis.core.workflow_engine.fork_session_events",
        AsyncMock(side_effect=CanonicalHistoryUnavailable("history unavailable")),
    )
    with pytest.raises(CanonicalHistoryUnavailable):
        await engine._fork_source_events(
            "source",
            SimpleNamespace(session_id="target-step"),
            SimpleNamespace(step_outputs={"source": {"session_id": "source-step"}}),
        )
    engine._session_manager.mark_failed.assert_awaited_once_with(
        "target-step",
        result_summary="Required workflow context could not be copied",
    )
