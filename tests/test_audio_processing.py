"""

Tests for the audio-side pure helpers (VAD, silence trimming, speaker
assignment). No Whisper, pyannote, or ffmpeg is required.

"""

import wave

import numpy as np

from audio.audio_processing import (
    _detect_speech_bounds,
    apply_silence_trimming,
    assign_speakers,
)


def test_assign_speakers_basic():
    words = [
        {"s": 0.5, "w": "a"},
        {"s": 5.5, "w": "c"},
        {"s": 2.2, "w": "b"},
        {"s": 8.0, "w": "d"},
    ]
    turns = [(0.0, 2.0, "SPEAKER_00"), (3.0, 6.0, "SPEAKER_01")]
    num = assign_speakers(words, turns)
    assert num == 2
    assert [word["spk"] for word in words] == [0, 1, 0, 1]


def test_assign_speakers_handles_unsorted_turns():
    words = [{"s": 1.5, "w": "x"}, {"s": 4.5, "w": "y"}]
    turns = [(3.0, 6.0, "B"), (0.0, 2.0, "A")]
    assign_speakers(words, turns)
    assert words[0]["spk"] == 1
    assert words[1]["spk"] == 0


def test_detect_speech_bounds_silence_returns_none():
    samples = np.zeros(16000 * 2, dtype=np.int16)
    assert _detect_speech_bounds(samples, 16000) is None


def test_detect_speech_bounds_detects_span():
    sample_rate = 16000
    samples = np.zeros(sample_rate * 4, dtype=np.int16)
    samples[int(1.0 * sample_rate) : int(3.0 * sample_rate)] = 5000
    start, end = _detect_speech_bounds(samples, sample_rate)
    assert start < 1.2
    assert end > 2.8


def _write_wav(path, samples, sample_rate):
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(samples.astype(np.int16).tobytes())


def test_apply_silence_trimming_full_of_speech_unchanged(tmp_path):
    sample_rate = 16000
    samples = np.full(sample_rate * 2, 3000, dtype=np.int16)
    wav_path = tmp_path / "full.wav"
    _write_wav(wav_path, samples, sample_rate)

    result_path, offset, has_speech = apply_silence_trimming(str(wav_path))
    assert result_path == str(wav_path)
    assert offset == 0.0
    assert has_speech is True


def test_apply_silence_trimming_silent_file(tmp_path):
    sample_rate = 16000
    samples = np.zeros(sample_rate * 2, dtype=np.int16)
    wav_path = tmp_path / "silent.wav"
    _write_wav(wav_path, samples, sample_rate)

    result_path, offset, has_speech = apply_silence_trimming(str(wav_path))
    assert result_path == str(wav_path)
    assert offset == 0.0
    assert has_speech is False
