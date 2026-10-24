from cognis.core.chat_modes import (
    chat_mode_system_message,
    optional_chat_mode,
    plan_mode_reminder,
)


def test_optional_chat_mode_validates_durable_values_without_calling_type_alias() -> None:
    assert optional_chat_mode("build") == "build"
    assert optional_chat_mode(" PLAN ") == "plan"
    assert optional_chat_mode(None) is None
    assert optional_chat_mode("unsupported") is None


def test_planning_reminder_does_not_require_an_execution_sandbox() -> None:
    reminder = plan_mode_reminder(source="one_shot")
    assert "not a strict read-only sandbox" in reminder
    assert "Planning documents, scratch files" in reminder
    assert "Do not perform substantive implementation" in reminder
    assert "Explicit read-only restrictions" in reminder
    assert "only read-only commands" not in reminder
    assert "read-only" not in chat_mode_system_message("plan")
