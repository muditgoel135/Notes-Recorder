"""

Tests for key-points transcript formatting helpers.

"""

import json
from types import SimpleNamespace

from audio.key_points import _join_words_with_spacing, format_transcript_with_speakers


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
