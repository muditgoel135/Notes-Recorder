import json
import os

from audio import transcription
from core.config import TRANSCRIPTION_COMPLETED, TRANSCRIPTION_FAILED
from core.extensions import db
from core.models import Note, Speaker


def _note():
    note = Note(
        date="2026-09-03",
        time="10:00:00",
        start_time="10:00:00",
        end_time="10:05:00",
        subject="Physics",
        transcription_status="pending",
        key_points_status="pending",
    )
    db.session.add(note)
    db.session.commit()
    return note


def test_transcribe_note_persists_transcript_and_speakers(test_app, monkeypatch):
    with test_app.app_context():
        note = _note()
        monkeypatch.setattr(transcription, "app", test_app)
        monkeypatch.setattr(
            transcription,
            "prepare_audio_for_transcription",
            lambda path: path,
        )
        monkeypatch.setattr(
            transcription,
            "apply_silence_trimming",
            lambda path, remove_source=False: (path, 0.5, True),
        )
        monkeypatch.setattr(
            transcription,
            "track_whisper_progress",
            lambda note_id: __import__("contextlib").nullcontext(),
        )

        class Model:
            def transcribe(self, path, **kwargs):
                assert kwargs["language"] == "en"
                return {
                    "text": "hello world",
                    "segments": [
                        {
                            "words": [
                                {"start": 0.1, "word": "hello"},
                                {"start": 0.3, "word": "world"},
                            ]
                        }
                    ],
                }

        monkeypatch.setattr(transcription, "get_whisper_model", lambda: Model())
        monkeypatch.setattr(
            transcription,
            "diarize_audio",
            lambda path, progress_callback=None: [(0, 1, "speaker")],
        )
        monkeypatch.setattr(transcription, "extract_key_points", lambda *args: None)
        transcription.transcribe_note(note.id, "recording.wav")
        db.session.refresh(note)
        assert note.transcription_status == TRANSCRIPTION_COMPLETED
        assert note.transcription == "hello world"
        assert json.loads(note.transcription_segments)[0]["s"] == 0.6
        assert db.session.query(Speaker).filter_by(note_id=note.id).count() == 1


def test_transcribe_note_marks_failure_and_truncates_error(test_app, monkeypatch):
    with test_app.app_context():
        note = _note()
        monkeypatch.setattr(transcription, "app", test_app)
        monkeypatch.setattr(
            transcription,
            "prepare_audio_for_transcription",
            lambda path: (_ for _ in ()).throw(RuntimeError("x" * 2000)),
        )
        transcription.transcribe_note(note.id, "recording.wav")
        db.session.refresh(note)
        assert note.transcription_status == TRANSCRIPTION_FAILED
        assert len(note.transcription_error) == 1000


def test_existing_transcriptions_requeues_existing_and_fails_missing(
    test_app, tmp_path, monkeypatch
):
    with test_app.app_context():
        existing = _note()
        existing.recording_path = "recordings/existing.wav"
        missing = _note()
        missing.recording_path = "recordings/missing.wav"
        db.session.commit()
        (tmp_path / "recordings").mkdir()
        existing_path = tmp_path / "recordings" / "existing.wav"
        existing_path.write_bytes(b"audio")
        monkeypatch.setattr(transcription, "app", test_app)
        monkeypatch.setattr(transcription, "BASE_DIR", str(tmp_path))
        submitted = []
        monkeypatch.setattr(
            transcription.transcription_executor,
            "submit",
            lambda fn, *args, **kwargs: submitted.append((fn, args)),
        )
        transcription.enqueue_existing_transcriptions()
        db.session.refresh(missing)
        assert missing.transcription_status == TRANSCRIPTION_FAILED
        assert len(submitted) == 1
        assert submitted[0][0] is transcription.transcribe_note
        assert submitted[0][1][0] == existing.id
        assert os.path.normpath(submitted[0][1][1]) == os.path.normpath(
            str(existing_path)
        )
