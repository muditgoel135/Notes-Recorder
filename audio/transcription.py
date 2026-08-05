"""

This module handles the transcription of audio files into text, including speaker diarization and integration with Whisper and Ollama for processing notes and key points.

"""

# Import required modules
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import warnings
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import numpy as np
import requests

# Import core extensions, models, and services
from core.extensions import app, db
from core.models import Note, Speaker, SPEAKER_COLOR_PALETTE
from services.note_images import collect_ollama_note_images
from services.text_filters import rich_note_html_to_text
from services.video_embeds import (
    extract_video_embeds,
    format_video_transcripts,
    process_video_embeds,
)

# Import core.config constants
from core.config import (
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

STAGE_TRANSCRIBING = "transcribing"
STAGE_DIARIZING = "diarizing"

DIARIZATION_START_PERCENT = 90
DIARIZATION_END_PERCENT = 99

transcription_executor = ThreadPoolExecutor(max_workers=1)
whisper_model = None
whisper_model_lock = threading.Lock()

diarization_pipeline = None
diarization_pipeline_lock = threading.Lock()

_ffmpeg_dll_handles = []


def register_ffmpeg_dll_directories():
    """
    Register FFmpeg's shared-library directory so torchcodec/pyannote.audio can
    load their native DLLs on Windows.

    Since Python 3.8, ctypes.CDLL loads libraries with
    LOAD_LIBRARY_SEARCH_DEFAULT_DIRS, which does NOT include PATH. torchcodec
    therefore cannot find the FFmpeg DLLs (avcodec-*.dll, ...) shipped by the
    "full-shared" FFmpeg build just because they are on PATH. Registering the
    directory with os.add_dll_directory() makes those DLLs discoverable and
    silences the "torchcodec is not installed correctly" warning.
    """

    if os.name != "nt":
        return

    candidates = []
    for dir_path in os.environ.get("PATH", "").split(os.pathsep):
        if not dir_path or not os.path.isdir(dir_path):
            continue
        if any(fname.startswith("avcodec-") for fname in os.listdir(dir_path)):
            candidates.append(dir_path)

    if not candidates:
        packages_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages"
        )

        try:
            for entry in os.listdir(packages_dir):
                if entry.startswith("Gyan.FFmpeg.Shared_"):
                    shared_root = os.path.join(packages_dir, entry)
                    for sub in os.listdir(shared_root):
                        if sub.endswith("full_build-shared"):
                            candidates.append(os.path.join(shared_root, sub, "bin"))
        except OSError:
            pass

    for candidate in candidates:
        try:
            _ffmpeg_dll_handles.append(os.add_dll_directory(candidate))
        except (OSError, ValueError):
            pass


def is_internet_available(host="8.8.8.8", port=53, timeout=3):
    """
    Check whether the machine has outbound internet connectivity.

    Attempts to open a TCP connection to the given host and port within the
    specified timeout. Defaults to Google's public DNS server (8.8.8.8) on
    port 53 which is commonly reachable when internet access is available.

    :param host: Remote host to connect to (default: "8.8.8.8").
    :type host: str
    :param port: Remote TCP port to connect to (default: 53).
    :type port: int
    :param timeout: Connection timeout in seconds (default: 3).
    :type timeout: float

    :return: True if a connection could be established, False otherwise.
    :rtype: bool
    """

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True

    except OSError:
        return False


def get_whisper_model():
    """
    Return the shared Whisper transcription model, loading it on first use.

    The model is loaded lazily and cached in the module-level whisper_model
    variable, guarded by a lock so concurrent callers only load it once.

    :return: The loaded Whisper model instance.
    """

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
    """
    Update the transcription state for a note.

    Retrieves the Note with the given note_id, updates its transcription status
    and optional transcription text, segments, or error message, commits the
    database session, and returns the updated Note instance.

    :param note_id: ID of the note to update.
    :param status: New transcription status value.
    :param transcription: Optional full transcription text.
    :param segments: Optional transcription segments metadata.
    :param error: Optional transcription error message.
    :return: Updated Note instance, or None if note_id was not found.
    :rtype: Note or None
    """

    note = db.session.get(Note, note_id)
    if not note:
        return None

    note.transcription_status = status
    if status == TRANSCRIPTION_COMPLETED:
        note.transcription_progress = 100
        note.transcription_stage = None

    elif status == TRANSCRIPTION_FAILED:
        note.transcription_stage = None

    if transcription is not None:
        note.transcription = transcription

    if segments is not None:
        note.transcription_segments = segments

    note.transcription_error = error
    db.session.commit()
    return note


