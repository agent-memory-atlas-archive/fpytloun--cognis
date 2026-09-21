from cognis.core.tool_preparation import ToolPreparationBudget


def test_active_generation_cannot_extend_absolute_preparation_budget() -> None:
    budget = ToolPreparationBudget()
    assert budget.observe("patch", 1, 0) is None
    assert budget.observe("patch", 127331, 599) is None
    assert "600-second" in budget.observe("patch", 127332, 600)


def test_size_budget_is_per_generation_and_monotonic() -> None:
    budget = ToolPreparationBudget()
    assert budget.observe("first", 200000, 0) is None
    assert budget.observe("first", 1, 1) is None
    assert "character" in budget.observe("second", 70000, 2)
    assert ToolPreparationBudget().observe("second", 70000, 2) is None
