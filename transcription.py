import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import numpy as np
import requests

from extensions import app, db
from models import Note, Speaker, SPEAKER_COLOR_PALETTE
from config import (
    BASE_DIR,
    WHISPER_MODEL_NAME,
    HUGGINGFACE_TOKEN,
    HINDI_SUBJECT,
    HINDI_INITIAL_PROMPT,
    TRANSCRIPTION_PENDING,
    TRANSCRIPTION_PROCESSING,
    TRANSCRIPTION_COMPLETED,
    TRANSCRIPTION_FAILED,
    KEY_POINTS_PENDING,
    KEY_POINTS_PROCESSING,
    KEY_POINTS_COMPLETED,
    KEY_POINTS_FAILED,
    KEY_POINTS_RETRY_SECONDS,
    OLLAMA_API_KEY,
    OLLAMA_MODEL,
    OLLAMA_CHAT_URL,
)

transcription_executor = ThreadPoolExecutor(max_workers=1)
whisper_model = None
whisper_model_lock = threading.Lock()

diarization_pipeline = None
diarization_pipeline_lock = threading.Lock()


def is_internet_available(host="8.8.8.8", port=53, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def get_whisper_model():
    global whisper_model
    if whisper_model is None:
        with whisper_model_lock:
            if whisper_model is None:
                import whisper

                whisper_model = whisper.load_model(WHISPER_MODEL_NAME)

    return whisper_model


def update_transcription_status(
    note_id, status, transcription=None, segments=None, error=None
):
    note = db.session.get(Note, note_id)
    if not note:
        return None

    note.transcription_status = status
    if transcription is not None:
        note.transcription = transcription

    if segments is not None:
        note.transcription_segments = segments

    note.transcription_error = error
    db.session.commit()
    return note


def update_transcription_progress(note_id, progress):
    note = db.session.get(Note, note_id)
    if not note:
        return None

    note.transcription_progress = progress
    db.session.commit()
    return note


@contextmanager
def track_whisper_progress(note_id):
    """Patch whisper's internal tqdm progress bar to persist percent-complete
    onto the note, so the UI can render a live progress bar during transcription.

    Whisper only exposes progress through a tqdm instance tracking mel frames
    processed vs. total frames, with no callback hook, so we swap in a tqdm
    subclass for the duration of the transcribe() call to intercept updates.
    """
    import sys

    import whisper  # noqa: F401  (ensures whisper.transcribe is in sys.modules)

    # `whisper.transcribe` is shadowed on the package by the top-level
    # `transcribe` function (see whisper/__init__.py), so the submodule that
    # defines the tqdm-based progress bar must be looked up via sys.modules
    # instead of attribute access.
    whisper_transcribe_module = sys.modules["whisper.transcribe"]

    last_reported = {"percent": -1, "time": 0.0}

    def report(current_frames, total_frames):
        if not total_frames:
            return
        percent = min(99, int(current_frames / total_frames * 100))
        now = time.monotonic()
        if percent == last_reported["percent"] or now - last_reported["time"] < 1:
            return
        last_reported["percent"] = percent
        last_reported["time"] = now
        update_transcription_progress(note_id, percent)

    real_tqdm_cls = whisper_transcribe_module.tqdm.tqdm

    class ReportingTqdm(real_tqdm_cls):
        def update(self, n=1):
            super().update(n)
            report(self.n, self.total)

    class TqdmModuleShim:
        tqdm = ReportingTqdm

    original_tqdm_module = whisper_transcribe_module.tqdm
    whisper_transcribe_module.tqdm = TqdmModuleShim
    try:
        yield
    finally:
        whisper_transcribe_module.tqdm = original_tqdm_module


def update_key_points_status(note_id, status, title=None, key_points=None, error=None):
    note = db.session.get(Note, note_id)
    if not note:
        return None

    note.key_points_status = status
    if title is not None:
        note.title = title

    if key_points is not None:
        note.key_points = key_points

    note.key_points_error = error
    db.session.commit()
    return note


def denoise_audio(audio_path):
    """Run the audio through ffmpeg noise reduction and return the temp file path.

    Falls back to the original path if ffmpeg is missing or fails, since
    transcribing noisy audio is better than not transcribing at all.
    """
    fd, denoised_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                audio_path,
                "-af",
                "highpass=f=100,afftdn=nf=-25,dynaudnorm",
                "-ar",
                "16000",
                "-ac",
                "1",
                denoised_path,
            ],
            check=True,
            capture_output=True,
        )
        return denoised_path
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        if os.path.exists(denoised_path):
            os.remove(denoised_path)
        return audio_path


