"""

This module defines the recording upload, recording session, and file-serving
routes for the Notes-Recorder application.

"""

# Import required modules
import json
from flask import Response, request, jsonify, redirect, url_for, send_from_directory

# Import core extensions and config
from core.extensions import app, db
from core.config import RECORDINGS_DIR, NOTE_IMAGES_DIR

# Import text filter and audio recording helpers
from services.text_filters import sanitize_rich_note_html
from audio.recordings import (
    ACTIVE_RECORDING_STATUS,
    allowed_file,
    cancel_recording_session,
    create_recording_session,
    finish_recording_session,
    get_session_by_key,
    save_audio_file,
    save_recording_chunk,
)


@app.route("/save_recording", methods=["POST"])
def save_recording() -> Response:
    """
    Save an uploaded audio file and create a note for it.

    :return: A JSON response with the new note id, or an error.
    :rtype: flask.Response
    """

    audio_file = request.files.get("audio")
    subject = request.form.get("subject")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")

    if not audio_file or audio_file.filename == "":
        return jsonify({"error": "No audio file received."}), 400

    if not allowed_file(audio_file.filename):
        return jsonify({"error": "Unsupported audio file type."}), 400

    note = save_audio_file(audio_file, subject, start_time, end_time)
    return jsonify({"message": "Recording saved.", "id": note.id})


@app.route("/api/recording_sessions", methods=["POST"])
def create_recording_session_route() -> Response:
    """
    Create a new recording session from the request payload.

    :return: A JSON response with the created session, or an error.
    :rtype: flask.Response
    """

    data = request.get_json(silent=True) or {}
    subject = (data.get("subject") or "").strip()
    mime_type = (data.get("mime_type") or "").strip()
    extension = (data.get("extension") or "webm").strip().lower()
    start_time = (data.get("start_time") or "").strip() or None

    if not subject:
        return jsonify({"error": "A subject is required."}), 400

    if extension not in {"wav", "mp3", "ogg", "webm", "m4a", "mp4"}:
        return jsonify({"error": "Unsupported audio file type."}), 400

    session = create_recording_session(subject, mime_type, extension, start_time)
    return jsonify({"session": session.to_dict()})


@app.route("/api/recording_sessions/<session_key>")
def get_recording_session_route(session_key: str) -> Response:
    """
    Return a recording session by its session key.

    :param session_key: The session key string.
    :type session_key: str
    :return: A JSON response with the session, or 404 if not found.
    :rtype: flask.Response
    """

    session = get_session_by_key(session_key)
    if not session:
        return jsonify({"error": "Recording session was not found."}), 404

    return jsonify({"session": session.to_dict()})


@app.route("/api/recording_sessions/<session_key>/notes", methods=["PATCH"])
def update_recording_session_notes(session_key: str) -> Response:
    """
    Update the rich notes HTML of an active recording session.

    :param session_key: The session key string.
    :type session_key: str
    :return: A JSON response with the sanitized notes HTML, or an error.
    :rtype: flask.Response
    """

    session = get_session_by_key(session_key)
    if not session:
        return jsonify({"error": "Recording session was not found."}), 404

    if session.status != ACTIVE_RECORDING_STATUS:
        return jsonify({"error": "Recording session is not active."}), 400

    data = request.get_json(silent=True) or {}
    session.notes_html = sanitize_rich_note_html(data.get("notes_html"))
    db.session.commit()
    return jsonify({"notes_html": session.notes_html or ""})


@app.route("/api/recording_sessions/<session_key>/chunks", methods=["POST"])
def save_recording_chunk_route(session_key: str) -> Response:
    """
    Save an uploaded audio chunk for a recording session.

    :param session_key: The session key string.
    :type session_key: str
    :return: A JSON response confirming the save, or an error.
    :rtype: flask.Response
    """

    session = get_session_by_key(session_key)
    if not session:
        return jsonify({"error": "Recording session was not found."}), 404

    if session.status != ACTIVE_RECORDING_STATUS:
        return jsonify({"error": "Recording session is not active."}), 400

    chunk_file = request.files.get("audio")
    if not chunk_file or chunk_file.filename == "":
        return jsonify({"error": "No audio chunk received."}), 400

    try:
        save_recording_chunk(
            session,
            chunk_file,
            request.form.get("segment_index", 0, type=int),
            request.form.get("chunk_index", 0, type=int),
        )

    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify({"message": "Chunk saved.", "chunk_count": session.chunk_count})


