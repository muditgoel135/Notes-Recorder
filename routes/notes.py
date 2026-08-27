"""

This module defines the notes listing and per-note management routes for the
Notes-Recorder application, including search, filtering, downloads, and
metadata updates.

"""

# Import required modules
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from flask import (
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    Response,
)

from werkzeug.utils import secure_filename

# Import core extensions and models
from core.extensions import app, db
from core.models import Note, Speaker, Subject, Tag, Unit

# Import core.config constants
from core.config import (
    BASE_DIR,
    NOTE_IMAGES_DIR,
    DEFAULT_PER_PAGE,
    TRANSCRIPTION_PENDING,
    TRANSCRIPTION_PROCESSING,
    TRANSCRIPTION_COMPLETED,
    KEY_POINTS_PENDING,
    KEY_POINTS_FAILED,
    DEFAULT_UNIT,
)

# Import services and audio helpers
from services.notes_query import (
    build_notes_query,
    parse_notes_filters_from_request,
    check_has_active_transcription,
)
from services.text_filters import sanitize_rich_note_html
from audio.recordings import note_download_basename, duration_seconds_from_times
from audio.transcription import (
    enqueue_transcription,
    extract_key_points,
    transcription_executor,
)
from audio.key_points import reset_key_points_offline_retries


def units_by_subject_map() -> dict[str, list[str]]:
    """
    Build a mapping of subject names to their unit names, ordered by name.

    :return: A dict keyed by subject name with lists of unit names.
    :rtype: dict of str to list of str
    """

    result = {}
    units = Unit.query.join(Subject).order_by(Subject.name, Unit.name).all()
    for unit in units:
        result.setdefault(unit.subject.name, []).append(unit.name)
    return result


@app.route("/")
def index() -> str:
    """
    Render the notes index page with optional filters.

    :return: The rendered index template.
    :rtype: str
    """

    filters = parse_notes_filters_from_request()
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    pagination = build_notes_query(**filters).paginate(
        page=page, per_page=DEFAULT_PER_PAGE, error_out=False
    )

    has_active_transcription = check_has_active_transcription()
    has_filters = bool(
        filters["search"]
        or filters["date_from"]
        or filters["date_to"]
        or filters["time_from"]
        or filters["time_to"]
        or filters["tag_ids"]
        or filters["subjects"]
        or filters["units"]
        or filters["transcription_statuses"]
        or filters["key_points_statuses"]
        or filters["empty_notes"]
    )

    return render_template(
        "index.html",
        notes=pagination.items,
        page=pagination.page,
        total_pages=pagination.pages or 1,
        total=pagination.total,
        has_active_transcription=has_active_transcription,
        has_filters=has_filters,
        subjects=Subject.query.order_by(Subject.name).all(),
        units_by_subject=units_by_subject_map(),
        sort_by=filters["sort"],
    )


@app.route("/api/notes")
def api_notes() -> Response:
    """
    Return a paginated, filtered notes list as JSON.

    :return: A JSON response with the rendered list HTML and pagination info.
    :rtype: flask.Response
    """

    filters = parse_notes_filters_from_request()
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    pagination = build_notes_query(**filters).paginate(
        page=page, per_page=DEFAULT_PER_PAGE, error_out=False
    )

    has_filters = bool(
        filters["search"]
        or filters["date_from"]
        or filters["date_to"]
        or filters["time_from"]
        or filters["time_to"]
        or filters["tag_ids"]
        or filters["subjects"]
        or filters["units"]
        or filters["transcription_statuses"]
        or filters["key_points_statuses"]
        or filters["empty_notes"]
    )

    html = render_template(
        "_notes_list.html",
        notes=pagination.items,
        page=pagination.page,
        total_pages=pagination.pages or 1,
        total=pagination.total,
        has_filters=has_filters,
        subjects=Subject.query.order_by(Subject.name).all(),
        units_by_subject=units_by_subject_map(),
    )

    return jsonify(
        {
            "html": html,
            "page": pagination.page,
            "total_pages": pagination.pages or 1,
            "total": pagination.total,
            "has_active_transcription": check_has_active_transcription(),
        }
    )


