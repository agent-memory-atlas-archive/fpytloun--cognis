from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cognis.core.shell_target_evidence import shell_target_evidence


def row(**updates):
    return {
        "shell_id": "shell_monitor",
        "user_email": "owner@example.com",
        "conversation_id": "conversation_monitor",
        "executor_id": "executor_monitor",
        "session_id": "session_before_compaction",
        "call_id": "start_monitor",
        "command": "kubectl port-forward service/alertmanager 18938:9093",
        "description": "Release verification tunnel",
        "status": "running",
        "output_tail": "must not be exposed",
        **updates,
    }


async def evidence(executor):
    return await shell_target_evidence(
        executor,
        shell_id="shell_monitor",
        user_id="owner@example.com",
        session_id="session_after_compaction",
        conversation_id="conversation_monitor",
    )


@pytest.mark.asyncio
async def test_target_survives_rotation_and_omits_unrelated_shells_and_output():
    executor = SimpleNamespace(
        executor_id="executor_monitor",
        background_shell_status=AsyncMock(
            return_value={
                "shells": [
                    row(),
                    row(shell_id="shell_unrelated", command="private unrelated command"),
                ]
            }
        ),
    )
    result = await evidence(executor)
    assert result["coverage"] == "complete"
    assert result["target"]["session_id"] == "session_before_compaction"
    assert result["target"]["description"] == "Release verification tunnel"
    assert "output_tail" not in result["target"]
    assert "private unrelated" not in str(result)
    executor.background_shell_status.assert_awaited_once_with(include_completed=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["user_email", "conversation_id", "executor_id"])
async def test_cross_owner_target_does_not_leak(field):
    executor = SimpleNamespace(
        executor_id="executor_monitor",
        background_shell_status=AsyncMock(return_value={"shells": [row(**{field: "other"})]}),
    )
    result = await evidence(executor)
    assert result["reason"] == "not_found_or_not_owned"
    assert "target" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [row(), row()]])
async def test_missing_or_duplicate_target_is_unknown(rows):
    executor = SimpleNamespace(
        executor_id="executor_monitor",
        background_shell_status=AsyncMock(return_value={"shells": rows}),
    )
    assert (await evidence(executor))["coverage"] == "unknown"


@pytest.mark.asyncio
async def test_disconnected_executor_has_no_invented_provenance():
    executor = SimpleNamespace(
        executor_id="executor_monitor",
        background_shell_status=AsyncMock(side_effect=TimeoutError),
    )
    assert (await evidence(executor))["reason"] == "lookup_unavailable"


@pytest.mark.asyncio
async def test_completed_target_is_not_presented_as_running():
    executor = SimpleNamespace(
        executor_id="executor_monitor",
        background_shell_status=AsyncMock(
            return_value={
                "shells": [
                    row(status="completed", done=True, exit_code=0),
                ]
            }
        ),
    )
    assert (await evidence(executor))["target"]["done"] is True


@pytest.mark.asyncio
async def test_redacts_full_command_before_truncation_and_refreshes_status():
    executor = SimpleNamespace(
        executor_id="executor_monitor",
        background_shell_status=AsyncMock(
            side_effect=[
                {"shells": [row(command="x" * 1400 + " API_TOKEN=private-value")]},
                {"shells": [row(status="completed", done=True)]},
            ]
        ),
    )
    first = await evidence(executor)
    assert "private-value" not in str(first)
    assert "REDACTED" in first["target"]["command"]
    second = await evidence(executor)
    assert second["target"]["done"] is True
    assert executor.background_shell_status.await_count == 2


@pytest.mark.asyncio
async def test_incomplete_target_does_not_claim_complete_coverage():
    executor = SimpleNamespace(
        executor_id="executor_monitor",
        background_shell_status=AsyncMock(return_value={"shells": [row(command=None)]}),
    )
    result = await evidence(executor)
    assert result["coverage"] == "partial"
    assert "command" in result["missing_fields"]
