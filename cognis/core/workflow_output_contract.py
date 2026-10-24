"""Workflow-owned selection of the task output producer."""

from collections.abc import Sequence
from dataclasses import dataclass

from cognis.models.workflow import StepDefinition


def required_output_producers(steps: Sequence[StepDefinition]) -> list[StepDefinition]:
    """Return required run producers in workflow order."""
    return [step for step in steps if step.type == "run" and step.require_deliverable]


def step_is_task_output(
    steps: Sequence[StepDefinition] | None, step: StepDefinition, index: int
) -> bool | None:
    """Return the effective scope; unknown ownership remains strict."""
    return resolve_output_ownership(steps, step, index).task_output


@dataclass(frozen=True)
class OutputOwnership:
    """Content-free ownership decision for diagnostic metadata."""

    task_output: bool | None
    producer_step: str | None
    reason: str


def resolve_output_ownership(
    steps: Sequence[StepDefinition] | None, step: StepDefinition, index: int
) -> OutputOwnership:
    """Prove an intermediate output only in an unconditional linear workflow.

    Unknown graphs retain strict task-output validation. This is derived anew
    from the pinned workflow for each attempt, never from replayed tool output.
    An explicit outcome ``continue`` has the same next index as the normal
    success path; it cannot change which required run owns the final output.
    """
    if (
        not steps
        or not 0 <= index < len(steps)
        or steps[index] != step
        or len({item.name for item in steps}) != len(steps)
    ):
        return OutputOwnership(None, None, "unknown_position")
    for position, item in enumerate(steps):
        if (
            item.when
            or item.on_reject
            or item.on_error
            or item.on_skip
            or item.next
            or any(route.action != "continue" for route in item.outcome_routes)
        ):
            return OutputOwnership(None, None, "nonlinear_route")
        if item.type == "run":
            continue
        terminal = item.complete
        if not (
            position == len(steps) - 1
            and item.type == "complete"
            and terminal is not None
            and terminal.status == "completed"
            and terminal.content is None
            and terminal.notification is None
            and terminal.delivery_mode_override == "silent"
            and not item.outcome_routes
        ):
            return OutputOwnership(None, None, "unproven_nonproducer")
        # Complete.outputs stays in StepOutput.outputs. Task result/delivery
        # selects the last required run's artifact before any fallback content.
    producers = required_output_producers(steps)
    if not producers or step not in producers:
        return OutputOwnership(None, None, "not_required_producer")
    return OutputOwnership(step == producers[-1], producers[-1].name, "linear_required_runs")