@app.route("/api/notes/ids")
def api_notes_ids() -> Response:
    """
    Return the ids of all notes matching the current filters, for bulk selection.

    :return: A JSON response with the matching note ids.
    :rtype: flask.Response
    """

    filters = parse_notes_filters_from_request()
    rows = build_notes_query(**filters).with_entities(Note.id).all()
    return jsonify({"ids": [row.id for row in rows]})


@app.route("/api/note_images", methods=["POST"])
def upload_note_image() -> Response:
    """
    Upload an image to be embedded in a note.

    :return: A JSON response with the image URL, or an error.
    :rtype: flask.Response
    """

    image_file = request.files.get("image")
    if not image_file or image_file.filename == "":
        return jsonify({"error": "No image received."}), 400

    extension = image_file.filename.rsplit(".", 1)[-1].lower()
    if extension not in {"png", "jpg", "jpeg", "gif", "webp"}:
        return jsonify({"error": "Unsupported image type."}), 400

    os.makedirs(NOTE_IMAGES_DIR, exist_ok=True)
    safe_name = secure_filename(image_file.filename.rsplit(".", 1)[0]) or "image"
    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{safe_name}_{uuid.uuid4().hex}.{extension}"
    image_file.save(os.path.join(NOTE_IMAGES_DIR, filename))
    return jsonify({"url": url_for("note_image_file", filename=filename)})


