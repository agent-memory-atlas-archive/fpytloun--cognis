"""Constructed synthetic workflows through the real workflow/native boundary."""

from copy import deepcopy
from pathlib import Path

import pytest

from cognis import json_codec as json
from cognis.core.workflow_output_contract import resolve_output_ownership
from cognis.models.workflow import Workflow
from tests.unit.test_routed_output_engine import (
    test_routed_two_primary_handoff_keeps_collector_internal_and_final_strict as run_snapshot,
)

SNAPSHOTS = json.loads(
    (Path(__file__).parents[1] / "fixtures/workflows/synthetic-output-ownership.json").read_text()
)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["handoff", "silent_completion"])
@pytest.mark.parametrize("outcome", ["success", "rejected"])
async def test_synthetic_workflow_engine(tmp_path, name, outcome, caplog):
    caplog.set_level("INFO", logger="cognis.core.agent_loop")
    await run_snapshot(tmp_path, outcome, snapshot=SNAPSHOTS[name])
    traces = [
        record.output_contract
        for record in caplog.records
        if record.message == "Workflow output contract validation"
    ]
    assert {(trace["step_index"], trace["phase"]) for trace in traces} == {
        (0, "preflight"),
        (0, "execution"),
        (1, "preflight"),
        (1, "execution"),
    }
    for trace in traces:
        assert set(trace) == {
            "task_id",
            "step_run_id",
            "agent_id",
            "step_index",
            "task_output",
            "producer_step",
            "reason",
            "phase",
        }
        assert trace["producer_step"] == "execute"
        assert trace["task_output"] is (trace["step_index"] == 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("outputs", [{}, {"final_content": "not canonical", "synthetic": True}])
async def test_terminal_outputs_do_not_replace_canonical_pulse(tmp_path, outputs):
    snapshot = deepcopy(SNAPSHOTS["silent_completion"])
    snapshot["workflow"]["steps"][-1]["complete"]["outputs"] = outputs
    await run_snapshot(tmp_path, "success", snapshot=snapshot)


@pytest.mark.parametrize(
    "variant",
    [
        "content",
        "empty_content",
        "notification",
        "failed",
        "early_complete",
        "condition",
        "gate",
        "tool_call",
        "unknown_position",
        "cycle",
        "branch",
        "on_error",
        "when",
    ],
)
def test_unproven_terminal_and_graph_variants_fail_closed(variant):
    spec = deepcopy(SNAPSHOTS["silent_completion"]["workflow"])
    spec["name"] = spec["workflow_id"]
    workflow = Workflow.model_validate(spec)
    steps = workflow.steps
    index = 0
    if variant in {"content", "empty_content"}:
        steps[-1].complete.content = "" if variant == "empty_content" else "Different output"
    elif variant == "notification":
        from cognis.models.workflow import StepCompletionNotification

        steps[-1].complete.notification = StepCompletionNotification(
            mode="silent", reason="Synthetic"
        )
    elif variant == "failed":
        steps[-1].complete.status = "failed"
    elif variant == "early_complete":
        steps.insert(1, steps.pop())
    elif variant in {"condition", "gate", "tool_call"}:
        steps[-1].type = variant
    elif variant == "unknown_position":
        index = 99
    elif variant == "cycle":
        steps[1].next = steps[0].name
    elif variant == "branch":
        steps[0].next = steps[-1].name
    elif variant == "on_error":
        steps[0].on_error = steps[-1].name
    elif variant == "when":
        steps[-1].when = "metadata.ready"
    assert resolve_output_ownership(steps, steps[0], index).task_output is None
