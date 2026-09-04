import json

from services.text_filters import (
    format_display_date,
    format_display_time,
    is_allowed_video_embed_src,
    normalize_list_indentation,
    parse_json,
    rich_note_html_to_text,
    sanitize_rich_note_html,
)


def test_rich_note_sanitizer_removes_scripts_events_and_unsafe_css():
    cleaned = sanitize_rich_note_html(
        '<p onclick="alert(1)" style="color:red;position:absolute">Safe</p>'
        '<script>alert(1)</script><style>body{display:none}</style>'
    )
    assert cleaned is not None
    assert "onclick" not in cleaned
    assert "position" not in cleaned
    assert "<script" not in cleaned
    assert "Safe" in cleaned


def test_rich_note_sanitizer_keeps_safe_video_and_rejects_unsafe_video():
    html = (
        '<iframe src="https://www.youtube.com/embed/abc" title="Lesson"></iframe>'
        '<iframe src="https://evil.example/embed/abc"></iframe>'
    )
    cleaned = sanitize_rich_note_html(html)
    assert cleaned is not None
    assert "youtube.com/embed/abc" in cleaned
    assert "evil.example" not in cleaned


def test_rich_note_sanitizer_validates_images_and_attributes():
    cleaned = sanitize_rich_note_html(
        '<img src="data:image/png;base64,aGVsbG8=" alt="diagram" '
        'onerror="alert(1)"><img src="data:text/html;base64,abc">'
    )
    assert cleaned is not None
    assert "data:image/png" in cleaned
    assert "data:text/html" not in cleaned
    assert "onerror" not in cleaned


def test_rich_note_html_to_text_handles_blocks_lists_math_images_and_iframes():
    text = rich_note_html_to_text(
        '<h2>Title</h2><p>Hello<br>world</p><ul><li>One</li><li>Two</li></ul>'
        '<span class="math-field" data-latex="x^2"><span>ignored</span></span>'
        '<img alt="diagram" src="data:image/png;base64,abc">'
        '<iframe src="https://player.vimeo.com/video/123" title="Demo"></iframe>'
    )
    assert "Title" in text
    assert "Hello" in text and "world" in text
    assert "- One" in text and "- Two" in text
    assert "$x^2$" in text
    assert "[Image: diagram]" in text
    assert "[Demo]" in text
    assert "ignored" not in text


def test_allowed_video_embed_sources_are_strict():
    assert is_allowed_video_embed_src("https://youtube-nocookie.com/embed/x")
    assert is_allowed_video_embed_src("https://player.vimeo.com/video/123")
    assert not is_allowed_video_embed_src("http://youtube.com/embed/x")
    assert not is_allowed_video_embed_src("https://youtube.com/watch?v=x")
    assert not is_allowed_video_embed_src("https://youtube.com.evil.test/embed/x")


def test_list_normalization_flattens_runaway_top_level_indent():
    normalized = normalize_list_indentation("    - first\n        - second")
    assert normalized == "- first\n    - second"


def test_formatters_and_parse_json_handle_valid_and_invalid_values():
    assert format_display_date("2026-09-03") == "03/09/2026"
    assert format_display_date("bad") == "bad"
    assert format_display_time("00:05:00") == "12:05 AM"
    assert format_display_time("13:05") == "1:05 PM"
    assert format_display_time("bad") == "bad"
    assert parse_json(json.dumps([1, 2])) == [1, 2]
    assert parse_json("{bad") == []
    assert parse_json(None) == []