@app.route("/api/recording_sessions/<session_key>/bookmarks", methods=["PATCH"])
def update_recording_session_bookmarks(session_key: str) -> Response:
    """
    Update the timestamp bookmarks of an active recording session.

    :param session_key: The session key string.
    :type session_key: str
    :return: A JSON response with the saved bookmarks, or an error.
    :rtype: flask.Response
    """

    session = get_session_by_key(session_key)
    if not session:
        return jsonify({"error": "Recording session was not found."}), 404

    if session.status != ACTIVE_RECORDING_STATUS:
        return jsonify({"error": "Recording session is not active."}), 400

    data = request.get_json(silent=True) or {}
    bookmarks = data.get("bookmarks") or []
    if not isinstance(bookmarks, list):
        return jsonify({"error": "Bookmarks must be a list."}), 400

    cleaned = []
    for bookmark in bookmarks[:500]:
        if not isinstance(bookmark, dict):
            continue
        try:
            time = float(bookmark.get("t"))
        except (TypeError, ValueError):
            continue
        if time < 0:
            continue
        cleaned.append({"t": round(time, 3)})

    session.bookmarks_json = json.dumps(cleaned)
    db.session.commit()
    return jsonify({"bookmarks": cleaned})


@app.route("/api/recording_sessions/<session_key>/finish", methods=["POST"])
def finish_recording_session_route(session_key: str) -> Response:
    """
    Finalize a recording session and create the resulting note.

    :param session_key: The session key string.
    :type session_key: str
    :return: A JSON response with the new note id, or an error.
    :rtype: flask.Response
    """

    session = get_session_by_key(session_key)
    if not session:
        return jsonify({"error": "Recording session was not found."}), 404

    data = request.get_json(silent=True) or {}
    end_time = (data.get("end_time") or "").strip() or None
    recording_duration = data.get("recording_duration")
    try:
        note = finish_recording_session(
            session,
            end_time,
            recording_duration=(
                int(recording_duration) if recording_duration else None
            ),
        )

    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify({"message": "Recording saved.", "id": note.id})


@app.route("/api/recording_sessions/<session_key>/cancel", methods=["POST"])
def cancel_recording_session_route(session_key: str) -> Response:
    """
    Cancel an active recording session.

    :param session_key: The session key string.
    :type session_key: str
    :return: A JSON response confirming the cancelation, or an error.
    :rtype: flask.Response
    """

    session = get_session_by_key(session_key)
    if not session:
        return jsonify({"error": "Recording session was not found."}), 404

    try:
        cancel_recording_session(session)

    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify({"message": "Recording canceled."})


@app.route("/upload", methods=["POST"])
def upload() -> Response:
    """
    Handle a legacy upload form for an audio file.

    :return: A redirect back to the index page.
    :rtype: flask.Response
    """

    uploaded_file = request.files.get("file")
    if not uploaded_file or uploaded_file.filename == "":
        return redirect(url_for("index"))

    if not allowed_file(uploaded_file.filename):
        return redirect(url_for("index"))

    save_audio_file(uploaded_file, request.form.get("subject") or "Uploaded")
    return redirect(url_for("index"))


@app.route("/recordings/<path:filename>")
def recording_file(filename: str) -> Response:
    """
    Serve a stored recording file.

    :param filename: Path of the recording within RECORDINGS_DIR.
    :type filename: str
    :return: The requested file.
    :rtype: flask.Response
    """

    return send_from_directory(RECORDINGS_DIR, filename)


@app.route("/recordings/note_images/<path:filename>")
def note_image_file(filename: str) -> Response:
    """
    Serve a stored note image file.

    :param filename: Path of the image within NOTE_IMAGES_DIR.
    :type filename: str
    :return: The requested image file.
    :rtype: flask.Response
    """

    return send_from_directory(NOTE_IMAGES_DIR, filename)
