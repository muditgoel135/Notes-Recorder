"""

Integration tests for Flask route handlers.

"""

import json

from core.extensions import db
from core.models import Note, Subject, Tag, Unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_note(db_session, **overrides):
    """Create and persist a Note with sensible defaults."""
    defaults = dict(
        date="2026-08-20",
        time="10:00:00",
        start_time="10:00:00",
        end_time="10:05:00",
        subject="Physics",
        unit="General",
        transcription_status="pending",
        key_points_status="pending",
    )
    defaults.update(overrides)
    note = Note(**defaults)
    db_session.add(note)
    db_session.commit()
    return note


def _create_subject(db_session, name="Biology"):
    subject = Subject(name=name)
    db_session.add(subject)
    db_session.commit()
    return subject


def _create_tag(db_session, name="important", color="#ff0000"):
    tag = Tag(name=name, color=color)
    db_session.add(tag)
    db_session.commit()
    return tag


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------


def test_index_returns_200(test_app):
    client = test_app.test_client()
    response = client.get("/")
    assert response.status_code == 200


def test_index_with_search_filter(test_app):
    _create_note(db.session, title="Photosynthesis notes", transcription="biology content")
    client = test_app.test_client()
    response = client.get("/?q=Photosynthesis")
    assert response.status_code == 200
    assert b"Photosynthesis notes" in response.data


def test_index_with_subject_filter(test_app):
    _create_note(db.session, subject="Chemistry")
    _create_note(db.session, subject="Biology")
    client = test_app.test_client()
    response = client.get("/?subjects=Chemistry")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/notes
# ---------------------------------------------------------------------------


def test_api_notes_empty(test_app):
    client = test_app.test_client()
    response = client.get("/api/notes")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 0
    assert data["total_pages"] == 1


def test_api_notes_returns_notes(test_app):
    _create_note(db.session, title="Test Note")
    client = test_app.test_client()
    response = client.get("/api/notes")
    data = response.get_json()
    assert data["total"] == 1
    assert "html" in data


