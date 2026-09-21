"""

Tests for markdown rendering and sanitization.

"""

from services.text_filters import (
    markdown_to_text,
    normalize_list_indentation,
    render_markdown,
)


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


def test_render_markdown_inline_star_bullets():
    text = (
        "**Cooling Mechanisms (Heat Loss)** * **Sweating:** When the body is "
        "exposed * **Evaporation:** cooling happens * **Chemical Regulation:** "
        "stimulated * **Hydration:** needs water"
    )
    html = str(render_markdown(text))
    assert html.count("<li>") == 4
    assert "<strong>Sweating:</strong>" in html
    assert "<strong>Hydration:</strong>" in html
    # Inline markers must not survive as literal asterisks.
    assert " * <strong>Sweating" not in html
    assert " * <strong>Evaporation" not in html


def test_render_markdown_inline_bullets_without_bold():
    text = (
        "Cooling Mechanisms (Heat Loss) * Sweating: body sweats "
        "* Evaporation: sweat evaporates"
    )
    html = str(render_markdown(text))
    assert html.count("<li>") == 2
    assert " * Sweating" not in html


def test_render_markdown_list_after_heading_without_blank_line():
    html = str(render_markdown("**Warming**\n* **Shivering:** a\n* **Body Hair:** b"))
    assert "<p><strong>Warming</strong></p>" in html
    assert html.count("<li>") == 2
    assert "\n* " not in html  # no literal list markers left in a paragraph


def test_render_markdown_dash_list_after_paragraph():
    html = str(render_markdown("**Bold heading**\n- a\n- b"))
    assert "<ul>" in html
    assert html.count("<li>") == 2


def test_render_markdown_ordered_list_after_paragraph():
    html = str(render_markdown("Para\n1. first\n2. second"))
    assert "<ol>" in html
    assert html.count("<li>") == 2


def test_render_markdown_preserves_math_and_emphasis():
    assert "5 * 3 = 15" in str(render_markdown("Normal para with 5 * 3 = 15 math"))
    assert "5 * 10:" in str(render_markdown("Explain: 5 * 10: something"))
    assert "<em>italic</em>" in str(render_markdown("Use *italic* here"))


def test_normalize_list_indentation_splits_and_separates():
    normalized = normalize_list_indentation(
        "**Heading** * **A:** x * **B:** y"
    )
    assert normalized == "**Heading**\n\n* **A:** x\n* **B:** y"
