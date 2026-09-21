"""

Tests for markdown rendering and sanitization.

"""

from services.text_filters import markdown_to_text, render_markdown


def test_render_markdown_basic():
    html = render_markdown("**bold** and a [link](https://example.com)")
    assert "<strong>bold</strong>" in html
    assert '<a href="https://example.com">link</a>' in html


def test_render_markdown_strips_script():
    html = render_markdown("hello <script>alert(1)</script>")
    assert "<script>" not in html
    assert "<script" not in html


def test_render_markdown_strips_javascript_url():
    html = render_markdown("[x](javascript:alert(1))")
    assert "javascript:" not in html


def test_render_markdown_strips_event_handlers():
    html = render_markdown('<a href="https://example.com" onclick="alert(1)">x</a>')
    assert "onclick" not in html


def test_render_markdown_empty():
    assert render_markdown("") == ""
    assert render_markdown(None) == ""


def test_render_markdown_tables():
    html = render_markdown("| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<table>" in html
    assert "<td>" in html


def test_markdown_to_text_strips_syntax():
    text = markdown_to_text(
        "## Life Expectancy\nDeterminants - **bold** point and *italic*"
    )
    assert "##" not in text
    assert "**" not in text
    assert "*" not in text
    assert "Life Expectancy" in text
    assert "bold" in text


def test_markdown_to_text_empty():
    assert markdown_to_text("") == ""
    assert markdown_to_text(None) == ""
