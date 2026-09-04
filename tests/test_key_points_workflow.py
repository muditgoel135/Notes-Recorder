import json

from audio import key_points
from core.config import KEY_POINTS_COMPLETED, KEY_POINTS_FAILED
from core.extensions import db
from core.models import Note


def _note():
    note = Note(
        date="2026-09-03",
        time="10:00:00",
        start_time="10:00:00",
        end_time="10:05:00",
        subject="Physics",
        transcription="A transcript",
        transcription_status="completed",
        key_points_status="pending",
        key_points_generation=2,
    )
    db.session.add(note)
    db.session.commit()
    return note


def test_update_key_points_status_rejects_stale_generation(test_app):
    with test_app.app_context():
        note = _note()
        result = key_points.update_key_points_status(
            note.id,
            KEY_POINTS_COMPLETED,
            title="stale",
            key_points="- stale",
            generation=1,
        )
        assert result is None
        db.session.refresh(note)
        assert note.key_points_status == "pending"
        assert note.title is None


def test_update_key_points_status_persists_current_generation(test_app):
    with test_app.app_context():
        note = _note()
        result = key_points.update_key_points_status(
            note.id,
            KEY_POINTS_COMPLETED,
            title="Current",
            key_points="- point",
            generation=2,
        )
        assert result is not None
        db.session.refresh(note)
        assert note.title == "Current"
        assert note.key_points == "- point"
        assert note.key_points_error is None


def test_extract_key_points_fails_without_api_key(test_app, monkeypatch):
    with test_app.app_context():
        note = _note()
        monkeypatch.setattr(key_points, "app", test_app)
        monkeypatch.setattr(key_points, "OLLAMA_API_KEY", "")
        key_points.extract_key_points(note.id, note.transcription, generation=2)
        db.session.refresh(note)
        assert note.key_points_status == KEY_POINTS_FAILED
        assert note.key_points_error == "OLLAMA_API_KEY is not configured."


def test_extract_key_points_persists_successful_model_response(test_app, monkeypatch):
    with test_app.app_context():
        note = _note()
        monkeypatch.setattr(key_points, "app", test_app)
        monkeypatch.setattr(key_points, "OLLAMA_API_KEY", "test-key")
        monkeypatch.setattr(key_points, "is_internet_available", lambda: True)
        monkeypatch.setattr(key_points, "process_video_embeds", lambda note: [])
        monkeypatch.setattr(key_points, "collect_ollama_note_images", lambda notes: [])

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "message": {
                        "content": json.dumps(
                            {"title": "A title", "key_points": "- Important"}
                        )
                    }
                }

        captured = {}

        def fake_post(url, headers, payload):
            captured["payload"] = payload
            return Response()

        monkeypatch.setattr(key_points, "_post_ollama", fake_post)
        key_points.extract_key_points(note.id, note.transcription, generation=2)
        db.session.refresh(note)
        assert note.key_points_status == KEY_POINTS_COMPLETED
        assert note.title == "A title"
        assert note.key_points == "- Important"
        assert "Transcript:" in captured["payload"]["messages"][0]["content"]
