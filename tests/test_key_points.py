"""

Tests for key-points transcript formatting helpers.

"""

import json
from types import SimpleNamespace

from audio.key_points import (
    _join_words_with_spacing,
    _parse_ollama_json,
    format_transcript_with_speakers,
)


def test_join_words_with_leading_spaces():
    assert _join_words_with_spacing([" Hello", " world!"]) == " Hello world!"


def test_join_words_without_leading_spaces():
    assert _join_words_with_spacing(["Hello", "world!"]) == "Hello world!"


def test_join_words_punctuation_attaches():
    assert _join_words_with_spacing(["Hello", "!", "What"]) == "Hello! What"


def test_join_words_unicode():
    assert _join_words_with_spacing(["नमस्ते", "दुनिया"]) == "नमस्ते दुनिया"


def test_join_words_empty():
    assert _join_words_with_spacing([]) == ""


def test_parse_ollama_json_plain():
    result = _parse_ollama_json('{"title": "Hi", "key_points": "- a"}')
    assert result == {"title": "Hi", "key_points": "- a"}


def test_parse_ollama_json_ignores_prose():
    content = (
        "Sure, here is the JSON you asked for:\n"
        '{"title": "Hi", "key_points": "- a"}\n'
        "Let me know if you need more help."
    )
    result = _parse_ollama_json(content)
    assert result == {"title": "Hi", "key_points": "- a"}


def test_parse_ollama_json_markdown_fence():
    content = '```json\n{"title": "Hi", "key_points": "- a"}\n```'
    result = _parse_ollama_json(content)
    assert result == {"title": "Hi", "key_points": "- a"}


def test_parse_ollama_json_stray_backslash():
    content = '{"title": "Math", "key_points": "- \\\\(x + y\\\\)"}'
    result = _parse_ollama_json(content)
    assert result == {"title": "Math", "key_points": "- \\(x + y\\)"}


def test_parse_ollama_json_invalid_returns_none():
    assert _parse_ollama_json("") is None
    assert _parse_ollama_json("no json here") is None
    assert _parse_ollama_json("{not valid json}") is None


def test_format_transcript_with_speakers_uses_spacing():
    note = SimpleNamespace(
        transcription_segments=json.dumps(
            [
                {"s": 0.0, "w": "Hello", "spk": 0},
                {"s": 0.2, "w": "world!", "spk": 0},
                {"s": 0.4, "w": "नमस्ते", "spk": 1},
                {"s": 0.6, "w": "दुनिया", "spk": 1},
            ]
        ),
        transcription="fallback",
    )

    def speakers_by_order():
        return {
            0: SimpleNamespace(display_name=None, label="Speaker 1"),
            1: SimpleNamespace(display_name=None, label="Speaker 2"),
        }

    note.speakers_by_order = speakers_by_order

    result = format_transcript_with_speakers(note)
    assert "Speaker 1: Hello world!" in result
    assert "Speaker 2: नमस्ते दुनिया" in result


def test_format_transcript_with_speakers_falls_back():
    note = SimpleNamespace(
        transcription_segments="[]",
        transcription="plain transcript",
    )
    note.speakers_by_order = dict
    assert format_transcript_with_speakers(note) == "plain transcript"
