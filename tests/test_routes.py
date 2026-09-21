"""

Integration tests for Flask route handlers.

"""

import io
import json

from core.extensions import db
from core.models import Note, Speaker, Subject, Tag, Unit

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
    from services.notes_query import refresh_note_search_index

    db_session.flush()
    refresh_note_search_index(note)
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
    assert b"nr-navbar" in response.data


def test_recorder_page_content(test_app):
    titles = [f"Recent {i}" for i in range(4)]
    for title in titles:
        _create_note(db.session, title=title)
    client = test_app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    # Record controls, tabs, and shell elements.
    for hook in (
        b"start-recording-form", b"subject-radio-group", b"stop-recording-form",
        b"recording-status", b"tab-notes-btn", b"tab-upload-btn",
        b"active-notes-panel", b"upload-form", b"theme-toggle",
        b"toast-stack", b"nr-confirm-modal", b"math-editor-modal",
        b'data-save-recording-url',
    ):
        assert hook in response.data
    # Recent strip shows the last 3 notes only.
    assert b"Recent" in response.data
    assert b"Recent 3" in response.data
    assert b"Recent 0" not in response.data


def test_base_shell_on_all_pages(test_app):
    note = _create_note(db.session, title="Shell Note")
    client = test_app.test_client()
    for path in ("/", "/notes", "/chat", "/manage", f"/notes/{note.id}"):
        response = client.get(path)
        assert response.status_code == 200, path
        for hook in (b"nr-navbar", b"toast-stack", b"nr-confirm-modal",
                     b"theme-toggle", b"js/ui/toast.js", b"js/api.js"):
            assert hook in response.data, (path, hook)


def test_library_returns_200(test_app):
    client = test_app.test_client()
    response = client.get("/notes")
    assert response.status_code == 200
    assert b"nr-navbar" in response.data


def test_library_with_search_filter(test_app):
    _create_note(
        db.session, title="Photosynthesis notes", transcription="biology content"
    )
    client = test_app.test_client()
    response = client.get("/notes?q=Photosynthesis")
    assert response.status_code == 200
    assert b"Photosynthesis notes" in response.data


def test_search_finds_text_in_rich_notes(test_app):
    """
    The FTS index searches the plain text extracted from rich note HTML, not
    the raw HTML markup. A term split across tags (e.g. inside <em>) must be
    findable.
    """
    from services.notes_query import init_database

    with test_app.app_context():
        init_database()
    _create_note(
        db.session,
        title="Calc Notes",
        notes_html="<p>derivatives and <em>integrals</em> formula</p>",
    )
    client = test_app.test_client()
    response = client.get("/notes?q=integrals")
    assert response.status_code == 200
    assert b"Calc Notes" in response.data


def test_search_reflects_edited_rich_notes(test_app):
    from services.notes_query import init_database

    with test_app.app_context():
        init_database()
    note = _create_note(db.session, title="Chem Notes", notes_html="<p>acid</p>")
    client = test_app.test_client()

    assert b"Chem Notes" in client.get("/notes?q=acid").data
    assert b"Chem Notes" not in client.get("/notes?q=base").data

    # Update the rich notes and the index should refresh.
    response = client.post(
        f"/notes/{note.id}/notes",
        json={"notes_html": "<p>base</p>"},
    )
    assert response.status_code == 200
    assert b"Chem Notes" not in client.get("/notes?q=acid").data
    assert b"Chem Notes" in client.get("/notes?q=base").data


def test_search_after_delete_excludes_note(test_app):
    from services.notes_query import init_database

    with test_app.app_context():
        init_database()
    note = _create_note(db.session, title="Gone Note", transcription="unique sentence")
    client = test_app.test_client()
    assert b"Gone Note" in client.get("/notes?q=unique").data

    client.post(f"/delete/{note.id}")
    assert b"Gone Note" not in client.get("/notes?q=unique").data


def test_library_with_subject_filter(test_app):
    _create_note(db.session, subject="Chemistry")
    _create_note(db.session, subject="Biology")
    client = test_app.test_client()
    response = client.get("/notes?subjects=Chemistry")
    assert response.status_code == 200