def test_api_notes_ids(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()
    response = client.get("/api/notes/ids")
    data = response.get_json()
    assert note.id in data["ids"]


# ---------------------------------------------------------------------------
# POST /api/note_images
# ---------------------------------------------------------------------------


def test_upload_note_image_no_file(test_app):
    client = test_app.test_client()
    response = client.post("/api/note_images")
    assert response.status_code == 400


def test_upload_note_image_bad_extension(test_app):
    client = test_app.test_client()
    data = {"image": (b"fake", "test.bmp")}
    response = client.post(
        "/api/note_images",
        data=data,
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /notes/<id>/tags
# ---------------------------------------------------------------------------


def test_set_note_tags(test_app):
    note = _create_note(db.session)
    tag = _create_tag(db.session)
    client = test_app.test_client()
    response = client.post(
        f"/notes/{note.id}/tags",
        json={"tag_ids": [tag.id]},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["tags"]) == 1
    assert data["tags"][0]["id"] == tag.id


def test_set_note_tags_invalid_ids(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()
    response = client.post(
        f"/notes/{note.id}/tags",
        json={"tag_ids": ["not_a_number"]},
    )
    assert response.status_code == 400


def test_set_note_tags_empty_list(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()
    response = client.post(
        f"/notes/{note.id}/tags",
        json={"tag_ids": []},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["tags"] == []


def test_set_note_tags_404(test_app):
    client = test_app.test_client()
    response = client.post(
        "/notes/99999/tags",
        json={"tag_ids": []},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /notes/<id>/subject
# ---------------------------------------------------------------------------


def test_update_note_subject(test_app):
    note = _create_note(db.session, subject="Physics")
    client = test_app.test_client()
    response = client.post(
        f"/notes/{note.id}/subject",
        json={"subject": "Chemistry"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["subject"] == "Chemistry"
    assert data["unit"] == "General"


def test_update_note_subject_empty(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()
    response = client.post(
        f"/notes/{note.id}/subject",
        json={"subject": ""},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /notes/<id>/pin
# ---------------------------------------------------------------------------


def test_toggle_note_pin(test_app):
    note = _create_note(db.session, pinned=False)
    client = test_app.test_client()
    response = client.post(f"/notes/{note.id}/pin")
    assert response.status_code == 200
    data = response.get_json()
    assert data["pinned"] is True


# ---------------------------------------------------------------------------
# POST /notes/<id>/datetime
# ---------------------------------------------------------------------------


def test_update_note_datetime(test_app):
    note = _create_note(db.session, start_time="10:00:00", end_time="10:05:00")
    client = test_app.test_client()
    response = client.post(
        f"/notes/{note.id}/datetime",
        json={"date": "2026-09-01", "start_time": "14:30"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["date"] == "2026-09-01"
    assert data["start_time"] == "14:30:00"


def test_update_note_datetime_invalid_date(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()
    response = client.post(
        f"/notes/{note.id}/datetime",
        json={"date": "bad-date", "start_time": "10:00"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /update_note/<id>
# ---------------------------------------------------------------------------


def test_update_note_title_and_key_points(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()
    response = client.post(
        f"/update_note/{note.id}",
        json={"title": "New Title", "key_points": "- Point one"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["message"] == "Note updated."


# ---------------------------------------------------------------------------
# POST /delete/<id>
# ---------------------------------------------------------------------------


def test_delete_note(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()
    response = client.post(
        f"/delete/{note.id}",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["message"] == "Note deleted."


def test_delete_note_redirects_for_non_ajax(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()
    response = client.post(f"/delete/{note.id}")
    assert response.status_code == 302


def test_delete_note_404(test_app):
    client = test_app.test_client()
    response = client.post(
        "/delete/99999",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /download_transcript / GET /download_key_points
# ---------------------------------------------------------------------------


def test_download_transcript(test_app):
    note = _create_note(db.session, transcription="Hello world transcript")
    client = test_app.test_client()
    response = client.get(f"/download_transcript/{note.id}")
    assert response.status_code == 200
    assert b"Hello world transcript" in response.data


def test_download_transcript_unavailable(test_app):
    note = _create_note(db.session, transcription=None)
    client = test_app.test_client()
    response = client.get(f"/download_transcript/{note.id}")
    assert response.status_code == 404


def test_download_key_points(test_app):
    note = _create_note(db.session, key_points="- Important point", title="My Title")
    client = test_app.test_client()
    response = client.get(f"/download_key_points/{note.id}")
    assert response.status_code == 200
    assert b"My Title" in response.data


def test_download_key_points_unavailable(test_app):
    note = _create_note(db.session, key_points=None)
    client = test_app.test_client()
    response = client.get(f"/download_key_points/{note.id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Subjects API
# ---------------------------------------------------------------------------


def test_api_subjects(test_app):
    _create_subject(db.session, "History")
    client = test_app.test_client()
    response = client.get("/api/subjects")
    data = response.get_json()
    assert any(s["name"] == "History" for s in data["subjects"])


def test_create_subject(test_app):
    client = test_app.test_client()
    response = client.post("/api/subjects", json={"name": "Art"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["subject"]["name"] == "Art"


def test_create_subject_empty_name(test_app):
    client = test_app.test_client()
    response = client.post("/api/subjects", json={"name": ""})
    assert response.status_code == 400


def test_create_subject_duplicate(test_app):
    _create_subject(db.session, "Art")
    client = test_app.test_client()
    response = client.post("/api/subjects", json={"name": "Art"})
    assert response.status_code == 400


def test_delete_subject(test_app):
    subject = _create_subject(db.session, "ToDelete")
    client = test_app.test_client()
    response = client.post(f"/api/subjects/{subject.id}/delete")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tags API
# ---------------------------------------------------------------------------


def test_api_tags(test_app):
    _create_tag(db.session, "urgent")
    client = test_app.test_client()
    response = client.get("/api/tags")
    data = response.get_json()
    assert any(t["name"] == "urgent" for t in data["tags"])


def test_create_tag(test_app):
    client = test_app.test_client()
    response = client.post("/api/tags", json={"name": "new", "color": "#00ff00"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["tag"]["name"] == "new"


def test_create_tag_invalid_color(test_app):
    client = test_app.test_client()
    response = client.post("/api/tags", json={"name": "bad", "color": "not-hex"})
    assert response.status_code == 400


def test_update_tag(test_app):
    tag = _create_tag(db.session)
    client = test_app.test_client()
    response = client.post(
        f"/api/tags/{tag.id}",
        json={"name": "updated", "color": "#0000ff"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["tag"]["name"] == "updated"


def test_delete_tag(test_app):
    tag = _create_tag(db.session)
    client = test_app.test_client()
    response = client.post(f"/api/tags/{tag.id}/delete")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Units API
# ---------------------------------------------------------------------------


def test_api_units(test_app):
    subject = _create_subject(db.session, "Math")
    client = test_app.test_client()
    response = client.get("/api/units")
    data = response.get_json()
    assert isinstance(data["units"], list)


def test_create_unit(test_app):
    subject = _create_subject(db.session, "Math")
    client = test_app.test_client()
    response = client.post(
        "/api/units",
        json={"subject_id": subject.id, "name": "Algebra"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["unit"]["name"] == "Algebra"


def test_create_unit_missing_subject(test_app):
    client = test_app.test_client()
    response = client.post("/api/units", json={"name": "Algebra"})
    assert response.status_code == 400


def test_delete_unit(test_app):
    subject = _create_subject(db.session)
    unit = Unit(name="Ch1", subject_id=subject.id)
    db.session.add(unit)
    db.session.commit()
    client = test_app.test_client()
    response = client.post(f"/api/units/{unit.id}/delete")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Recording sessions API
# ---------------------------------------------------------------------------


def test_create_recording_session(test_app):
    client = test_app.test_client()
    response = client.post(
        "/api/recording_sessions",
        json={"subject": "Physics", "mime_type": "audio/webm", "extension": "webm"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "session" in data
    assert data["session"]["subject"] == "Physics"


def test_create_recording_session_no_subject(test_app):
    client = test_app.test_client()
    response = client.post(
        "/api/recording_sessions",
        json={"subject": "", "mime_type": "audio/webm"},
    )
    assert response.status_code == 400


def test_get_recording_session_not_found(test_app):
    client = test_app.test_client()
    response = client.get("/api/recording_sessions/nonexistent")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Chat API
# ---------------------------------------------------------------------------


def test_chat_page(test_app):
    client = test_app.test_client()
    response = client.get("/chat")
    assert response.status_code == 200


def test_api_chat_sessions_empty(test_app):
    client = test_app.test_client()
    response = client.get("/api/chat/sessions")
    data = response.get_json()
    assert data["sessions"] == []


def test_api_chat_recordings_empty(test_app):
    client = test_app.test_client()
    response = client.get("/api/chat/recordings")
    data = response.get_json()
    assert data["recordings"] == []


# ---------------------------------------------------------------------------
# Bulk operations API
# ---------------------------------------------------------------------------


def test_bulk_delete_empty(test_app):
    client = test_app.test_client()
    response = client.post("/api/notes/bulk_delete", json={"note_ids": []})
    assert response.status_code == 400


def test_bulk_delete_notes(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()
    response = client.post("/api/notes/bulk_delete", json={"note_ids": [note.id]})
    assert response.status_code == 200
    data = response.get_json()
    assert data["deleted"] == [note.id]


def test_bulk_update_subject(test_app):
    note = _create_note(db.session, subject="Physics")
    client = test_app.test_client()
    response = client.post(
        "/api/notes/bulk_subject",
        json={"note_ids": [note.id], "subject": "Chemistry"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["subject"] == "Chemistry"


def test_bulk_add_tag(test_app):
    note = _create_note(db.session)
    tag = _create_tag(db.session)
    client = test_app.test_client()
    response = client.post(
        "/api/notes/bulk_add_tag",
        json={"note_ids": [note.id], "tag_id": tag.id},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["tag"]["id"] == tag.id


def test_bulk_add_tag_not_found(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()
    response = client.post(
        "/api/notes/bulk_add_tag",
        json={"note_ids": [note.id], "tag_id": 99999},
    )
    assert response.status_code == 404


def test_bulk_export_empty(test_app):
    client = test_app.test_client()
    response = client.post("/api/notes/bulk_export", json={"note_ids": []})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Notes/<id>/notes (rich notes update)
# ---------------------------------------------------------------------------


def test_update_rich_notes(test_app):
    note = _create_note(db.session, transcription_status="completed", transcription="test transcript")
    client = test_app.test_client()
    response = client.post(
        f"/notes/{note.id}/notes",
        json={"notes_html": "<p>My notes</p>"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["notes_html"] == "<p>My notes</p>"


# ---------------------------------------------------------------------------
# Notes/<id>/speakers/<id>/rename
# ---------------------------------------------------------------------------


def test_rename_speaker_404(test_app):
    client = test_app.test_client()
    response = client.post(
        "/notes/1/speakers/1/rename",
        json={"name": "Teacher"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Retry endpoints
# ---------------------------------------------------------------------------


def test_retry_transcription_no_recording(test_app):
    note = _create_note(db.session, recording_path=None)
    client = test_app.test_client()
    response = client.post(f"/notes/{note.id}/retry_transcription")
    assert response.status_code == 400


def test_retry_key_points_no_transcript(test_app):
    note = _create_note(db.session, transcription_status="failed")
    client = test_app.test_client()
    response = client.post(f"/notes/{note.id}/retry_key_points")
    assert response.status_code == 400
