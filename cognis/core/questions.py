"""Generic question provenance and agent mediation contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from cognis.models.task import TaskModel
from cognis.models.workflow import WorkflowState

AGENT_QUESTION = "agent_question"
QUESTION_GUIDANCE = (
    "Answer with answer_question when the context, task instructions, or the user's "
    "preferences give you a reasonable basis. Otherwise use forward_question to ask "
    "the user rather than guess. A scheduled/API task's delivery destination alone "
    "does not give you decision authority."
)


def user_visible_workflow_state(state: WorkflowState | None) -> WorkflowState | None:
    """Keep execution status while hiding an agent-only input request."""
    if state is not None and state.pending_pause_type == AGENT_QUESTION:
        return state.model_copy(update={"pending_pause_type": None, "pending_pause_payload": None})
    return state


class QuestionTaskResumer(Protocol):
    """Task admission interface needed after a recovered question is answered."""

    def has_active_run(self, task_id: str) -> bool: ...

    async def resume_task(self, task_id: str) -> TaskModel: ...


class QuestionOrigin(BaseModel):
    """Controller-authored provenance, not a caller-selected routing destination."""

    conversation_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    task_id: str | None = None
    task_title: str | None = None
    task_attempt_number: int | None = Field(default=None, ge=1)
    step_run_id: str | None = None
    step_name: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    source_session_id: str | None = None


class QuestionRouting(BaseModel):
    """Pinned respondent and independent user delivery destination."""

    version: Literal[1] = 1
    respondent_conversation_id: str = Field(min_length=1)
    user_conversation_id: str = Field(min_length=1)


async def join_until_boundary[T](
    child: asyncio.Task[T],
    wait_for_boundary: Callable[[int | None], Awaitable[str]] | None,
    generation: int | None,
) -> tuple[T | None, str | None]:
    """Yield a joined child without cancelling it; parent cancellation still owns it."""
    if wait_for_boundary is None:
        return await child, None
    boundary = asyncio.ensure_future(wait_for_boundary(generation))
    try:
        done, _ = await asyncio.wait({child, boundary}, return_when=asyncio.FIRST_COMPLETED)
        if child in done or child.done():
            return await child, None
        return None, await boundary
    except BaseException:
        child.cancel()
        await asyncio.gather(child, return_exceptions=True)
        raise
    finally:
        boundary.cancel()
        await asyncio.gather(boundary, return_exceptions=True)