def get_diarization_pipeline():
    global diarization_pipeline
    if diarization_pipeline is None:
        with diarization_pipeline_lock:
            if diarization_pipeline is None:
                from pyannote.audio import Pipeline

                diarization_pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    token=HUGGINGFACE_TOKEN,
                )

    return diarization_pipeline


def load_waveform(audio_path):
    """Load a mono PCM WAV file into a pyannote-compatible waveform dict.

    Reads the file directly with the stdlib wave module instead of handing
    the path to pyannote, since torchcodec (pyannote's default audio
    backend) frequently fails to load its native libraries on Windows.
    """
    import torch

    with wave.open(audio_path, "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        raw_audio = wav_file.readframes(wav_file.getnframes())

    samples = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
    waveform = torch.from_numpy(samples).unsqueeze(0)
    return {"waveform": waveform, "sample_rate": sample_rate}


def diarize_audio(audio_path):
    """Return a list of (start, end, raw_speaker_label) turns, or None if unavailable.

    Diarization is best-effort: a missing token, missing dependency, or a
    pipeline failure all fall back to an undifferentiated transcript rather
    than failing the whole transcription.
    """
    if not HUGGINGFACE_TOKEN:
        return None

    try:
        pipeline = get_diarization_pipeline()
        output = pipeline(load_waveform(audio_path))
        diarization = getattr(output, "speaker_diarization", output)
        return [
            (turn.start, turn.end, label)
            for turn, _, label in diarization.itertracks(yield_label=True)
        ]
    except Exception:
        return None


def assign_speakers(words, turns):
    """Tag each word dict in-place with a 0-based "spk" index and return the
    number of distinct speakers, based on diarization turns."""
    order_map = {}
    for _, _, label in turns:
        if label not in order_map:
            order_map[label] = len(order_map)

    for word in words:
        start = word["s"]
        speaker_label = None
        for turn_start, turn_end, label in turns:
            if turn_start <= start <= turn_end:
                speaker_label = label
                break

        if speaker_label is None:
            nearest = min(
                turns, key=lambda turn: min(abs(turn[0] - start), abs(turn[1] - start))
            )
            speaker_label = nearest[2]

        word["spk"] = order_map[speaker_label]

    return len(order_map)


def transcribe_note(note_id, audio_path):
    with app.app_context():
        denoised_path = audio_path
        try:
            note = update_transcription_status(note_id, TRANSCRIPTION_PROCESSING)
            if not note:
                return
            update_transcription_progress(note_id, 0)

            denoised_path = denoise_audio(audio_path)

            transcribe_kwargs = {"fp16": False, "word_timestamps": True, "verbose": False}
            if note.subject == HINDI_SUBJECT:
                transcribe_kwargs["language"] = "hi"
                transcribe_kwargs["initial_prompt"] = HINDI_INITIAL_PROMPT
                transcribe_kwargs["beam_size"] = 5

            with track_whisper_progress(note_id):
                result = get_whisper_model().transcribe(denoised_path, **transcribe_kwargs)
            transcription = (result.get("text") or "").strip()
            words = [
                {"s": word["start"], "w": word["word"]}
                for segment in result.get("segments") or []
                for word in segment.get("words") or []
            ]

            if words:
                turns = diarize_audio(denoised_path)
                if turns:
                    num_speakers = assign_speakers(words, turns)
                    Speaker.query.filter_by(note_id=note_id).delete()
                    for index in range(num_speakers):
                        db.session.add(
                            Speaker(
                                note_id=note_id,
                                order_index=index,
                                label=f"Speaker {index + 1}",
                                color=SPEAKER_COLOR_PALETTE[
                                    index % len(SPEAKER_COLOR_PALETTE)
                                ],
                            )
                        )
                    db.session.commit()

            segments_json = json.dumps(words) if words else None
            update_transcription_status(
                note_id,
                TRANSCRIPTION_COMPLETED,
                transcription=transcription,
                segments=segments_json,
                error=None,
            )

        except Exception as exc:
            db.session.rollback()
            error_message = str(exc).strip() or exc.__class__.__name__
            update_transcription_status(
                note_id,
                TRANSCRIPTION_FAILED,
                error=error_message[:1000],
            )
            return

        finally:
            if denoised_path != audio_path and os.path.exists(denoised_path):
                os.remove(denoised_path)

        extract_key_points(note_id, transcription)


def format_transcript_with_speakers(note):
    """Render transcription_segments as "Speaker N: ..." lines per turn.

    Falls back to the plain transcript when there's no per-word speaker
    data (diarization disabled/unavailable), so the Ollama prompt still
    gets a usable transcript either way.
    """
    words = (
        json.loads(note.transcription_segments) if note.transcription_segments else []
    )
    if not words or all(word.get("spk") is None for word in words):
        return note.transcription or ""

    speakers = note.speakers_by_order()

    def speaker_name(spk):
        speaker = speakers.get(spk)
        if speaker:
            return speaker.display_name or speaker.label
        return f"Speaker {spk + 1}" if spk is not None else "Unknown speaker"

    lines = []
    current_spk = object()
    current_words = []
    for word in words:
        spk = word.get("spk")
        if spk != current_spk:
            if current_words:
                lines.append(
                    f"{speaker_name(current_spk)}: {''.join(current_words).strip()}"
                )
            current_spk = spk
            current_words = []
        current_words.append(word["w"])

    if current_words:
        lines.append(f"{speaker_name(current_spk)}: {''.join(current_words).strip()}")

    return "\n".join(lines)


def extract_key_points(note_id, transcript):
    with app.app_context():
        if not transcript:
            update_key_points_status(
                note_id, KEY_POINTS_FAILED, error="No transcript to summarize."
            )
            return

        note = db.session.get(Note, note_id)
        prompt_transcript = (
            format_transcript_with_speakers(note) if note else transcript
        )

        if not OLLAMA_API_KEY:
            update_key_points_status(
                note_id,
                KEY_POINTS_FAILED,
                error="OLLAMA_API_KEY is not configured.",
            )
            return

        if not is_internet_available():
            update_key_points_status(
                note_id,
                KEY_POINTS_PENDING,
                error="Waiting for an internet connection to reach Ollama.",
            )
            threading.Timer(
                KEY_POINTS_RETRY_SECONDS,
                lambda: transcription_executor.submit(
                    extract_key_points, note_id, transcript
                ),
            ).start()
            return

        try:
            update_key_points_status(note_id, KEY_POINTS_PROCESSING)
            response = requests.post(
                OLLAMA_CHAT_URL,
                headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "You are given a class recording transcript. Lines "
                                "are prefixed with the speaker who said them (e.g. "
                                "'Speaker 1: ...') when that information is "
                                "available; use it to attribute points to the "
                                "right speaker where relevant, but don't let it "
                                "distract from summarizing the content. Respond "
                                "with ONLY a JSON object of the form "
                                '{"title": "short descriptive title (max 8 words)", '
                                '"key_points": "markdown notes summarizing the '
                                "transcript\"}. In key_points, use '## ' headings "
                                "to group related points into sections when the "
                                "transcript covers multiple topics, and '-' for "
                                "bullets under each heading. Nested bullets must be "
                                "indented by exactly 4 spaces per level (required "
                                "for the list to render as nested). Bold with "
                                "**text** where useful. No preamble or closing "
                                f"remarks.\n\nTranscript:\n{prompt_transcript}"
                            ),
                        }
                    ],
                    "format": "json",
                    "stream": False,
                },
                timeout=120,
            )

            response.raise_for_status()
            content = (
                response.json().get("message", {}).get("content", "") or ""
            ).strip()

            if not content:
                raise ValueError("Ollama returned an empty response.")

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                # Ollama sometimes emits backslashes that aren't valid JSON
                # escapes (e.g. LaTeX-style "\(" ). Escape stray backslashes
                # and retry instead of failing the whole extraction.
                sanitized = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", content)
                parsed = json.loads(sanitized)
            title = (parsed.get("title") or "").strip()
            key_points = (parsed.get("key_points") or "").strip()

            if not key_points:
                raise ValueError("Ollama returned no key points.")

            update_key_points_status(
                note_id,
                KEY_POINTS_COMPLETED,
                title=title[:200] or None,
                key_points=key_points,
                error=None,
            )

        except Exception as exc:
            db.session.rollback()
            error_message = str(exc).strip() or exc.__class__.__name__
            update_key_points_status(
                note_id, KEY_POINTS_FAILED, error=error_message[:1000]
            )


def enqueue_transcription(note_id, audio_path):
    transcription_executor.submit(transcribe_note, note_id, audio_path)


def enqueue_existing_transcriptions():
    notes = Note.query.filter(
        Note.transcription_status.in_(
            [TRANSCRIPTION_PENDING, TRANSCRIPTION_PROCESSING]
        ),
        Note.recording_path.isnot(None),
    ).all()

    for note in notes:
        audio_path = os.path.join(BASE_DIR, note.recording_path)
        if os.path.exists(audio_path):
            enqueue_transcription(note.id, audio_path)
        else:
            note.transcription_status = TRANSCRIPTION_FAILED
            note.transcription_error = "Audio file not found."

    db.session.commit()


def enqueue_existing_key_points():
    notes = Note.query.filter(
        Note.transcription_status == TRANSCRIPTION_COMPLETED,
        Note.key_points_status.in_([KEY_POINTS_PENDING, KEY_POINTS_PROCESSING]),
    ).all()

    for note in notes:
        transcription_executor.submit(extract_key_points, note.id, note.transcription)
