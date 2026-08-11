"""

This module handles the audio-side transcription pipeline: loading the Whisper
and pyannote models, preparing audio for transcription, tracking progress, and
persisting transcription status to the database.

"""

# Import required modules
import os
import socket
import subprocess
import tempfile
import threading
import time
import warnings
import wave
from contextlib import contextmanager
import numpy as np

# Import core extensions and models
from core.extensions import app, db
from core.models import Note

# Import core.config constants
from core.config import (
    WHISPER_MODEL_NAME,
    HUGGINGFACE_TOKEN,
    TRANSCRIPTION_COMPLETED,
    TRANSCRIPTION_FAILED,
    RNNOISE_MODEL,
)

STAGE_TRANSCRIBING = "transcribing"
STAGE_DIARIZING = "diarizing"

DIARIZATION_START_PERCENT = 90
DIARIZATION_END_PERCENT = 99

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


def prepare_audio_for_transcription(audio_path):
    """
    Convert the audio to a 16 kHz mono WAV and return the temp file path.

    Converts, resamples, and downmixes with ffmpeg, then optionally reduces
    steady background noise (e.g. fan or AC hum) with the RNNoise ``arnndn``
    filter using a pretrained model. Whisper transcribes raw, unaltered audio
    markedly better than spectrally filtered audio — prior testing showed the
    old denoise chain (``highpass=f=100,afftdn=nf=-25``) destroyed the speech
    in noisy classroom sections, turning whole stretches of talk into silence
    or Whisper hallucinations — so no FFT-style filter is applied. The neural
    ``arnndn`` filter is used instead because it preserves speech while
    suppressing stationary noise, and denoising is best-effort: a missing
    model file or a failed filter pass leaves the plain converted WAV in place
    so transcription always proceeds.

    Falls back to the original path if ffmpeg is missing or fails, since
    transcribing the unprocessed audio is better than not transcribing at all.

    :param audio_path: Path to the original audio file
    :return: Path to the converted WAV file, or the original path on failure
    """

    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                audio_path,
                "-ar",
                "16000",
                "-ac",
                "1",
                wav_path,
            ],
            check=True,
            capture_output=True,
        )

    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        if os.path.exists(wav_path):
            os.remove(wav_path)
        return audio_path

    if not RNNOISE_MODEL or not os.path.isfile(RNNOISE_MODEL):
        return wav_path

    # The filter string can't hold the model's absolute path (a drive-letter
    # colon splits the filter options and backslashes are escape characters),
    # so run ffmpeg with the model's directory as the working directory and
    # reference the model by bare filename instead.
    fd, denoised_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                wav_path,
                "-af",
                f"arnndn=m={os.path.basename(RNNOISE_MODEL)}",
                # arnndn resamples to 48 kHz internally and outputs at that
                # rate, so resample back to 16 kHz mono for Whisper/pyannote.
                "-ar",
                "16000",
                "-ac",
                "1",
                denoised_path,
            ],
            check=True,
            capture_output=True,
            cwd=os.path.dirname(RNNOISE_MODEL),
        )

    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        if os.path.exists(denoised_path):
            os.remove(denoised_path)
        return wav_path

    os.remove(wav_path)
    return denoised_path


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
