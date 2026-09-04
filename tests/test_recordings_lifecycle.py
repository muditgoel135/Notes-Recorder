"""
 
Tests for the recording-session lifecycle and the high-level audio.recordings
helpers. External dependencies (ffmpeg, subprocess, network, the background
transcription worker) are fully mocked.
 
"""

import io
import os
import struct

import pytest
from werkzeug.datastructures import FileStorage

from audio.recordings import (
    WEBM_DURATION_ID,
    WEBM_INFO_ID,
    WEBM_SEGMENT_ID,
    WEBM_TRACKS_ID,
    ACTIVE_RECORDING_STATUS,
    FINISHED_RECORDING_STATUS,
    add_webm_duration_metadata,
    allowed_file,
    build_recording_path,
    build_segment_files,
    cancel_recording_session,
    concat_segments,
    create_recording_session,
    duration_seconds_from_times,
    finish_recording_session,
    note_download_basename,
    patch_webm_duration,
    save_recording_chunk,
)
from core.extensions import db
from core.models import Note, RecordingSession

# ---------------------------------------------------------------------------
# Pure helper unit tests
# ---------------------------------------------------------------------------


def test_allowed_file_valid_and_invalid():
    assert allowed_file("note.webm")
    assert allowed_file("note.WAV")
    assert allowed_file("rec.m4a")
    assert not allowed_file("note.exe")
    assert not allowed_file("note")
    assert not allowed_file("")
    assert not allowed_file(None)


def test_note_download_basename():
    note = Note(date="2026-08-20", title="My Physics Notes", subject="Physics")
    assert note_download_basename(note).startswith("2026-08-20_")
    assert "Physics" in note_download_basename(note)

    note2 = Note(date="2026-08-20", title=None, subject="Physics")
    assert note_download_basename(note2).endswith("Physics")

    note3 = Note(date="2026-08-20", subject=None, title=None)
    assert note_download_basename(note3).endswith("note")


def test_duration_seconds_from_times():
    assert duration_seconds_from_times("10:00:00", "10:05:30") == 330
    # End before start wraps past midnight.
    assert duration_seconds_from_times("23:00:00", "00:30:00") == 5400
    assert duration_seconds_from_times("10:00:00", "09:59:00") == 86340
    assert duration_seconds_from_times(None, "10:00:00") is None
    assert duration_seconds_from_times("10:00:00", "") is None
    assert duration_seconds_from_times("bogus", "10:00:00") is None


def test_build_recording_path_pattern(tmp_recordings):
    import datetime

    session = RecordingSession(subject="Physics", extension="webm")
    now = datetime.datetime(2026, 8, 20, 10, 5, 0)
    path = build_recording_path(session, now)
    filename = os.path.basename(path)
    assert filename.startswith("20260820_100500_Physics_")
    assert filename.endswith(".webm")
    assert os.path.dirname(path) == tmp_recordings.recordings


def test_build_segment_files_merges_chunks(tmp_recordings):
    session = RecordingSession(
        subject="Math", extension="webm", session_key="segtest"
    )
    chunk_dir = os.path.join(tmp_recordings.session_chunks, session.session_key)
    os.makedirs(chunk_dir, exist_ok=True)

    # Write chunk files for two segments into the session's chunk dir.
    chunk_msgs = {
        "segment_0000_chunk_000000.webm": b"AAAA",
        "segment_0000_chunk_000001.webm": b"BBBB",
        "segment_0001_chunk_000000.webm": b"CCCC",
    }
    for name, data in chunk_msgs.items():
        with open(os.path.join(chunk_dir, name), "wb") as fh:
            fh.write(data)

    segment_paths = build_segment_files(
        session,
        list(chunk_msgs.keys()),
    )
    segment_paths = sorted(segment_paths)
    assert len(segment_paths) == 2
    with open(segment_paths[0], "rb") as fh:
        assert fh.read() == b"AAAABBBB"
    with open(segment_paths[1], "rb") as fh:
        assert fh.read() == b"CCCC"