def test_library_renders_cards(test_app):
    note = _create_note(
        db.session,
        title="Card Note",
        subject="Physics",
        transcription_status="completed",
        recording_path="card-note.webm",
    )
    tag = _create_tag(db.session, name="important")
    note.tags.append(tag)
    db.session.commit()
    client = test_app.test_client()
    response = client.get("/notes")
    assert response.status_code == 200
    assert b"note-card" in response.data
    assert b"Card Note" in response.data
    assert b'preload="none"' in response.data
    assert f"/notes/{note.id}".encode() in response.data
    assert b"selection-toolbar" in response.data


def test_library_pagination_window(test_app):
    for i in range(11):
        _create_note(db.session, title=f"Paged Note {i}")
    client = test_app.test_client()
    page1 = client.get("/notes")
    assert page1.status_code == 200
    assert b"page-number-btn" in page1.data
    assert b"Page 1 of 2" in page1.data
    page2 = client.get("/notes?page=2")
    assert page2.status_code == 200
    assert b"Page 2 of 2" in page2.data


def test_api_notes_returns_cards(test_app):
    _create_note(db.session, title="API Card Note")
    client = test_app.test_client()
    response = client.get("/api/notes")
    data = response.get_json()
    assert "html" in data
    assert "note-card" in data["html"]
    assert "API Card Note" in data["html"]


def test_library_tag_overflow_and_pinned(test_app):
    note = _create_note(
        db.session, title="Tagged Note", pinned=True,
        transcription_status="completed",
    )
    for name in ("one", "two", "three", "four"):
        tag = _create_tag(db.session, name=name)
        note.tags.append(tag)
    db.session.commit()
    response = test_app.test_client().get("/notes")
    assert response.status_code == 200
    assert b"+1" in response.data
    assert b"pinned-note-item" not in response.data  # cards use .pinned pin btn
    assert b"pin-note-btn pinned" in response.data
    assert b"completed" in response.data


def test_library_empty_messages(test_app):
    client = test_app.test_client()
    response = client.get("/notes")
    assert b"No recordings yet" in response.data
    assert b"Start recording" in response.data
    filtered = client.get("/notes?q=zzz-no-match")
    assert b"No recordings match" in filtered.data


def test_library_count_and_sort(test_app):
    _create_note(db.session, title="Counted Note")
    response = test_app.test_client().get("/notes")
    assert b">1 recording" in response.data
    assert b'value="date_desc" selected' in response.data or b"date_desc" in response.data


def test_api_notes_status(test_app):
    processing = _create_note(
        db.session,
        title="Busy Note",
        transcription_status="processing",
        transcription_progress=42,
        transcription_stage="transcribing",
        key_points_status="pending",
    )
    done = _create_note(
        db.session,
        title="Done Note",
        transcription_status="completed",
        key_points_status="completed",
    )
    client = test_app.test_client()
    response = client.get("/api/notes/status")
    assert response.status_code == 200
    data = response.get_json()
    assert "has_active_transcription" in data
    by_id = {item["id"]: item for item in data["notes"]}
    assert set(by_id) == {processing.id, done.id}
    assert by_id[processing.id]["transcription_status"] == "processing"
    assert by_id[processing.id]["transcription_progress"] == 42
    assert by_id[processing.id]["transcription_stage"] == "transcribing"
    assert by_id[processing.id]["key_points_status"] == "pending"
    assert set(by_id[processing.id]) == {
        "id",
        "transcription_status",
        "transcription_progress",
        "transcription_stage",
        "key_points_status",
    }
    # No heavy bodies leak into the payload.
    assert b'"transcription":' not in response.data
    assert b'"key_points":' not in response.data


def test_api_notes_status_ids_filter(test_app):
    first = _create_note(db.session, title="First Note")
    _create_note(db.session, title="Second Note")
    client = test_app.test_client()
    response = client.get(f"/api/notes/status?ids={first.id}")
    assert response.status_code == 200
    assert [item["id"] for item in response.get_json()["notes"]] == [first.id]
    bad = client.get("/api/notes/status?ids=nope")
    assert bad.status_code == 400