def update_transcription_progress(note_id, progress, stage=None):
    """
    Update the transcription progress percentage for a note.

    Retrieves the Note with the given note_id, updates its transcription
    progress and optionally its transcription stage, commits the database
    session, and returns the updated Note instance.

    :param note_id: ID of the note to update.
    :type note_id: int
    :param progress: New transcription progress percentage (0-100).
    :type progress: int
    :param stage: Optional transcription stage name (e.g. "transcribing").
    :type stage: str or None
    :return: Updated Note instance, or None if note_id was not found.
    :rtype: Note or None
    """

    note = db.session.get(Note, note_id)
    if not note:
        return None

    note.transcription_progress = progress
    if stage is not None:
        note.transcription_stage = stage
    db.session.commit()
    return note


@contextmanager
def track_whisper_progress(note_id):
    """
    Patch whisper's internal tqdm progress bar to persist percent-complete
    onto the note, so the UI can render a live progress bar during transcription.

    Whisper only exposes progress through a tqdm instance tracking mel frames
    processed vs. total frames, with no callback hook, so we swap in a tqdm
    subclass for the duration of the transcribe() call to intercept updates.

    :param note_id: ID of the Note being transcribed
    :return: Context manager that patches whisper's tqdm and restores it on exit
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
        """
        Report Whisper's mel-frame progress as a transcription percentage.

        :param current_frames: Frames processed so far by the tqdm bar.
        :type current_frames: int
        :param total_frames: Total frames Whisper will process.
        :type total_frames: int
        :return: None
        :rtype: None
        """
        if not total_frames:
            return
        # Whisper owns the 0-90% range; the remaining 10% is reserved for
        # speaker diarization so it stays visible in the same progress bar.
        percent = min(
            DIARIZATION_START_PERCENT, int(current_frames / total_frames * 90)
        )
        now = time.monotonic()
        if percent == last_reported["percent"] or now - last_reported["time"] < 1:
            return
        last_reported["percent"] = percent
        last_reported["time"] = now
        update_transcription_progress(note_id, percent)

    real_tqdm_cls = whisper_transcribe_module.tqdm.tqdm

    class ReportingTqdm(real_tqdm_cls):
        """
        tqdm subclass that reports progress to the note while updating.
        """

        def update(self, n=1):
            """
            Intercept tqdm updates to persist whisper's progress percentage.

            :param n: Number of frames reported as processed.
            :type n: int
            :return: None
            :rtype: None
            """
            super().update(n)
            report(self.n, self.total)

    class TqdmModuleShim:
        """
        Module-like shim exposing the progress-reporting tqdm class.
        """

        tqdm = ReportingTqdm

    original_tqdm_module = whisper_transcribe_module.tqdm
    whisper_transcribe_module.tqdm = TqdmModuleShim
    try:
        yield
    finally:
        whisper_transcribe_module.tqdm = original_tqdm_module


def update_key_points_status(
    note_id, status, title=None, key_points=None, error=None, generation=None
):
    """
    Update the key points state for a note.

    Retrieves the Note with the given note_id and updates its key points
    status, optional title, key points text, error message, and generation
    number. The generation guard prevents stale background jobs from
    overwriting newer key points.

    :param note_id: ID of the note to update.
    :type note_id: int
    :param status: New key points status value.
    :type status: str
    :param title: Optional new title for the note.
    :type title: str or None
    :param key_points: Optional new key points markdown text.
    :type key_points: str or None
    :param error: Optional key points error message.
    :type error: str or None
    :param generation: Key points generation this update belongs to.
    :type generation: int or None
    :return: Updated Note instance, or None if note_id was not found or the
        generation is stale.
    :rtype: Note or None
    """

    note = db.session.get(Note, note_id)
    if not note:
        return None

    if generation is not None and note.key_points_generation != generation:
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
    """
    Run the audio through ffmpeg noise reduction and return the temp file path.

    Falls back to the original path if ffmpeg is missing or fails, since
    transcribing noisy audio is better than not transcribing at all.

    :param audio_path: Path to the original audio file
    :return: Path to the denoised audio file, or the original path on failure
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
                "highpass=f=100,afftdn=nf=-25",
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
    """
    Return the pyannote speaker diarization pipeline, loading it on first use.

    Loads lazily and caches the pipeline in the module-level variable, guarded
    by a lock. FFmpeg's shared-library directory is registered first so its
    native DLLs can be found on Windows.

    :return: The loaded pyannote diarization Pipeline instance.
    """

    global diarization_pipeline
    if diarization_pipeline is None:
        with diarization_pipeline_lock:
            if diarization_pipeline is None:
                register_ffmpeg_dll_directories()
                from pyannote.audio import Pipeline

                diarization_pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    token=HUGGINGFACE_TOKEN,
                )

    return diarization_pipeline


