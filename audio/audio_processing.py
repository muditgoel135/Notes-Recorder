"""

This module handles the audio-side transcription pipeline: loading the Whisper
and pyannote models, preparing audio for transcription, tracking progress, and
persisting transcription status to the database.

"""

# Import required modules
import bisect
import os
import socket
import subprocess
import tempfile
import threading
import time
import warnings
import wave
from collections.abc import Callable
from contextlib import contextmanager
import numpy as np

# Import core extensions and models
from core.extensions import app, db
from core.models import Note
from services.notes_query import refresh_note_search_index

# Import core.config constants
from core.config import (
    WHISPER_MODEL_NAME,
    HUGGINGFACE_TOKEN,
    TRANSCRIPTION_COMPLETED,
    TRANSCRIPTION_FAILED,
    RNNOISE_MODEL,
    DIARIZATION_MAX_SPEAKERS,
)

STAGE_TRANSCRIBING: str = "transcribing"
STAGE_DIARIZING: str = "diarizing"

DIARIZATION_START_PERCENT: int = 90
DIARIZATION_END_PERCENT: int = 99

whisper_model = None
whisper_model_lock: threading.Lock = threading.Lock()

diarization_pipeline = None
diarization_pipeline_lock: threading.Lock = threading.Lock()

_ffmpeg_dll_handles: list = []


def register_ffmpeg_dll_directories() -> None:
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


def is_internet_available(
    host: str = "8.8.8.8", port: int = 53, timeout: float = 3
) -> bool:
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
    note_id: int,
    status: str,
    transcription: str | None = None,
    segments: str | None = None,
    error: str | None = None,
) -> Note | None:
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
    refresh_note_search_index(note)
    db.session.commit()
    return note


def update_transcription_progress(
    note_id: int, progress: int, stage: str | None = None
) -> Note | None:
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
    setattr(whisper_transcribe_module, "tqdm", TqdmModuleShim)
    try:
        yield
    finally:
        setattr(whisper_transcribe_module, "tqdm", original_tqdm_module)


def denoise_audio_file(audio_path: str) -> str:
    """
    Reduce steady background noise (e.g. fan or AC hum) with the RNNoise
    ``arnndn`` filter using a pretrained model.

    The neural ``arnndn`` filter preserves speech while suppressing stationary
    noise. An FFT-style filter like ffmpeg's ``afftdn`` was found to destroy
    speech in noisy classroom sections, so none is applied. Denoising is
    best-effort: a missing model file or a failed filter pass leaves the
    source audio untouched so the caller's downstream processing proceeds.

    :param audio_path: Path to a 16 kHz mono PCM WAV file.
    :return: Path to a denoised temp WAV, or audio_path when denoising is
        unavailable or fails.
    """

    if not RNNOISE_MODEL or not os.path.isfile(RNNOISE_MODEL):
        return audio_path

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
                audio_path,
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
        return audio_path

    return denoised_path


def prepare_audio_for_transcription(audio_path: str) -> str:
    """
    Convert the audio to a 16 kHz mono WAV and return the temp file path.

    Converts, resamples, and downmixes with ffmpeg, then reduces steady
    background noise (e.g. fan or AC hum) with ``denoise_audio_file`` (RNNoise
    ``arnndn``). Whisper transcribes raw, unaltered audio markedly better than
    spectrally filtered audio, which is why the neural ``arnndn`` filter is
    used rather than an FFT-style filter; denoising stays best-effort so
    transcription always proceeds even when it's unavailable.

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

    denoised_path = denoise_audio_file(wav_path)
    if denoised_path == wav_path:
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
                from pyannote.audio import Pipeline  # type: ignore[import-untyped]

                diarization_pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    token=HUGGINGFACE_TOKEN,
                )

    return diarization_pipeline


def load_waveform(audio_path: str) -> dict:
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


def diarize_audio(
    audio_path: str, progress_callback: "Callable | None" = None
) -> list[tuple[float, float, str]] | None:
    """
    Return a list of (start, end, raw_speaker_label) turns, or None if unavailable.

    The input audio is denoised with ``denoise_audio_file`` before it reaches
    the pipeline, so diarization never runs on raw classroom audio (in the
    normal transcription flow the file was already denoised during audio prep,
    making this a second, near-identical arnndn pass — harmless, since arnndn
    passes speech through close to untouched). Speaker attribution is capped
    at DIARIZATION_MAX_SPEAKERS so pyannote can't invent phantom speakers.

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

    denoised_path = denoise_audio_file(audio_path)
    try:
        pipeline = get_diarization_pipeline()

        hook: Callable[..., None] | None = None
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
                    or now - last_reported["time"] < 1
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
            output = pipeline(
                load_waveform(denoised_path),
                hook=hook,
                max_speakers=DIARIZATION_MAX_SPEAKERS,
            )
        diarization = getattr(output, "speaker_diarization", output)
        return [
            (turn.start, turn.end, label)
            for turn, _, label in diarization.itertracks(yield_label=True)
        ]

    except Exception:
        return None

    finally:
        if denoised_path != audio_path and os.path.exists(denoised_path):
            os.remove(denoised_path)


