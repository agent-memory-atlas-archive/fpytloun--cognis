"""Persisted text-only checklist items survive portable exports."""

import pytest

from cognis.channels.rich_markdown import render_rich_markdown
from cognis.rendering.deliverables import _render_block


@pytest.mark.parametrize("kind", ["checklist", "incident_checklist"])
def test_checklist_text_items_are_not_empty_timeline_entries(kind):
    block = {
        "type": kind,
        "items": [{"text": "Verify backup"}, {"text": "Test restore", "done": True}],
    }
    html = _render_block(block)
    markdown = render_rich_markdown(
        {"blocks": [block]},
        title="Maintenance",
        full_view_link=None,
        deliverable_id="",
        fallback_text="",
    )
    for rendered in (html, markdown):
        assert "Verify backup" in rendered
        assert "Test restore" in rendered
        assert "Entry 1" not in rendered
        assert "Item 1" not in rendered
    assert "- [ ] Verify backup" in markdown
    assert "- [x] Test restore" in markdown
