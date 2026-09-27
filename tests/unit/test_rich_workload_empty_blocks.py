"""Persisted workload report content survives both portable renderers."""

from cognis.channels.rich_markdown import render_rich_markdown
from cognis.rendering.deliverables import _render_block


def test_section_claim_cards_and_callout_retain_authored_text() -> None:
    blocks = [
        {
            "type": "section",
            "heading": "Deployed this run",
            "body": "Both approved upgrades are live and verified.",
        },
        {
            "type": "claim_cards",
            "title": "Skipped before mutation",
            "cards": [
                {
                    "claim": "Infra doc correction not applied",
                    "evidence": "Historical evidence must remain unchanged.",
                    "verdict": "Correctly deferred",
                },
                {
                    "claim": "Kernel dist-upgrade not performed",
                    "evidence": "No established host-access path.",
                    "verdict": "Blocked on tooling",
                },
            ],
        },
        {
            "type": "callout",
            "variant": "warning",
            "text": "Residual follow-ups require an approved window.",
        },
    ]
    pdf_html = " ".join(_render_block(block) for block in blocks)
    markdown = render_rich_markdown(
        {"blocks": blocks},
        title="Workload review",
        full_view_link=None,
        deliverable_id="",
        fallback_text="",
    )
    for output in (pdf_html, markdown.replace("\\-", "-")):
        for text in (
            "Both approved upgrades are live and verified.",
            "Infra doc correction not applied",
            "Historical evidence must remain unchanged.",
            "Correctly deferred",
            "Kernel dist-upgrade not performed",
            "No established host-access path.",
            "Blocked on tooling",
            "Residual follow-ups require an approved window.",
        ):
            assert text in output
