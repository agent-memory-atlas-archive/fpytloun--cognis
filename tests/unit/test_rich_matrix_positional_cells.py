"""Positional matrix values must survive PDF and Markdown projections."""

from bs4 import BeautifulSoup

from cognis.channels.rich_markdown import render_rich_markdown
from cognis.rendering.deliverables import _render_block


def test_labeled_positional_matrix_rows_preserve_values_and_explicit_cells() -> None:
    block = {
        "type": "comparison_matrix",
        "title": "Approval decisions",
        "columns": ["Severity", {"key": "component", "label": "Component"}, "Action"],
        "rows": [
            {
                "label": "Upgrade A",
                "values": ["HIGH", "ArgoCD", "Stage upgrade"],
            },
            {
                "label": "Upgrade B",
                "values": ["MEDIUM", "Harbor", "Back up first"],
                "component": "Explicit override",
            },
        ],
    }
    html = BeautifulSoup(_render_block(block), "html.parser")
    cells = [
        [cell.get_text(" ", strip=True) for cell in row.select("td")]
        for row in html.select("tbody tr")
    ]
    assert cells == [
        ["HIGH", "ArgoCD", "Stage upgrade"],
        ["MEDIUM", "Explicit override", "Back up first"],
    ]

    markdown = render_rich_markdown(
        {"blocks": [block]},
        title="Review",
        full_view_link=None,
        deliverable_id="",
        fallback_text="",
    )
    assert "| HIGH | ArgoCD | Stage upgrade |" in markdown
    assert "| MEDIUM | Explicit override | Back up first |" in markdown
