import pytest
from jsonschema import validate
from pydantic import ValidationError

from cognis.models.agent import AgentRuntimeProfile
from cognis.tools.builtin.agent_management import MANAGE_AGENTS_TOOL


@pytest.mark.parametrize("index", [-1, 1.5, True, "2", None])
def test_quick_profile_rejects_invalid_positions(index: object) -> None:
    with pytest.raises(ValidationError):
        AgentRuntimeProfile.model_validate({"quick_switch_index": index})


def test_quick_switch_defaults_are_backward_compatible() -> None:
    profile = AgentRuntimeProfile()
    assert profile.quick_switch is False
    assert profile.quick_switch_index == 0
    assert profile.quick_switch_color == "neutral"
    assert profile.agent_switchable is False


@pytest.mark.parametrize("action", ["runtime_profiles_create", "runtime_profiles_update"])
def test_management_schema_accepts_quick_switch_configuration(action: str) -> None:
    validate(
        {
            "action": action,
            "agent_id": "target",
            "profile_id": "smart",
            "profile": {
                "quick_switch": True,
                "quick_switch_index": 2,
                "quick_switch_color": "violet",
            },
        },
        MANAGE_AGENTS_TOOL.parameters,
    )


@pytest.mark.parametrize("color", ["neutral", "blue", "teal", "amber", "violet", "rose"])
def test_quick_profile_palette_roundtrip(color: str) -> None:
    profile = AgentRuntimeProfile.model_validate({"quick_switch_color": color})
    assert AgentRuntimeProfile.model_validate(profile.model_dump()).quick_switch_color == color


@pytest.mark.parametrize("color", ["red", "#ff0000", None])
def test_quick_profile_rejects_invalid_colors(color: object) -> None:
    with pytest.raises(ValidationError):
        AgentRuntimeProfile.model_validate({"quick_switch_color": color})
