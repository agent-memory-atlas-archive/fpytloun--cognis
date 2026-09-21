"""Persisted hero summaries must survive every renderer."""

from cognis.channels.rich_markdown import render_rich_markdown
from cognis.rendering.deliverables import _render_block, _render_intro


def test_hero_dek_survives_web_fallback_and_markdown():
    block = {"type": "hero", "title": "Operational review", "dek": "Bounded coverage"}
    assert "Bounded coverage" in _render_intro(block, fallback_title="Review")
    assert "Bounded coverage" in _render_block(block)
    assert "Bounded coverage" in render_rich_markdown(
        {"blocks": [block]},
        title="Review",
        full_view_link=None,
        deliverable_id="",
        fallback_text="",
    )


def test_hero_subtitle_takes_precedence_over_dek():
    block = {"type": "hero", "title": "Review", "subtitle": "Canonical", "dek": "Older"}
    for rendered in (
        _render_intro(block, fallback_title="Review"),
        _render_block(block),
        render_rich_markdown(
            {"blocks": [block]},
            title="Review",
            full_view_link=None,
            deliverable_id="",
            fallback_text="",
        ),
    ):
        assert "Canonical" in rendered
        assert "Older" not in rendered