def test_api_note_card(test_app):
    note = _create_note(
        db.session,
        title="Single Card",
        transcription_status="completed",
        recording_path="single.webm",
    )
    client = test_app.test_client()
    response = client.get(f"/api/notes/card?id={note.id}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["id"] == note.id
    assert "note-card" in data["html"]
    assert "Single Card" in data["html"]
    assert client.get("/api/notes/card").status_code == 400
    assert client.get("/api/notes/card?id=999999").status_code == 404


# ---------------------------------------------------------------------------
# GET /notes/<id>
# ---------------------------------------------------------------------------


def test_note_detail_returns_200(test_app):
    note = _create_note(
        db.session,
        title="Detail Note",
        transcription_status="completed",
        transcription="hello world",
        transcription_segments='[{"w": "hello", "s": 0.5, "spk": null},'
        ' {"w": "world", "s": 1.0, "spk": null}]',
        bookmarks_json='[{"t": 5}]',
        notes_html="<p>my notes</p>",
        key_points="- point one",
        key_points_status="completed",
        recording_path="detail.webm",
    )
    client = test_app.test_client()
    response = client.get(f"/notes/{note.id}")
    assert response.status_code == 200
    assert b"nr-navbar" in response.data
    assert b"Detail Note" in response.data
    assert b"note-detail" in response.data
    assert b"tab-transcript" in response.data
    assert b"tab-keypoints" in response.data
    assert b"tab-notes" in response.data
    assert b"transcript-word" in response.data
    assert b'role="button"' in response.data
    assert b"bookmark-chip" in response.data
    assert b"sync-toggle" in response.data
    assert b"speaker-rename-modal" in response.data


def test_note_detail_404(test_app):
    assert test_app.test_client().get("/notes/999999").status_code == 404


def test_note_detail_speaker_badges(test_app):
    note = _create_note(
        db.session,
        title="Speaker Note",
        transcription_status="completed",
        transcription="hello world",
        transcription_segments='[{"w": "hello", "s": 0.5, "spk": 0}]',
    )
    db.session.add(Speaker(note_id=note.id, order_index=0, label="SPEAKER_00",
                           color="#ff0000", display_name="Alice"))
    db.session.commit()
    response = test_app.test_client().get(f"/notes/{note.id}")
    assert response.status_code == 200
    assert b"speaker-badge" in response.data
    assert b"Rename speaker Alice" in response.data
    assert b"data-speaker-id" in response.data


def test_note_detail_key_points_branches(test_app):
    failed = _create_note(
        db.session, title="KP Failed", transcription_status="completed",
        transcription="text", key_points_status="failed",
        key_points_error="boom",
    )
    processing = _create_note(
        db.session, title="KP Busy", transcription_status="processing",
        transcription_progress=30,
    )
    client = test_app.test_client()
    failed_page = client.get(f"/notes/{failed.id}")
    assert b"retry-key-points-btn" in failed_page.data
    assert b"boom" in failed_page.data
    busy_page = client.get(f"/notes/{processing.id}")
    assert b"Transcribing" in busy_page.data
    # Rail retries are always available; the transcript tab shows progress.
    assert b"retry-transcription-btn" in busy_page.data


def test_note_detail_pager_preserves_query(test_app):
    _create_note(db.session, title="Alpha Note", date="2026-08-18")
    middle = _create_note(db.session, title="Beta Note", date="2026-08-19")
    _create_note(db.session, title="Gamma Note", date="2026-08-20")
    response = test_app.test_client().get(f"/notes/{middle.id}?q=Note")
    assert response.status_code == 200
    assert b"?q=Note" in response.data
    assert b"Library" in response.data


def test_note_detail_download_links(test_app):
    note = _create_note(
        db.session, title="Downloads Note", transcription_status="completed",
        transcription="spoken words here", key_points="- point",
        key_points_status="completed",
    )
    response = test_app.test_client().get(f"/notes/{note.id}")
    assert f"/download_transcript/{note.id}".encode() in response.data
    assert f"/download_key_points/{note.id}".encode() in response.data


def test_note_detail_prev_next(test_app):
    first = _create_note(db.session, title="First Detail", date="2026-08-18")
    middle = _create_note(db.session, title="Middle Detail", date="2026-08-19")
    last = _create_note(db.session, title="Last Detail", date="2026-08-20")
    client = test_app.test_client()
    response = client.get(f"/notes/{middle.id}")
    assert response.status_code == 200
    assert f"/notes/{first.id}".encode() in response.data
    assert f"/notes/{last.id}".encode() in response.data
    first_page = client.get(f"/notes/{first.id}")
    assert b"aria-disabled" in first_page.data


def test_update_note_partial_title_only(test_app):
    note = _create_note(
        db.session, title="Old Title", key_points="- keep me",
        key_points_status="completed",
    )
    client = test_app.test_client()
    response = client.post(
        f"/update_note/{note.id}", json={"title": "New Title"}
    )
    assert response.status_code == 200
    db.session.refresh(note)
    assert note.title == "New Title"
    assert note.key_points == "- keep me"


def test_update_note_key_points_only(test_app):
    note = _create_note(
        db.session, title="Keep Title", key_points="- old",
        key_points_status="completed",
    )
    client = test_app.test_client()
    response = client.post(
        f"/update_note/{note.id}", json={"key_points": "- new"}
    )
    assert response.status_code == 200
    db.session.refresh(note)
    assert note.title == "Keep Title"
    assert note.key_points == "- new"


def test_upload_audio_creates_note(test_app, tmp_recordings):
    client = test_app.test_client()
    response = client.post(
        "/upload",
        data={"file": (io.BytesIO(b"fake-audio-bytes"), "clip.webm")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    note = Note.query.order_by(Note.id.desc()).first()
    assert note is not None
    assert note.recording_path and note.recording_path.endswith(".webm")
    assert note.transcription_status == "pending"
    # The uploaded file lands in the recordings dir.
    import os
    from audio.recordings import RECORDINGS_DIR
    assert os.path.exists(os.path.join(RECORDINGS_DIR, note.recording_path.split("/")[-1]))


def test_upload_rejects_bad_extension(test_app, tmp_recordings):
    client = test_app.test_client()
    before = Note.query.count()
    response = client.post(
        "/upload",
        data={"file": (io.BytesIO(b"nope"), "clip.exe")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert Note.query.count() == before


def test_bulk_export_downloads_zip(test_app):
    first = _create_note(db.session, title="Export One")
    second = _create_note(db.session, title="Export Two")
    client = test_app.test_client()
    response = client.post(
        "/api/notes/bulk_export", json={"note_ids": [first.id, second.id]}
    )
    assert response.status_code == 200
    assert "zip" in response.headers.get("Content-Type", "")
    assert len(response.data) > 0


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
# GET /manage
# ---------------------------------------------------------------------------


def test_manage_returns_200(test_app):
    _create_note(db.session, title="Managed Note")
    _create_subject(db.session, "History")
    _create_tag(db.session, name="keep")
    client = test_app.test_client()
    response = client.get("/manage")
    assert response.status_code == 200
    assert b"nr-navbar" in response.data
    for hook in (
        b"subject-list-manage",
        b"new-subject-name",
        b"add-subject-btn",
        b"subject-manage-error",
        b"tag-tree-manage",
        b"new-tag-name",
        b"new-tag-color",
        b"new-tag-parent",
        b"add-tag-btn",
        b"tag-manage-error",
        b"prefs-sync",
        b"prefs-theme-light",
        b"prefs-density-compact",
        b"js/pages/manage.js",
    ):
        assert hook in response.data
    assert b"Managed Note" not in response.data


def test_manage_counts(test_app):
    _create_note(db.session, title="Counted")
    _create_subject(db.session, "History")
    _create_tag(db.session, name="keep")
    response = test_app.test_client().get("/manage")
    assert response.status_code == 200
    assert b"Recordings" in response.data
    assert b"per page" in response.data


# ---------------------------------------------------------------------------
# Static module assets (guards filename typos that would break pages)
# ---------------------------------------------------------------------------


def test_static_modules_served(test_app):
    client = test_app.test_client()
    for path in (
        "js/utils.js",
        "js/store.js",
        "js/api.js",
        "js/ui/toast.js",
        "js/ui/dialog.js",
        "js/ui/tree.js",
        "js/features/library-list.js",
        "js/features/library-actions.js",
        "js/features/library-bulk.js",
        "js/features/library-taxonomy.js",
        "js/features/note-detail.js",
        "js/features/editor-shell.js",
        "js/features/chat.js",
        "js/features/taxonomy.js",
        "js/pages/library.js",
        "js/pages/detail.js",
        "js/pages/chat-page.js",
        "js/pages/manage.js",
        "js/pages/recorder.js",
        "css/tokens.css",
        "css/base.css",
        "css/components.css",
    ):
        response = client.get(f"/static/{path}")
        assert response.status_code == 200, path


def test_static_references_resolve_on_disk():
    """Every static asset referenced by templates/JS must exist on disk."""
    import os
    import re

    base = os.path.join(os.path.dirname(__file__), "..")
    static_dir = os.path.join(base, "static")
    templates_dir = os.path.join(base, "templates")
    missing = []

    for root, _, files in os.walk(templates_dir):
        for name in files:
            if not name.endswith(".html"):
                continue
            text = open(os.path.join(root, name), encoding="utf-8").read()
            for ref in re.findall(r"filename='([^']+)'", text):
                candidate = os.path.join(static_dir, *ref.split("/"))
                if not os.path.isfile(candidate):
                    missing.append(f"{name} -> {ref}")

    for root, _, files in os.walk(os.path.join(static_dir, "js")):
        for name in files:
            if not name.endswith(".js"):
                continue
            text = open(os.path.join(root, name), encoding="utf-8").read()
            for ref in re.findall(r"from\s+['\"](\.[^'\"]+)['\"]", text):
                candidate = os.path.normpath(os.path.join(root, ref))
                if not candidate.endswith(".js"):
                    candidate += ".js"
                if not os.path.isfile(candidate):
                    missing.append(f"js/{name} -> {ref}")

    assert missing == []


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


def test_create_recording_session(test_app, tmp_recordings):
    client = test_app.test_client()
    response = client.post(
        "/api/recording_sessions",
        json={"subject": "Physics", "mime_type": "audio/webm", "extension": "webm"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "session" in data
    assert data["session"]["subject"] == "Physics"
    assert tmp_recordings.submissions == []


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


def test_chat_page_shell(test_app):
    client = test_app.test_client()
    response = client.get("/chat")
    assert response.status_code == 200
    for hook in (
        b"chats-offcanvas",
        b"chat-filters-top",
        b"chat-session-list",
        b"chat-recording-list",
        b"select-chat-all-btn",
        b"chat-messages",
        b"chat-message-form",
        b"chat-rename-modal",
        b"js/pages/chat-page.js",
        b"filter-tag-tree",
        b"filter-subject-list",
    ):
        assert hook in response.data
    # Chat-scoped filters hide library-only sections.
    assert b"transcription-status-filter-list" not in response.data
    assert b"key-points-status-filter-list" not in response.data
    assert b"empty-notes-filter" not in response.data


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


def test_update_rich_notes(test_app, tmp_recordings):
    note = _create_note(
        db.session, transcription_status="completed", transcription="test transcript"
    )
    client = test_app.test_client()
    response = client.post(
        f"/notes/{note.id}/notes",
        json={"notes_html": "<p>My notes</p>"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["notes_html"] == "<p>My notes</p>"
    assert note.key_points_generation == 1
    assert len(tmp_recordings.submissions) == 1


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
