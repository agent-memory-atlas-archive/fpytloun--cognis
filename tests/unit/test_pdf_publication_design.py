"""Print composition keeps semantic content and uses offline publication fonts."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from pypdf import PdfReader
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration

from cognis.rendering.deliverables import (
    _blocked_url_fetcher,
    _render_intro,
    _render_pdf_sync,
    render_standalone_html,
)


def test_semantic_badges_take_precedence_over_topic_tags():
    intro = _render_intro(
        {
            "title": "Review",
            "tags": ["Topic"],
            "badges": [{"label": "Verified", "tone": "success"}],
        },
        fallback_title="Report",
    )
    assert "Verified" in intro
    assert "Topic" not in intro
    assert intro.index("Verified") < intro.index("<h1")


@pytest.mark.parametrize("name", ["archivo", "jetbrains-mono"])
def test_publication_fonts_are_vendored_and_allowlisted(name):
    resource = _blocked_url_fetcher(f"cognis-asset:{name}")
    assert resource["mime_type"] == "font/woff2"
    assert resource["string"][:4] == b"wOF2"
    with pytest.raises(ValueError):
        _blocked_url_fetcher(f"cognis-asset:{name}/../../secret")


def test_print_summary_grid_and_short_table_pagination():
    row = SimpleNamespace(
        title="Cost review",
        format="rich",
        content="",
        rich_payload={
            "blocks": [
                {"type": "hero", "title": "Cost review"},
                {
                    "type": "key_value",
                    "variant": "summary",
                    "items": [{"label": f"Metric {i}", "value": f"${i}"} for i in range(6)],
                },
                {"type": "markdown", "content": "\n\n".join(["A measured observation. " * 8] * 8)},
                {
                    "type": "table",
                    "title": "Accelerator costs",
                    "columns": ["Component", "Cost"],
                    "rows": [["Fixed fee", "$18"], ["Premium", "$1,366"], ["Total", "~$1,384"]],
                },
            ]
        },
    )
    source = render_standalone_html(row, render_target="pdf")
    assert BeautifulSoup(source, "html.parser").select_one("table.short-table")
    document = HTML(string=source, url_fetcher=_blocked_url_fetcher).render(
        font_config=FontConfiguration()
    )
    cells = [
        box
        for page in document.pages
        for box in page._page_box.descendants()
        if box.element_tag == "div"
        and box.element is not None
        and box.element.find("dt") is not None
    ]
    assert len(cells) == 6
    assert len({round(cell.position_x) for cell in cells}) == 3
    assert len({round(cell.position_y) for cell in cells}) == 2
    reader = PdfReader(BytesIO(_render_pdf_sync(source)))
    pages = [page.extract_text() for page in reader.pages]
    assert any("Accelerator costs" in page and "~$1,384" in page for page in pages)
    fonts = [
        str(font.get_object().get("/BaseFont"))
        for page in reader.pages
        for font in page["/Resources"]["/Font"].values()
    ]
    assert any("Archivo" in font for font in fonts)
    assert any("JetBrains" in font for font in fonts)
