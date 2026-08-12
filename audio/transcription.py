"""

This module orchestrates the transcription pipeline for audio files: it
schedules transcription jobs, runs Whisper transcription with speaker
diarization, and hands off to key-point extraction via Ollama.

The heavy lifting lives in audio.audio_processing (model loading, audio
preparation, diarization, progress tracking) and audio.key_points (Ollama
title/key-point generation); this module re-exports their public names so
existing import paths keep working.

"""

# Import required modules
import json
import os
from concurrent.futures import ThreadPoolExecutor

# Import core extensions and models
from core.extensions import app, db
from core.models import Note, Speaker, SPEAKER_COLOR_PALETTE

# Import core.config constants
from core.config import (
    BASE_DIR,
    HINDI_SUBJECT,
    HINDI_INITIAL_PROMPT,
    TRANSCRIPTION_PENDING,
    TRANSCRIPTION_PROCESSING,
    TRANSCRIPTION_COMPLETED,
    TRANSCRIPTION_FAILED,
    KEY_POINTS_PENDING,
    KEY_POINTS_PROCESSING,
    KEY_POINTS_FAILED,
)

# Import audio-side transcription pipeline helpers
from audio.audio_processing import (
    STAGE_TRANSCRIBING,
    STAGE_DIARIZING,
    DIARIZATION_START_PERCENT,
    DIARIZATION_END_PERCENT,
    register_ffmpeg_dll_directories,
    is_internet_available,
    get_whisper_model,
    update_transcription_status,
    update_transcription_progress,
    track_whisper_progress,
    prepare_audio_for_transcription,
    apply_silence_trimming,
    get_diarization_pipeline,
    load_waveform,
    diarize_audio,
    assign_speakers,
)

# Import key-point extraction helpers
from audio.key_points import (
    update_key_points_status,
    format_transcript_with_speakers,
    is_key_points_generation_current,
    has_speaker_annotations,
    extract_key_points,
)

# Import video embed helpers for key points extraction
from services.video_embeds import extract_video_embeds

transcription_executor = ThreadPoolExecutor(max_workers=1)


def transcribe_note(note_id, audio_path):
    """
    Transcribe an audio file for a note and extract key points.

    Converts the audio to 16 kHz mono, runs it through Whisper (with speaker
    diarization when available), persists the transcript and per-word
    segments, then hands off to extract_key_points. Runs inside the app
    context and updates the note's transcription status on success or failure.

    :param note_id: ID of the note to transcribe.
    :type note_id: int
    :param audio_path: Path to the audio file to transcribe.
    :type audio_path: str
    :return: None
    :rtype: None
    """

    with app.app_context():
        processed_path = audio_path
        transcription = ""
        try:
            note = update_transcription_status(note_id, TRANSCRIPTION_PROCESSING)
            if not note:
                return
            update_transcription_progress(note_id, 0, stage=STAGE_TRANSCRIBING)

            processed_path = prepare_audio_for_transcription(audio_path)
            processed_path, trim_offset, has_speech = apply_silence_trimming(
                processed_path,
                remove_source=processed_path != audio_path,
            )

            words = []
            if has_speech:
                transcribe_kwargs = {
                    "fp16": False,
                    "word_timestamps": True,
                    "verbose": False,
                    # Decode each window independently so a hallucination on a
                    # noisy stretch doesn't cascade through the whole recording.
                    "condition_on_previous_text": False,
                }

                if note.subject == HINDI_SUBJECT:
                    transcribe_kwargs["language"] = "hi"
                    transcribe_kwargs["initial_prompt"] = HINDI_INITIAL_PROMPT
                    transcribe_kwargs["beam_size"] = 5
                else:
                    # Force English so a noisy opening window can't misdirect
                    # Whisper's language detection and bias the whole recording.
                    transcribe_kwargs["language"] = "en"

                with track_whisper_progress(note_id):
                    result = get_whisper_model().transcribe(
                        processed_path, **transcribe_kwargs
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
                        processed_path,
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

                    # Silence trimming made Whisper's timestamps relative to
                    # the trimmed audio; shift them back into the original
                    # recording's time domain so transcript words stay
                    # aligned with audio playback and bookmarks.
                    if trim_offset:
                        for word in words:
                            word["s"] = round(word["s"] + trim_offset, 3)

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
            if processed_path != audio_path and os.path.exists(processed_path):
                os.remove(processed_path)

        note = db.session.get(Note, note_id)
        generation = note.key_points_generation if note else 0
        has_video_embeds = bool(
            note and note.notes_html and extract_video_embeds(note.notes_html)
        )
        if not has_speech and not transcription and not has_video_embeds:
            update_key_points_status(
                note_id,
                KEY_POINTS_FAILED,
                error="The recording contains no speech to summarize.",
                generation=generation,
            )
        else:
            extract_key_points(note_id, transcription, generation)


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