@app.route("/download_transcript/<int:note_id>")
def download_transcript(note_id: int) -> Response:
    """
    Download a note's transcript as a text file.

    :param note_id: ID of the note.
    :type note_id: int
    :return: The transcript as an attachment, or 404 if unavailable.
    :rtype: flask.Response
    """

    note = Note.query.get_or_404(note_id)
    if not note.transcription:
        return jsonify({"error": "No transcript available."}), 404

    filename = f"{note_download_basename(note)}_transcript.txt"
    return Response(
        note.transcription,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/download_key_points/<int:note_id>")
def download_key_points(note_id: int) -> Response:
    """
    Download a note's key points as a markdown file.

    :param note_id: ID of the note.
    :type note_id: int
    :return: The key points as an attachment, or 404 if unavailable.
    :rtype: flask.Response
    """

    note = Note.query.get_or_404(note_id)
    if not note.key_points:
        return jsonify({"error": "No key points available."}), 404

    heading = note.title or note.subject or "Key Points"
    content = f"# {heading}\n\n{note.key_points}\n"
    filename = f"{note_download_basename(note)}_key_points.md"
    return Response(
        content,
        mimetype="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/notes/<int:note_id>/tags", methods=["POST"])
def set_note_tags(note_id: int) -> Response:
    """
    Set the tags assigned to a note.

    :param note_id: ID of the note.
    :type note_id: int
    :return: A JSON response with the note's tags, or 404 if not found.
    :rtype: flask.Response
    """

    note = Note.query.get_or_404(note_id)
    data = request.get_json(silent=True) or {}
    raw_tag_ids = data.get("tag_ids") or []
    if not isinstance(raw_tag_ids, list) or not all(
        isinstance(tag_id, int)
        or (isinstance(tag_id, str) and tag_id.strip().isdigit())
        for tag_id in raw_tag_ids
    ):
        return jsonify({"error": "Invalid tag ids."}), 400

    tag_ids = [int(tag_id) for tag_id in raw_tag_ids]
    note.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
    db.session.commit()
    return jsonify({"tags": [tag.to_dict() for tag in note.tags]})


@app.route("/notes/<int:note_id>/subject", methods=["POST"])
def update_note_subject(note_id: int) -> Response:
    """
    Update a note's subject and unit.

    The unit defaults to the general category and is reset to it when the
    chosen unit does not belong to the note's subject.

    :param note_id: ID of the note.
    :type note_id: int
    :return: A JSON response with the updated subject and unit, or an error.
    :rtype: flask.Response
    """

    note = Note.query.get_or_404(note_id)
    data = request.get_json(silent=True) or {}
    subject = (data.get("subject") or "").strip()
    unit = (data.get("unit") or DEFAULT_UNIT).strip() or DEFAULT_UNIT

    if not subject:
        return jsonify({"error": "A subject is required."}), 400

    if unit != DEFAULT_UNIT:
        subject_obj = Subject.query.filter(
            db.func.lower(Subject.name) == subject.lower()
        ).first()
        if not subject_obj or not any(u.name == unit for u in subject_obj.units):
            unit = DEFAULT_UNIT

    note.subject = subject[:100]
    note.unit = unit[:100]
    db.session.commit()
    return jsonify({"subject": note.subject, "unit": note.unit})


@app.route("/notes/<int:note_id>/pin", methods=["POST"])
def toggle_note_pin(note_id: int) -> Response:
    """
    Toggle whether a note is pinned to the top of the recordings list.

    :param note_id: ID of the note.
    :type note_id: int
    :return: A JSON response with the note's new pinned state, or 404 if not found.
    :rtype: flask.Response
    """

    note = Note.query.get_or_404(note_id)
    note.pinned = not note.pinned
    db.session.commit()
    return jsonify({"id": note.id, "pinned": note.pinned})


def parse_note_date(value: str) -> "datetime.date | None":
    """
    Parse a date string into a date object.

    :param value: A date string in YYYY-MM-DD format.
    :type value: str
    :return: The parsed date, or None if the value is invalid.
    :rtype: datetime.date or None
    """

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()

    except (TypeError, ValueError):
        return None


def parse_note_time(value: str | None) -> "datetime.time | None":
    """
    Parse a time string into a time object, accepting HH:MM or HH:MM:SS.

    :param value: A time string in HH:MM or HH:MM:SS format.
    :type value: str
    :return: The parsed time, or None if the value is invalid.
    :rtype: datetime.time or None
    """

    value = (value or "").strip()
    if re.match(r"^\d{2}:\d{2}$", value):
        value = f"{value}:00"

    try:
        return datetime.strptime(value, "%H:%M:%S").time()

    except (TypeError, ValueError):
        return None


@app.route("/notes/<int:note_id>/datetime", methods=["POST"])
def update_note_datetime(note_id: int) -> Response:
    """
    Update a note's date and start time, preserving its duration.

    :param note_id: ID of the note.
    :type note_id: int
    :return: A JSON response with the updated datetime fields, or an error.
    :rtype: flask.Response
    """

    note = Note.query.get_or_404(note_id)
    data = request.get_json(silent=True) or {}
    new_date = parse_note_date((data.get("date") or "").strip())
    new_start_time = parse_note_time(data.get("start_time"))

    if not new_date or not new_start_time:
        return jsonify({"error": "Enter a valid date and start time."}), 400

    duration_seconds = duration_seconds_from_times(note.start_time, note.end_time)
    if duration_seconds is None:
        return jsonify({"error": "This note does not have a valid duration."}), 400

    new_start = datetime.combine(new_date, new_start_time)
    new_end = new_start + timedelta(seconds=duration_seconds)

    note.date = new_date.strftime("%Y-%m-%d")
    note.start_time = new_start.strftime("%H:%M:%S")
    note.time = note.start_time
    note.end_time = new_end.strftime("%H:%M:%S")
    db.session.commit()
    return jsonify(
        {
            "date": note.date,
            "start_time": note.start_time,
            "end_time": note.end_time,
        }
    )


@app.route("/notes/<int:note_id>/speakers/<int:speaker_id>/rename", methods=["POST"])
def rename_speaker(note_id: int, speaker_id: int) -> Response:
    """
    Rename a speaker of a note.

    :param note_id: ID of the note.
    :type note_id: int
    :param speaker_id: ID of the speaker.
    :type speaker_id: int
    :return: A JSON response with the updated speaker, or an error.
    :rtype: flask.Response
    """

    speaker = Speaker.query.filter_by(id=speaker_id, note_id=note_id).first_or_404()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "A speaker name is required."}), 400

    speaker.display_name = name[:100]
    db.session.commit()
    return jsonify({"speaker": speaker.to_dict()})