def assign_speakers(words: list[dict], turns: list[tuple[float, float, str]]) -> int:
    """
    Tag each word dict in-place with a 0-based "spk" index and return the
    number of distinct speakers, based on diarization turns.

    Turns are searched with a bisect over their start times instead of a
    linear scan, so long recordings with many turns stay fast. A word outside
    every turn still falls back to its nearest turn edge.

    :param words: List of dicts with "s" (start time) and "w" (word) keys
    :param turns: List of (start, end, raw_speaker_label) tuples
    :return: Number of distinct speakers
    """

    order_map = {}
    for _, _, label in turns:
        if label not in order_map:
            order_map[label] = len(order_map)

    sorted_turns = sorted(turns, key=lambda turn: turn[0])
    turn_starts = [turn[0] for turn in sorted_turns]
    turn_ends = [turn[1] for turn in sorted_turns]

    for word in words:
        start = word["s"]
        index = bisect.bisect_right(turn_starts, start) - 1
        if index >= 0 and start <= turn_ends[index]:
            speaker_label = sorted_turns[index][2]
        else:
            nearest = min(
                turns, key=lambda turn: min(abs(turn[0] - start), abs(turn[1] - start))
            )
            speaker_label = nearest[2]

        word["spk"] = order_map[speaker_label]

    return len(order_map)


VAD_FRAME_SECONDS = 0.03
VAD_HOP_SECONDS = 0.01
VAD_SILENCE_MARGIN = 0.15


