from cognis.channels.matrix_formatting import markdown_to_matrix_html


def test_matrix_markdown_renders_headings_and_lists() -> None:
    html = markdown_to_matrix_html(
        "# Status\n\n## Checks\n\n- tests passed\n- lint passed\n\n1. deploy\n2. verify"
    )

    assert "<h1>Status</h1>" in html
    assert "<h2>Checks</h2>" in html
    assert "<ul>" in html
    assert "<li>tests passed</li>" in html
    assert "<ol>" in html
    assert "<li>verify</li>" in html


def test_matrix_markdown_linearizes_tables_for_client_portability() -> None:
    html = markdown_to_matrix_html(
        "| Check | Result |\n| --- | --- |\n| tests | ✅ |\n| lint | ✅ |"
    )

    assert "<table>" not in html
    assert "<strong>Check:</strong> tests" in html
    assert "<strong>Result:</strong> ✅" in html


def test_matrix_markdown_preserves_code_and_links() -> None:
    html = markdown_to_matrix_html(
        "Use `pytest` and [docs](https://example.com).\n\n```python\nprint('hi')\n```"
    )

    assert "<code>pytest</code>" in html
    assert '<a href="https://example.com">docs</a>' in html
    assert "<pre><code>print('hi')\n</code></pre>" in html


def test_matrix_markdown_normalizes_task_lists() -> None:
    html = markdown_to_matrix_html("- [x] done\n- [ ] pending")

    assert "<li>☑ done</li>" in html
    assert "<li>☐ pending</li>" in html


def test_matrix_markdown_supports_gfm_strikethrough_and_two_space_nested_lists() -> None:
    html = markdown_to_matrix_html("~~obsolete~~\n\n- parent\n  - nested")

    assert "<del>obsolete</del>" in html
    assert "<li>nested</li>" in html
    assert html.count("<ul>") == 2


def test_matrix_rich_markdown_preserves_semantic_block_spacing() -> None:
    html = markdown_to_matrix_html(
        "# Brief\n\nFirst paragraph.\n\nSecond paragraph.\n\n- one\n- two"
    )

    assert "<h1>Brief</h1>" in html
    assert "<p>First paragraph.</p>" in html
    assert "<p>Second paragraph.</p>" in html
    assert "<ul>" in html
    assert "<li>one</li>" in html


def test_matrix_rich_markdown_keeps_portable_document_hierarchy() -> None:
    html = markdown_to_matrix_html(
        "# Daily brief\n\n"
        "_Friday · 11 September_\n\n"
        "## Today\n\n"
        "A focused morning.\n\n"
        "> Protect the first work block.\n\n"
        "---\n\n"
        "### Plan\n\n"
        "1. Finish the report.\n"
        "2. Review the result."
    )

    assert html.startswith("<h1>Daily brief</h1>")
    assert "<p><em>Friday · 11 September</em></p>" in html
    assert "<h2>Today</h2>" in html
    assert "<p>A focused morning.</p>" in html
    assert "<blockquote>" in html
    assert "<p>Protect the first work block.</p>" in html
    assert "<hr/>" in html
    assert "<h3>Plan</h3>" in html
    assert "<ol>" in html
    assert "<li>Finish the report.</li>" in html


def test_matrix_markdown_sanitizes_unsafe_html_and_links() -> None:
    html = markdown_to_matrix_html(
        '<script>alert("x")</script>\n\n'
        "[bad](javascript:alert(1))\n\n"
        '<span style="color:red">plain</span>'
    )

    assert "<script>" not in html
    assert "javascript:" not in html
    assert "<span" not in html
    assert "plain" in html


def test_matrix_markdown_sanitizes_nested_unsafe_html() -> None:
    html = markdown_to_matrix_html(
        '<span><a href="javascript:alert(1)">bad</a></span>\n\n'
        '<div><strong onclick="alert(1)">strong</strong></div>'
    )

    assert "javascript:" not in html
    assert "onclick" not in html
    assert "<span" not in html
    assert "<div" not in html
    assert "<a " not in html
    assert "<strong>strong</strong>" in html