def test_concat_segments_writes_list_and_cleans_up(tmp_recordings, monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        list_path = args[args.index("-i") + 1]
        with open(list_path, "r", encoding="utf-8") as fh:
            captured["content"] = fh.read()
        captured["list_path"] = list_path
        return None

    monkeypatch.setattr("audio.recordings.subprocess.run", fake_run)

    seg1 = os.path.join(tmp_recordings.session_chunks, "seg1.webm")
    seg2 = os.path.join(tmp_recordings.session_chunks, "seg2.webm")
    final = os.path.join(tmp_recordings.recordings, "final.webm")
    for path in (seg1, seg2):
        with open(path, "wb") as fh:
            fh.write(b"x")

    concat_segments([seg1, seg2], final)

    assert "file '" + seg1.replace("\\", "/") + "'" in captured["content"]
    assert os.path.exists(captured["list_path"]) is False


# ---------------------------------------------------------------------------
# WebM duration patching unit tests
# ---------------------------------------------------------------------------


def _build_webm(data_with_info=False):
    """
    Build a minimal WebM bytearray with a Segment -> Info element (and a Tracks
    element so patch_webm_duration can insert a missing Duration in front of
    it). When data_with_info is True the Info element contains an 8-byte
    (float64) Duration element.
    """
    if data_with_info:
        duration_payload = struct.pack(">d", 5000.0)
        duration_element = WEBM_DURATION_ID + b"\x88" + duration_payload
        info_payload = duration_element
    else:
        info_payload = b"\x00\x00"

    info_element = WEBM_INFO_ID + _vint_size(len(info_payload)) + info_payload
    tracks_element = WEBM_TRACKS_ID + _vint_size(2) + b"\x00\x00"

    segment_payload = info_element + tracks_element
    segment = WEBM_SEGMENT_ID + _vint_size(len(segment_payload)) + segment_payload
    return bytearray(segment)


def _vint_size(value):
    if value < 0x7F:
        return bytes([0x80 | value])
    if value < 0x3FFF:
        return bytes([0x40 | (value >> 8), value & 0xFF])
    return bytes([0x20 | ((value >> 16) & 0xFF), (value >> 8) & 0xFF, value & 0xFF])


def test_patch_webm_duration_rewrites_existing():
    patched = patch_webm_duration(_build_webm(data_with_info=True), 10)
    assert patched is not None
    # After patching, the duration payload should be 10000.0 ms (10s * 1000).
    duration_pos = patched.find(WEBM_DURATION_ID)
    value_pos = duration_pos + len(WEBM_DURATION_ID) + 1  # skip size byte
    (value,) = struct.unpack(">d", bytes(patched[value_pos : value_pos + 8]))
    assert value == 10000.0


def test_patch_webm_duration_rewrites_float32():
    duration_element = WEBM_DURATION_ID + b"\x84" + struct.pack(">f", 2000.0)
    info_payload = duration_element
    info_element = WEBM_INFO_ID + _vint_size(len(info_payload)) + info_payload
    tracks_element = WEBM_TRACKS_ID + _vint_size(2) + b"\x00\x00"
    segment = WEBM_SEGMENT_ID + _vint_size(len(info_element + tracks_element)) + (
        info_element + tracks_element
    )
    data = bytearray(segment)

    patched = patch_webm_duration(data, 7)
    assert patched is not None
    duration_pos = patched.find(WEBM_DURATION_ID)
    value_pos = duration_pos + len(WEBM_DURATION_ID) + 1
    (value,) = struct.unpack(">f", bytes(patched[value_pos : value_pos + 4]))
    assert value == 7000.0


def test_patch_webm_duration_insets_when_absent():
    data = _build_webm(data_with_info=False)
    assert data.find(WEBM_DURATION_ID) == -1

    patched = patch_webm_duration(data, 12)
    assert patched is not None
    duration_pos = patched.find(WEBM_DURATION_ID)
    assert duration_pos >= 0


def test_patch_webm_duration_malformed_returns_none():
    assert patch_webm_duration(bytearray(b"\x00\x00\x00"), 5) is None


def test_add_webm_duration_metadata(tmp_recordings):
    # None / <=0 returns False without touching the file.
    path = os.path.join(tmp_recordings.recordings, "m.webm")
    with open(path, "wb") as fh:
        fh.write(b"raw")
    assert add_webm_duration_metadata(path, None) is False
    assert add_webm_duration_metadata(path, 0) is False
    with open(path, "rb") as fh:
        assert fh.read() == b"raw"

    # Missing file returns False.
    assert add_webm_duration_metadata(
        os.path.join(tmp_recordings.recordings, "nope.webm"), 5
    ) is False


# ---------------------------------------------------------------------------
# DB-backed integration tests
# ---------------------------------------------------------------------------


def _create_session(db_session, **overrides):
    defaults = dict(
        session_key="sesskey123",
        subject="Physics",
        unit="General",
        start_time="10:00:00",
        status=ACTIVE_RECORDING_STATUS,
        extension="webm",
        segments_json="[]",
        bookmarks_json="[]",
    )
    defaults.update(overrides)
    session = RecordingSession(**defaults)
    db_session.add(session)
    db_session.commit()
    return session


def _chunk_file(data=b"chunk-data", name="chunk.webm"):
    return FileStorage(stream=io.BytesIO(data), filename=name)


def test_save_recording_route_success(test_app, tmp_recordings):
    client = test_app.test_client()
    response = client.post(
        "/save_recording",
        data={
            "audio": _chunk_file(name="audio.webm"),
            "subject": "Physics",
            "start_time": "10:00:00",
            "end_time": "10:05:00",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    note = Note.query.first()
    assert note is not None
    assert response.json["id"] == note.id
    assert note.transcription_status == "pending"
    # File was saved into the (patched) recordings dir.
    assert os.path.exists(os.path.join(tmp_recordings.recordings, os.path.basename(note.recording_path)))


def test_save_recording_route_missing_file(test_app):
    response = test_app.test_client().post(
        "/save_recording",
        data={},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_save_recording_route_bad_extension(test_app):
    response = test_app.test_client().post(
        "/save_recording",
        data={
            "audio": _chunk_file(name="audio.exe"),
            "subject": "Physics",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_create_recording_session_route_success(test_app, tmp_recordings):
    client = test_app.test_client()
    response = client.post(
        "/api/recording_sessions",
        json={"subject": "Physics", "extension": "webm"},
    )
    assert response.status_code == 200
    session = RecordingSession.query.first()
    assert response.json["session"]["id"] == session.id
    chunk_dir = os.path.join(tmp_recordings.session_chunks, session.session_key)
    assert os.path.isdir(chunk_dir)


def test_create_recording_session_route_no_subject(test_app):
    response = test_app.test_client().post(
        "/api/recording_sessions", json={"extension": "webm"}
    )
    assert response.status_code == 400


def test_create_recording_session_route_bad_extension(test_app):
    response = test_app.test_client().post(
        "/api/recording_sessions", json={"subject": "Physics", "extension": "exe"}
    )
    assert response.status_code == 400


def test_update_recording_session_notes_success(test_app):
    session = _create_session(db.session)
    response = test_app.test_client().patch(
        f"/api/recording_sessions/{session.session_key}/notes",
        json={"notes_html": "<p>new notes</p>"},
    )
    assert response.status_code == 200
    assert "<p>new notes</p>" in response.json["notes_html"]


def test_update_recording_session_notes_404(test_app):
    response = test_app.test_client().patch(
        "/api/recording_sessions/nonexistent/notes",
        json={"notes_html": "<p>x</p>"},
    )
    assert response.status_code == 404


def test_update_recording_session_notes_not_active(test_app):
    session = _create_session(db.session, status=FINISHED_RECORDING_STATUS)
    response = test_app.test_client().patch(
        f"/api/recording_sessions/{session.session_key}/notes",
        json={"notes_html": "<p>x</p>"},
    )
    assert response.status_code == 400


def test_save_recording_chunk_route_success(test_app, tmp_recordings):
    session = _create_session(db.session)
    response = test_app.test_client().post(
        f"/api/recording_sessions/{session.session_key}/chunks",
        data={
            "audio": _chunk_file(),
            "segment_index": "0",
            "chunk_index": "0",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.json["chunk_count"] == 1
    db.session.refresh(session)
    assert session.chunk_count == 1
    assert session.segments_json == "[0]"


def test_save_recording_chunk_route_404(test_app):
    response = test_app.test_client().post(
        "/api/recording_sessions/nonexistent/chunks",
        data={"audio": _chunk_file()},
        content_type="multipart/form-data",
    )
    assert response.status_code == 404


def test_save_recording_chunk_route_not_active(test_app):
    session = _create_session(db.session, status=FINISHED_RECORDING_STATUS)
    response = test_app.test_client().post(
        f"/api/recording_sessions/{session.session_key}/chunks",
        data={"audio": _chunk_file()},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_save_recording_chunk_route_missing_file(test_app):
    session = _create_session(db.session)
    response = test_app.test_client().post(
        f"/api/recording_sessions/{session.session_key}/chunks",
        data={},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_save_recording_chunk_multiple_segments(test_app, tmp_recordings):
    session = _create_session(db.session)
    client = test_app.test_client()
    for seg, ch in [(0, 0), (0, 1), (1, 0)]:
        response = client.post(
            f"/api/recording_sessions/{session.session_key}/chunks",
            data={
                "audio": _chunk_file(data=f"seg{seg}-{ch}".encode()),
                "segment_index": str(seg),
                "chunk_index": str(ch),
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
    db.session.refresh(session)
    assert session.chunk_count == 3
    assert session.segments_json == "[0, 1]"


def test_update_recording_session_bookmarks_success(test_app):
    session = _create_session(db.session)
    response = test_app.test_client().patch(
        f"/api/recording_sessions/{session.session_key}/bookmarks",
        json={"bookmarks": [{"t": 1.5}, {"t": 2.0}]},
    )
    assert response.status_code == 200
    assert response.json["bookmarks"] == [{"t": 1.5}, {"t": 2.0}]


def test_update_recording_session_bookmarks_filters_and_caps(test_app):
    session = _create_session(db.session)
    bookmarks = [{"t": float(i)} for i in range(600)]
    bookmarks.append({"t": -1})
    bookmarks.append("not-a-dict")
    bookmarks.append({"t": "nan-here"})
    response = test_app.test_client().patch(
        f"/api/recording_sessions/{session.session_key}/bookmarks",
        json={"bookmarks": bookmarks},
    )
    assert response.status_code == 200
    assert len(response.json["bookmarks"]) == 500


def test_update_recording_session_bookmarks_not_list(test_app):
    session = _create_session(db.session)
    response = test_app.test_client().patch(
        f"/api/recording_sessions/{session.session_key}/bookmarks",
        json={"bookmarks": "nope"},
    )
    assert response.status_code == 400


def test_finish_recording_session_route_success(test_app, tmp_recordings):
    session = _create_session(db.session)
    client = test_app.test_client()

    chunk_resp = client.post(
        f"/api/recording_sessions/{session.session_key}/chunks",
        data={"audio": _chunk_file(data=b"abcdef")},
        content_type="multipart/form-data",
    )
    assert chunk_resp.status_code == 200

    response = client.post(
        f"/api/recording_sessions/{session.session_key}/finish",
        json={"end_time": "10:30:00"},
    )
    assert response.status_code == 200

    db.session.refresh(session)
    assert session.status == FINISHED_RECORDING_STATUS
    note = db.session.get(Note, response.json["id"])
    assert note is not None
    assert note.recording_path is not None
    # The chunk dir is cleaned up after finishing.
    assert not os.path.exists(
        os.path.join(tmp_recordings.session_chunks, session.session_key)
    )
    # Single-chunk finish moves the file into the recordings dir.
    assert os.path.exists(
        os.path.join(tmp_recordings.recordings, os.path.basename(note.recording_path))
    )


def test_finish_recording_session_route_idempotent(test_app, tmp_recordings):
    session = _create_session(db.session)
    client = test_app.test_client()
    client.post(
        f"/api/recording_sessions/{session.session_key}/chunks",
        data={"audio": _chunk_file(data=b"xyz")},
        content_type="multipart/form-data",
    )
    first = client.post(
        f"/api/recording_sessions/{session.session_key}/finish",
        json={"end_time": "10:30:00"},
    )
    second = client.post(
        f"/api/recording_sessions/{session.session_key}/finish",
        json={"end_time": "11:00:00"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json["id"] == second.json["id"]


def test_finish_recording_session_route_no_chunks(test_app):
    session = _create_session(db.session)
    response = test_app.test_client().post(
        f"/api/recording_sessions/{session.session_key}/finish",
        json={"end_time": "10:30:00"},
    )
    assert response.status_code == 400


def test_finish_recording_session_route_404(test_app):
    response = test_app.test_client().post(
        "/api/recording_sessions/nonexistent/finish", json={}
    )
    assert response.status_code == 404


def test_cancel_recording_session_route_success(test_app, tmp_recordings):
    session = _create_session(db.session)
    client = test_app.test_client()
    client.post(
        f"/api/recording_sessions/{session.session_key}/chunks",
        data={"audio": _chunk_file()},
        content_type="multipart/form-data",
    )
    response = client.post(f"/api/recording_sessions/{session.session_key}/cancel")
    assert response.status_code == 200
    db.session.refresh(session)
    assert session.status == "canceled"
    assert not os.path.exists(
        os.path.join(tmp_recordings.session_chunks, session.session_key)
    )


def test_cancel_recording_session_route_finished_400(test_app):
    session = _create_session(db.session, status=FINISHED_RECORDING_STATUS)
    response = test_app.test_client().post(
        f"/api/recording_sessions/{session.session_key}/cancel"
    )
    assert response.status_code == 400


def test_recording_file_served(test_app, tmp_recordings):
    file_path = os.path.join(tmp_recordings.recordings, "audio.webm")
    with open(file_path, "wb") as fh:
        fh.write(b"audiodata")
    response = test_app.test_client().get("/recordings/audio.webm")
    assert response.status_code == 200
    assert response.data == b"audiodata"


def test_recording_file_missing_404(test_app):
    response = test_app.test_client().get("/recordings/missing.webm")
    assert response.status_code == 404


def test_note_image_file_served(test_app, tmp_recordings):
    file_path = os.path.join(tmp_recordings.note_images, "img.png")
    with open(file_path, "wb") as fh:
        fh.write(b"imagedata")
    response = test_app.test_client().get("/recordings/note_images/img.png")
    assert response.status_code == 200
    assert response.data == b"imagedata"


def test_note_image_file_missing_404(test_app):
    response = test_app.test_client().get("/recordings/note_images/missing.png")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Direct helper-level DB tests
# ---------------------------------------------------------------------------


def test_save_recording_chunk_direct(test_app, tmp_recordings):
    session = _create_session(db.session)
    save_recording_chunk(session, _chunk_file(), 0, 0)
    db.session.refresh(session)
    assert session.chunk_count == 1
    assert session.segments_json == "[0]"


def test_finish_recording_session_direct_no_chunks(test_app):
    session = _create_session(db.session)
    with pytest.raises(ValueError):
        finish_recording_session(session, "10:30:00")


def test_cancel_recording_session_direct(test_app, tmp_recordings):
    session = _create_session(db.session)
    cancel_recording_session(session)
    assert session.status == "canceled"


def test_cancel_recording_session_finished_raises(test_app, tmp_recordings):
    session = _create_session(db.session)
    client = test_app.test_client()
    client.post(
        f"/api/recording_sessions/{session.session_key}/chunks",
        data={"audio": _chunk_file(data=b"xyz")},
        content_type="multipart/form-data",
    )
    finish = client.post(
        f"/api/recording_sessions/{session.session_key}/finish",
        json={"end_time": "10:30:00"},
    )
    assert finish.status_code == 200
    db.session.refresh(session)
    with pytest.raises(ValueError):
        cancel_recording_session(session)
