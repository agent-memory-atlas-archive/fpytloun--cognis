"""Declarative agent hook contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cognis.models.workflow import ToolCallStepConfig


class HookDefinition(BaseModel):
    """Reusable trigger, condition, and action without transport-specific policy."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    trigger: Literal[
        "first_user_message",
        "user_message",
        "before_turn",
        "before_model_cycle",
        "turn_completed",
        "conversation_idle",
    ]
    condition: str | None = Field(default=None, max_length=8000)
    idle_seconds: int = Field(default=900, ge=60, le=604800)
    action: Literal["prompt", "tool_call"] = "prompt"
    mode: Literal["inject", "fork", "fresh", "follow_up"] = "inject"
    prompt: str = Field(default="", max_length=32000)
    tool_call: ToolCallStepConfig | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=600, ge=10, le=3600)

    @model_validator(mode="after")
    def validate_action(self) -> HookDefinition:
        """Reject combinations that cannot run at their event boundary."""
        if self.action == "prompt" and not self.prompt.strip():
            raise ValueError("A prompt action requires prompt text")
        if self.action == "tool_call" and self.tool_call is None:
            raise ValueError("A tool_call action requires tool_call configuration")
        if self.action == "tool_call" and self.mode == "inject":
            raise ValueError("Tool calls require detached execution")
        if self.action == "tool_call" and self.mode != "fresh":
            raise ValueError("Deterministic tool calls require fresh execution")
        if self.mode == "follow_up" and self.trigger not in {"turn_completed", "conversation_idle"}:
            raise ValueError("Follow-up actions require turn_completed or conversation_idle")
        if self.mode == "inject" and self.trigger in {"turn_completed", "conversation_idle"}:
            raise ValueError("This trigger requires detached execution")
        return self


class HookAssignment(BaseModel):
    """Per-agent activation and template parameters."""

    model_config = ConfigDict(extra="forbid")
    hook_id: str
    enabled: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)


class HookResponse(HookDefinition):
    hook_id: str
    revision: int
    bundled: bool = False


class HookRunResponse(BaseModel):
    run_id: str
    hook_id: str
    hook_revision: int
    agent_id: str
    conversation_id: str
    status: str
    child_conversation_id: str | None = None
    task_id: str | None = None
    created_at: str
    finished_at: str | None = None
