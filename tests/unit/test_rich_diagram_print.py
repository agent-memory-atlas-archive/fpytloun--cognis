"""Rich report visual invariants across PDF and Markdown projections."""

from types import SimpleNamespace

from bs4 import BeautifulSoup

from cognis.channels.rich_markdown import render_rich_markdown
from cognis.rendering.deliverables import (
    _embed_pdf_mermaid,
    _render_timeline,
    render_standalone_html,
)
from cognis.rendering.rich_visuals import normalize_chart, render_chart_svg


def test_steps_suppress_only_matching_rendered_marker():
    block = {
        "type": "steps",
        "items": [
            {"title": "1. Reduce workers", "description": "Measure."},
            {"title": "2. Depth 3 → 2", "description": "Verify."},
            {"title": "5. Do not silently renumber", "description": "Escalate."},
        ],
    }
    print_html = _render_timeline(block)
    markdown = render_rich_markdown(
        {"blocks": [block]},
        title="Plan",
        full_view_link=None,
        deliverable_id="",
        fallback_text="",
    )
    assert "<strong>Reduce workers</strong>" in print_html
    assert "<strong>Depth 3 → 2</strong>" in print_html
    assert "<strong>5. Do not silently renumber</strong>" in print_html
    assert "1. Reduce workers" in markdown
    assert "2. Depth 3 → 2" in markdown
    assert "3. 5. Do not silently renumber" in markdown


def test_positive_chart_does_not_invent_negative_ticks_and_thins_dates():
    chart = {
        "type": "chart",
        "spec_version": "cognis.chart.v1",
        "chart_type": "line",
        "x_axis": {"type": "category", "label": "Time (UTC)"},
        "y_axis": {"type": "linear", "label": "Load average"},
        "series": [
            {
                "id": "load5",
                "label": "host_load5",
                "points": [
                    {"x": "Sep 11", "y": 6},
                    {"x": "Sep 18", "y": 13},
                    {"x": "Sep 24 06:00", "y": 22},
                    {"x": "Sep 24 12:00", "y": 28},
                    {"x": "Sep 24 20:00", "y": 395},
                    {"x": "Sep 25 02:00", "y": 534},
                    {"x": "Sep 25 08:00", "y": 464},
                ],
            }
        ],
    }
    svg = BeautifulSoup(render_chart_svg(normalize_chart(chart)), "xml")
    labels = [label.get_text() for label in svg.select(".chart-axis-label")]
    assert not any(label.startswith("-") for label in labels)
    assert len([label for label in labels if label.startswith("Sep")]) < 7
    assert "Sep 25 08:00" in labels
    assert "600" in labels and "0" in labels
    assert len(svg.select("polyline.chart-line")) == 1


def test_pdf_embeds_mermaid_image(monkeypatch):
    png = b"\x89PNG\r\n\x1a\n" + b"diagram"
    monkeypatch.setattr("cognis.rendering.deliverables._render_mermaid_png", lambda source: png)
    row = SimpleNamespace(
        title="Report",
        format="rich",
        content="",
        rich_payload={
            "blocks": [
                {"type": "hero", "title": "Report"},
                {
                    "type": "mermaid",
                    "title": "Request flow",
                    "source": 'flowchart LR\n A["Source"] --&gt; B["Destination"]',
                },
            ]
        },
    )
    html = render_standalone_html(row, render_target="pdf")
    assert not BeautifulSoup(html, "html.parser").select(".pdf-mermaid-image")
    embedded = _embed_pdf_mermaid(html)
    assert BeautifulSoup(embedded, "html.parser").select_one(".pdf-mermaid-image")
    assert "flowchart LR" not in BeautifulSoup(embedded, "html.parser").get_text()
    # Invalid test PNG is enough for composition, but not the PDF backend.


def test_pdf_invalid_diagram_retains_source(monkeypatch):
    def fail(_: str) -> bytes:
        raise ValueError("invalid syntax")

    monkeypatch.setattr("cognis.rendering.deliverables._render_mermaid_png", fail)
    html = '<section class="block-mermaid"><pre>flowchart LR A--&gt;B</pre></section>'
    assert "flowchart LR A" in _embed_pdf_mermaid(html)