@app.route("/notes/<int:note_id>/retry_transcription", methods=["POST"])
def retry_transcription(note_id: int) -> Response:
    """
    Reset a note's transcription status and re-enqueue it.

    :param note_id: ID of the note.
    :type note_id: int
    :return: A JSON response confirming the retry, or an error.
    :rtype: flask.Response
    """

    note = Note.query.get_or_404(note_id)
    if not note.recording_path:
        return jsonify({"error": "No recording available to retranscribe."}), 400

    audio_path = os.path.join(BASE_DIR, note.recording_path)
    if not os.path.exists(audio_path):
        return jsonify({"error": "Audio file not found."}), 404

    note.transcription_status = TRANSCRIPTION_PENDING
    note.transcription_error = None
    note.key_points_status = KEY_POINTS_PENDING
    note.key_points_error = None
    db.session.commit()
    reset_key_points_offline_retries(note.id)
    enqueue_transcription(note.id, audio_path)
    return jsonify({"message": "Retrying transcription."})


@app.route("/notes/<int:note_id>/retry_key_points", methods=["POST"])
def retry_key_points(note_id: int) -> Response:
    """
    Reset a note's key points status and re-enqueue extraction.

    :param note_id: ID of the note.
    :type note_id: int
    :return: A JSON response confirming the retry, or an error.
    :rtype: flask.Response
    """

    note = Note.query.get_or_404(note_id)
    if note.transcription_status != TRANSCRIPTION_COMPLETED or not note.transcription:
        return jsonify({"error": "Transcript is not available yet."}), 400

    note.key_points_status = KEY_POINTS_PENDING
    note.key_points_error = None
    db.session.commit()
    reset_key_points_offline_retries(note.id)
    transcription_executor.submit(
        extract_key_points,
        note.id,
        note.transcription,
        note.key_points_generation or 0,
    )

    return jsonify({"message": "Retrying key point extraction."})


@app.route("/notes/<int:note_id>/notes", methods=["POST"])
def update_note_rich_notes(note_id: int) -> Response:
    """
    Update a note's rich notes HTML and regenerate key points if ready.

    :param note_id: ID of the note.
    :type note_id: int
    :return: A JSON response with the updated notes state, or 404 if not found.
    :rtype: flask.Response
    """

    note = Note.query.get_or_404(note_id)
    data = request.get_json(silent=True) or {}
    note.notes_html = sanitize_rich_note_html(data.get("notes_html"))
    note.key_points_generation = (note.key_points_generation or 0) + 1
    note.key_points_error = None
    reset_key_points_offline_retries(note.id)

    should_regenerate = (
        note.transcription_status == TRANSCRIPTION_COMPLETED and note.transcription
    )

    if should_regenerate:
        note.key_points_status = KEY_POINTS_PENDING

    elif note.transcription_status not in {
        TRANSCRIPTION_PENDING,
        TRANSCRIPTION_PROCESSING,
    }:
        note.key_points_status = KEY_POINTS_FAILED
        note.key_points_error = "Transcript is not available yet."

    db.session.commit()

    if should_regenerate:
        transcription_executor.submit(
            extract_key_points,
            note.id,
            note.transcription,
            note.key_points_generation,
        )

    return jsonify(
        {
            "message": "Notes updated.",
            "notes_html": note.notes_html or "",
            "key_points_status": note.key_points_status,
        }
    )


@app.route("/update_note/<int:note_id>", methods=["POST"])
def update_note(note_id: int) -> Response:
    """
    Update a note's title and key points.

    :param note_id: ID of the note.
    :type note_id: int
    :return: A JSON response confirming the update, or 404 if not found.
    :rtype: flask.Response
    """

    note = Note.query.get_or_404(note_id)
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    key_points = (data.get("key_points") or "").strip()

    note.title = title[:200] or None
    note.key_points = key_points or None
    db.session.commit()
    return jsonify({"message": "Note updated."})


@app.route("/delete/<int:note_id>", methods=["POST"])
def delete_note(note_id: int) -> Response:
    """
    Delete a note and its recording file.

    :param note_id: ID of the note.
    :type note_id: int
    :return: A JSON response for AJAX requests, or a redirect otherwise.
    :rtype: flask.Response
    """

    note = Note.query.get_or_404(note_id)
    if note.recording_path:
        recording_file_path = os.path.join(BASE_DIR, note.recording_path)
        if os.path.exists(recording_file_path):
            os.remove(recording_file_path)

    db.session.delete(note)
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"message": "Note deleted."})

    return redirect(url_for("index"))