def _read_wav_samples(wav_path: str) -> tuple[np.ndarray | None, int | None]:
    """
    Read a PCM WAV file into an int16 numpy array and its sample rate.

    :param wav_path: Path to a PCM WAV file.
    :type wav_path: str
    :return: A tuple of (samples, sample_rate), or (None, None) when the file
        is not a readable 16-bit PCM WAV.
    :rtype: tuple of (numpy.ndarray, int) or (None, None)
    """

    try:
        with wave.open(wav_path, "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            width = wav_file.getsampwidth()
            if sample_rate <= 0 or channels <= 0 or width != 2:
                return None, None
            raw_audio = wav_file.readframes(wav_file.getnframes())

    except (wave.Error, EOFError, OSError):
        return None, None

    samples = np.frombuffer(raw_audio, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)

    return samples, sample_rate


def _detect_speech_bounds(
    samples: np.ndarray, sample_rate: int
) -> tuple[float, float] | None:
    """
    Return the first and last speech timestamps in an int16 sample array.

    Frames are scored by RMS energy with an adaptive threshold derived from
    the recording's own noise floor and peak level, so quiet but genuine
    speech is still detected. Frames are processed in bounded-memory chunks
    (cumulative sums of squared samples) so long recordings don't allocate
    oversized arrays.

    :param samples: int16 numpy array of audio samples.
    :type samples: numpy.ndarray
    :param sample_rate: Sample rate in Hz.
    :type sample_rate: int
    :return: A (start, end) tuple of speech bounds in seconds, or None when
        no speech was detected.
    :rtype: tuple of (float, float) or None
    """

    frame_size = max(1, int(sample_rate * VAD_FRAME_SECONDS))
    hop_size = max(1, int(sample_rate * VAD_HOP_SECONDS))
    if len(samples) < frame_size:
        return None

    window_size = sample_rate * 30
    rms_parts = []
    for chunk_start in range(0, len(samples), window_size):
        chunk = samples[chunk_start : chunk_start + window_size]
        squared = chunk.astype(np.float32)
        np.multiply(squared, squared, out=squared)
        cumulative = np.empty(len(squared) + 1, dtype=np.float64)
        cumulative[0] = 0
        np.cumsum(squared, out=cumulative[1:])
        indices = np.arange(0, len(squared) - frame_size + 1, hop_size)
        if indices.size == 0:
            continue
        sums = cumulative[indices + frame_size] - cumulative[indices]
        rms_parts.append(np.sqrt(sums / frame_size))

    if not rms_parts:
        return None

    frame_rms = np.concatenate(rms_parts)
    noise_floor = float(np.percentile(frame_rms, 10))
    peak = float(np.percentile(frame_rms, 99))
    if peak <= 1e-6:
        return None

    threshold = max(noise_floor * 6.0, peak * 0.08)
    threshold = min(threshold, peak * 0.35)

    speech_mask = frame_rms > threshold
    if not speech_mask.any():
        return None

    first_index = int(np.argmax(speech_mask))
    last_index = len(frame_rms) - 1 - int(np.argmax(speech_mask[::-1]))
    start = first_index * hop_size / sample_rate
    end = (last_index * hop_size + frame_size) / sample_rate
    return start, end


def _trim_wav(wav_path: str, start: float, end: float) -> str | None:
    """
    Trim a PCM WAV to the [start, end] second range with ffmpeg.

    :param wav_path: Path to the source PCM WAV.
    :type wav_path: str
    :param start: Seconds into the source to start the trim.
    :type start: float
    :param end: Seconds into the source to end the trim.
    :type end: float
    :return: Path to the trimmed temp WAV, or None on failure.
    :rtype: str or None
    """

    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                wav_path,
                "-af",
                f"atrim=start={start:.3f}:end={end:.3f}",
                "-ar",
                "16000",
                "-ac",
                "1",
                out_path,
            ],
            check=True,
            capture_output=True,
        )

    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        if os.path.exists(out_path):
            os.remove(out_path)
        return None

    return out_path


def apply_silence_trimming(
    audio_path: str, remove_source: bool = False
) -> tuple[str, float, bool]:
    """
    Trim leading and trailing silence from a 16 kHz mono PCM WAV using a
    lightweight energy-based voice-activity detector.

    Whisper is slower and more prone to hallucinating when long stretches of
    dead air sit at the edges of a recording, so the detected speech span is
    kept with a small silence margin on either side. The trimmed audio is
    re-encoded losslessly (PCM to PCM), and Whisper's word timestamps become
    relative to the trimmed file, so callers must add the returned leading
    offset back when persisting segment times to keep them aligned with the
    original audio.

    :param audio_path: Path to a 16 kHz mono PCM WAV file.
    :type audio_path: str
    :param remove_source: Whether to delete audio_path when a trimmed copy is
        produced (safe only when audio_path is a temporary file).
    :type remove_source: bool
    :return: A tuple of (path, leading_offset, has_speech). path is the file
        to transcribe (a trimmed copy, or the input when nothing was
        trimmed), leading_offset is seconds of audio removed from the start,
        and has_speech is False when no speech was detected at all.
    :rtype: tuple of (str, float, bool)
    """

    samples, sample_rate = _read_wav_samples(audio_path)
    if samples is None or sample_rate is None:
        return audio_path, 0.0, True

    bounds = _detect_speech_bounds(samples, sample_rate)
    if bounds is None:
        return audio_path, 0.0, False

    start, end = bounds

    # The detected speech span is too short to be meaningful speech.
    if end - start < 0.2:
        return audio_path, 0.0, False

    total_duration = len(samples) / sample_rate
    trim_start = max(0.0, start - VAD_SILENCE_MARGIN)
    trim_end = min(total_duration, end + VAD_SILENCE_MARGIN)

    # Less than the margin is trimmed at each edge; not worth re-encoding.
    if trim_start < 0.15 and trim_end > total_duration - 0.15:
        return audio_path, 0.0, True

    trimmed_path = _trim_wav(audio_path, trim_start, trim_end)
    if trimmed_path is None:
        return audio_path, 0.0, True

    if remove_source:
        try:
            os.remove(audio_path)
        except OSError:
            pass

    return trimmed_path, trim_start, True
