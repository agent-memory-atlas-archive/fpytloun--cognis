"""Agent outcome settings must remain validated independently of the UI."""

import pytest
from pydantic import ValidationError

from cognis.core.session import _intaris_session_policy
from cognis.models.agent import AgentCapabilities


def test_agent_outcome_bounds_validate_and_serialize() -> None:
    capabilities = AgentCapabilities(minimum_outcome="escalate", maximum_outcome="approve")
    assert capabilities.model_dump()["maximum_outcome"] == "approve"
    with pytest.raises(ValidationError):
        AgentCapabilities(maximum_outcome="unknown")
    with pytest.raises(ValidationError):
        AgentCapabilities(guardrails_backend="none", maximum_outcome="approve")


def test_session_policy_uses_agent_default_and_conversation_override() -> None:
    class Agent:
        capabilities = AgentCapabilities(maximum_outcome="escalate")

    default = _intaris_session_policy("/tmp/work", agent=Agent())
    assert default["maximum_outcome"] == "escalate"
    unattended = _intaris_session_policy("/tmp/work", agent=Agent(), interaction_mode="none")
    assert unattended["interaction_mode"] == "none"
    assert unattended["maximum_outcome"] == "escalate"
    override = _intaris_session_policy(
        "/tmp/work", agent=Agent(), conversation_data={"maximum_outcome_override": "approve"}
    )
    assert override["maximum_outcome"] == "approve"
    assert _intaris_session_policy("/tmp/work").get("maximum_outcome") is None