def load_waveform(audio_path):
    """
    Load a mono PCM WAV file into a pyannote-compatible waveform dict.

    Reads the file directly with the stdlib wave module instead of handing
    the path to pyannote, since torchcodec (pyannote's default audio
    backend) frequently fails to load its native libraries on Windows.

    :param audio_path: Path to a mono PCM WAV file
    :return: Dict with "waveform" (torch.Tensor) and "sample_rate"
    """

    import torch

    with wave.open(audio_path, "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        raw_audio = wav_file.readframes(wav_file.getnframes())

    samples = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
    waveform = torch.from_numpy(samples).unsqueeze(0)
    return {"waveform": waveform, "sample_rate": sample_rate}


def diarize_audio(audio_path, progress_callback=None):
    """
    Return a list of (start, end, raw_speaker_label) turns, or None if unavailable.

    Diarization is best-effort: a missing token, missing dependency, or a
    pipeline failure all fall back to an undifferentiated transcript rather
    than failing the whole transcription.

    :param audio_path: Path to a mono PCM WAV file
    :param progress_callback: Optional callable invoked with an integer in the
        90-99 range as the pyannote pipeline progresses, mirroring the slice of
        the transcription progress bar reserved for diarization.
    :return: List of (start, end, raw_speaker_label) tuples, or None if unavailable
    """

    if not HUGGINGFACE_TOKEN:
        return None

    try:
        pipeline = get_diarization_pipeline()

        hook = None
        if progress_callback is not None:
            last_reported = {"percent": -1, "time": 0.0}

            def hook(step_name, artifact, file=None, total=None, completed=None):
                """
                Report pyannote's pipeline progress to the progress callback.

                :param step_name: Name of the pipeline step being executed.
                :type step_name: str
                :param artifact: Artifact produced by the pipeline step.
                :type artifact: object
                :param file: File being processed.
                :type file: object or None
                :param total: Total number of units in the step.
                :type total: int or None
                :param completed: Number of units completed in the step.
                :type completed: int or None
                :return: None
                :rtype: None
                """

                if total is None or not total:
                    return
                ratio = min(1.0, (completed or 0) / total)
                percent = min(
                    DIARIZATION_END_PERCENT,
                    DIARIZATION_START_PERCENT
                    + int(
                        ratio * (DIARIZATION_END_PERCENT - DIARIZATION_START_PERCENT)
                    ),
                )

                now = time.monotonic()
                if (
                    percent == last_reported["percent"]
                    and now - last_reported["time"] < 1
                ):
                    return

                last_reported["percent"] = percent
                last_reported["time"] = now
                progress_callback(percent)

        with warnings.catch_warnings():
            # pyannote's StatisticsPooling computes a corrected std over each
            # speaker segment; segments lasting a single frame trigger a
            # harmless "degrees of freedom is <= 0" UserWarning.
            warnings.filterwarnings(
                "ignore",
                message=r"std\(\): degrees of freedom is <= 0",
                category=UserWarning,
            )
            output = pipeline(load_waveform(audio_path), hook=hook)
        diarization = getattr(output, "speaker_diarization", output)
        return [
            (turn.start, turn.end, label)
            for turn, _, label in diarization.itertracks(yield_label=True)
        ]

    except Exception:
        return None


def assign_speakers(words, turns):
    """
    Tag each word dict in-place with a 0-based "spk" index and return the
    number of distinct speakers, based on diarization turns.

    :param words: List of dicts with "s" (start time) and "w" (word) keys
    :param turns: List of (start, end, raw_speaker_label) tuples
    :return: Number of distinct speakers
    """

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
    """
    Transcribe an audio file for a note and extract key points.

    Denoises the audio, runs it through Whisper (with speaker diarization when
    available), persists the transcript and per-word segments, then hands off
    to extract_key_points. Runs inside the app context and updates the note's
    transcription status on success or failure.

    :param note_id: ID of the note to transcribe.
    :type note_id: int
    :param audio_path: Path to the audio file to transcribe.
    :type audio_path: str
    :return: None
    :rtype: None
    """

    with app.app_context():
        denoised_path = audio_path
        try:
            note = update_transcription_status(note_id, TRANSCRIPTION_PROCESSING)
            if not note:
                return
            update_transcription_progress(note_id, 0, stage=STAGE_TRANSCRIBING)

            denoised_path = denoise_audio(audio_path)

            transcribe_kwargs = {
                "fp16": False,
                "word_timestamps": True,
                "verbose": False,
            }

            if note.subject == HINDI_SUBJECT:
                transcribe_kwargs["language"] = "hi"
                transcribe_kwargs["initial_prompt"] = HINDI_INITIAL_PROMPT
                transcribe_kwargs["beam_size"] = 5

            with track_whisper_progress(note_id):
                result = get_whisper_model().transcribe(
                    denoised_path, **transcribe_kwargs
                )

            transcription = (result.get("text") or "").strip()
            words = [
                {"s": word["start"], "w": word["word"]}
                for segment in result.get("segments") or []
                for word in segment.get("words") or []
            ]

            if words:
                update_transcription_progress(
                    note_id, DIARIZATION_START_PERCENT, stage=STAGE_DIARIZING
                )
                turns = diarize_audio(
                    denoised_path,
                    progress_callback=lambda percent: update_transcription_progress(
                        note_id, percent, stage=STAGE_DIARIZING
                    ),
                )
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

        note = db.session.get(Note, note_id)
        extract_key_points(
            note_id,
            transcription,
            note.key_points_generation if note else 0,
        )


def format_transcript_with_speakers(note):
    """
    Render transcription_segments as "Speaker N: ..." lines per turn.

    Falls back to the plain transcript when there's no per-word speaker
    data (diarization disabled/unavailable), so the Ollama prompt still
    gets a usable transcript either way.

    :param note: Note instance with transcription_segments and speakers_by_order()
    :return: Formatted transcript string
    """

    words = (
        json.loads(note.transcription_segments) if note.transcription_segments else []
    )

    if not words or all(word.get("spk") is None for word in words):
        return note.transcription or ""

    speakers = note.speakers_by_order()

    def speaker_name(spk):
        """
        Resolve a 0-based speaker index to a display name.

        :param spk: 0-based speaker index.
        :type spk: int or None
        :return: Display name for the speaker.
        :rtype: str
        """
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


def is_key_points_generation_current(note_id, generation):
    """
    Check whether the note's key points generation matches the given value.

    :param note_id: ID of the note to check.
    :type note_id: int
    :param generation: Key points generation value to compare against.
    :type generation: int
    :return: True if the note exists and its generation matches, False otherwise.
    :rtype: bool
    """

    note = db.session.get(Note, note_id)
    return bool(note and note.key_points_generation == generation)


def has_speaker_annotations(note):
    """
    Whether the note's transcription segments carry per-word speaker labels.

    When diarization is available, format_transcript_with_speakers() returns
    only the speaker-labeled recording words, so embedded-video transcripts
    must be appended to the model prompt separately.

    :param note: Note instance with transcription_segments.
    :return: True if any word has a "spk" annotation.
    """

    words = (
        json.loads(note.transcription_segments) if note.transcription_segments else []
    )

    return bool(words) and any(word.get("spk") is not None for word in words)


def extract_key_points(note_id, transcript, generation=None):
    """
    Generate a title and key points for a note using Ollama.

    Builds a prompt from the user's notes, the transcript (with speaker labels
    and embedded video transcripts when available), and any extracted images,
    then posts it to Ollama. Waits for an internet connection when needed and
    guards against stale generations. Runs inside the app context.

    :param note_id: ID of the note to update.
    :type note_id: int
    :param transcript: The transcription text to summarize.
    :type transcript: str
    :param generation: Key points generation this run belongs to.
    :type generation: int or None
    :return: None
    :rtype: None
    """

    with app.app_context():
        note = db.session.get(Note, note_id)
        if not note:
            return

        if generation is None:
            generation = note.key_points_generation or 0

        if note.key_points_generation != generation:
            return

        if not transcript and not (
            note.notes_html and extract_video_embeds(note.notes_html)
        ):
            update_key_points_status(
                note_id,
                KEY_POINTS_FAILED,
                error="No transcript to summarize.",
                generation=generation,
            )
            return

        user_notes = rich_note_html_to_text(note.notes_html)

        if not OLLAMA_API_KEY:
            update_key_points_status(
                note_id,
                KEY_POINTS_FAILED,
                error="OLLAMA_API_KEY is not configured.",
                generation=generation,
            )

            return

        if not is_internet_available():
            update_key_points_status(
                note_id,
                KEY_POINTS_PENDING,
                error="Waiting for an internet connection to reach Ollama.",
                generation=generation,
            )

            threading.Timer(
                KEY_POINTS_RETRY_SECONDS,
                lambda: transcription_executor.submit(
                    extract_key_points, note_id, transcript, generation
                ),
            ).start()

            return

        try:
            update_key_points_status(
                note_id, KEY_POINTS_PROCESSING, generation=generation
            )

            # Download embedded YouTube/Vimeo videos, transcribe their audio,
            # and extract keyframes to attach to the model request.
            video_images = []
            video_transcript_text = ""
            try:
                video_images = process_video_embeds(note)
                video_transcript_text = format_video_transcripts(note)

            except Exception:
                video_images = []

            if (
                not (note.transcription or "").strip()
                and not (transcript or "").strip()
            ):
                update_key_points_status(
                    note_id,
                    KEY_POINTS_FAILED,
                    error="No transcript to summarize.",
                    generation=generation,
                )
                return

            prompt_transcript = (
                format_transcript_with_speakers(note) if note else transcript
            )

            context_parts = []
            if user_notes:
                context_parts.append(f"User notes:\n{user_notes}")

            context_parts.append(f"Transcript:\n{prompt_transcript}")
            # When diarization is available the speaker-labeled transcript above
            # omits the merged video text, so append it separately.
            if video_transcript_text and has_speaker_annotations(note):
                context_parts.append(
                    f"Embedded video transcripts:\n{video_transcript_text}"
                )

            message = {
                "role": "user",
                "content": (
                    "You are given a class recording transcript. Lines "
                    "are prefixed with the speaker who said them (e.g. "
                    "'Speaker 1: ...') when that information is "
                    "available; use it to attribute points to the "
                    "right speaker where relevant, but don't let it "
                    "distract from summarizing the content. Embedded "
                    "video transcripts, when present, describe videos "
                    "linked in the user's notes and are equally part of "
                    "the lesson. Respond "
                    "with ONLY a JSON object of the form "
                    '{"title": "short descriptive title (max 8 words)", '
                    '"key_points": "markdown notes summarizing the '
                    "transcript\"}. In key_points, use '## ' headings "
                    "to group related points into sections when the "
                    "transcript covers multiple topics, and '-' for "
                    "bullets under each heading. Nested bullets must be "
                    "indented by exactly 4 spaces per level (required "
                    "for the list to render as nested). Bold with "
                    "**text** where useful. Treat the user's notes as "
                    "important context that may clarify, correct, or "
                    "prioritize parts of the transcript. Images attached "
                    "to this message are keyframes extracted from embedded "
                    "videos or images from the user's notes. "
                    "No preamble or "
                    f"closing remarks.\n\n{chr(10).join(context_parts)}"
                ),
            }
            note_images = collect_ollama_note_images([note])
            for image in video_images:
                if image not in note_images:
                    note_images.append(image)
            if note_images:
                message["images"] = note_images
            response = requests.post(
                OLLAMA_CHAT_URL,
                headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [message],
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

            if not is_key_points_generation_current(note_id, generation):
                return

            update_key_points_status(
                note_id,
                KEY_POINTS_COMPLETED,
                title=title[:200] or None,
                key_points=key_points,
                error=None,
                generation=generation,
            )

        except Exception as exc:
            db.session.rollback()
            if not is_key_points_generation_current(note_id, generation):
                return
            error_message = str(exc).strip() or exc.__class__.__name__

            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                try:
                    error_message = exc.response.json().get("error") or error_message
                except (ValueError, AttributeError):
                    pass

            update_key_points_status(
                note_id,
                KEY_POINTS_FAILED,
                error=error_message[:1000],
                generation=generation,
            )


def enqueue_transcription(note_id, audio_path):
    """
    Schedule a note for transcription on the background executor.

    :param note_id: ID of the note to transcribe.
    :type note_id: int
    :param audio_path: Path to the audio file to transcribe.
    :type audio_path: str
    :return: None
    :rtype: None
    """

    transcription_executor.submit(transcribe_note, note_id, audio_path)


def enqueue_existing_transcriptions():
    """
    Re-enqueue transcription for notes stuck in a pending or processing state.

    Iterates over notes whose transcription is pending or processing, enqueues
    them when the recording file still exists, and otherwise marks them as
    failed with an "Audio file not found." error.

    :return: None
    :rtype: None
    """

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
    """
    Re-enqueue key point extraction for completed notes still pending.

    Finds notes whose transcription is completed but key points are pending or
    processing, and schedules extract_key_points for each on the background
    executor.

    :return: None
    :rtype: None
    """

    notes = Note.query.filter(
        Note.transcription_status == TRANSCRIPTION_COMPLETED,
        Note.key_points_status.in_([KEY_POINTS_PENDING, KEY_POINTS_PROCESSING]),
    ).all()

    for note in notes:
        transcription_executor.submit(
            extract_key_points,
            note.id,
            note.transcription,
            note.key_points_generation or 0,
        )
