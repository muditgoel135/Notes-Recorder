"""

This module defines the bulk note operation routes for the Notes-Recorder
application, including bulk deletion, subject updates, tagging, and export.

"""

# Import required modules
import io
import os
import zipfile
from datetime import datetime, timezone
from flask import Response, request, jsonify, send_file

# Import core extensions, models, and config
from core.extensions import app, db
from core.models import Note, Tag
from core.config import BASE_DIR, DEFAULT_UNIT

# Import audio and services helpers
from audio.recordings import note_download_basename
from audio.transcription import format_transcript_with_speakers
from services.text_filters import (
    rich_note_html_to_text,
    format_display_date,
    format_display_time,
)


def parse_bulk_note_ids(data: dict) -> list[int]:
    """
    Parse and deduplicate a list of note ids from a request JSON payload.

    :param data: The parsed JSON request body.
    :type data: dict
    :return: A list of unique integer note ids.
    :rtype: list of int
    """

    note_ids = []
    seen = set()
    for value in data.get("note_ids") or []:
        if str(value).isdigit():
            note_id = int(value)
            if note_id not in seen:
                seen.add(note_id)
                note_ids.append(note_id)
    return note_ids


def unique_zip_foldername(base: str, used_names: set[str]) -> str:
    """
    Return a folder name based on base that has not been used in a zip yet.

    Appends a numeric suffix when base is already taken so notes with the same
    date and subject do not collide inside an export archive.

    :param base: The preferred folder name.
    :type base: str
    :param used_names: A set of folder names already written.
    :type used_names: set of str
    :return: A unique folder name.
    :rtype: str
    """

    candidate = base or "note"
    index = 2
    while candidate in used_names:
        candidate = f"{base}_{index}"
        index += 1
    used_names.add(candidate)
    return candidate


@app.route("/api/notes/bulk_delete", methods=["POST"])
def bulk_delete_notes() -> Response:
    """
    Delete multiple notes and their recording files at once.

    :return: A JSON response with the number of deleted notes, or an error.
    :rtype: flask.Response
    """

    data = request.get_json(silent=True) or {}
    note_ids = parse_bulk_note_ids(data)
    if not note_ids:
        return jsonify({"error": "No notes selected."}), 400

    notes = Note.query.filter(Note.id.in_(note_ids)).all()
    deleted_ids = []
    for note in notes:
        if note.recording_path:
            recording_file_path = os.path.join(BASE_DIR, note.recording_path)
            if os.path.exists(recording_file_path):
                os.remove(recording_file_path)

        deleted_ids.append(note.id)
        db.session.delete(note)

    db.session.commit()
    return jsonify(
        {
            "message": f"{len(notes)} recording{'s' if len(notes) != 1 else ''} deleted.",
            "deleted": deleted_ids,
        }
    )


@app.route("/api/notes/bulk_subject", methods=["POST"])
def bulk_update_subjects() -> Response:
    """
    Change the subject of multiple notes at once.

    :return: A JSON response with the number of updated notes, or an error.
    :rtype: flask.Response
    """

    data = request.get_json(silent=True) or {}
    note_ids = parse_bulk_note_ids(data)
    subject = (data.get("subject") or "").strip()

    if not note_ids:
        return jsonify({"error": "No notes selected."}), 400

    if not subject:
        return jsonify({"error": "A subject is required."}), 400

    count = Note.query.filter(Note.id.in_(note_ids)).update(
        {"subject": subject[:100], "unit": DEFAULT_UNIT},
        synchronize_session=False,
    )
    db.session.commit()
    return jsonify(
        {
            "message": f"{count} recording{'s' if count != 1 else ''} updated.",
            "subject": subject,
        }
    )


@app.route("/api/notes/bulk_add_tag", methods=["POST"])
def bulk_add_tag() -> Response:
    """
    Add one tag to multiple notes, preserving each note's existing tags.

    :return: A JSON response with the number of updated notes, or an error.
    :rtype: flask.Response
    """

    data = request.get_json(silent=True) or {}
    note_ids = parse_bulk_note_ids(data)
    tag_id = data.get("tag_id")

    if not note_ids:
        return jsonify({"error": "No notes selected."}), 400

    if tag_id is None or not str(tag_id).isdigit():
        return jsonify({"error": "A tag is required."}), 400

    tag = Tag.query.get(int(tag_id))
    if not tag:
        return jsonify({"error": "Tag not found."}), 404

    notes = Note.query.filter(Note.id.in_(note_ids)).all()
    updated = 0
    for note in notes:
        if tag not in note.tags:
            note.tags.append(tag)
            updated += 1

    db.session.commit()
    return jsonify(
        {
            "message": f"{updated} recording{'s' if updated != 1 else ''} updated.",
            "tag": tag.to_dict(),
        }
    )


@app.route("/api/notes/bulk_export", methods=["POST"])
def bulk_export_notes() -> Response:
    """
    Export multiple notes as a zip of their recording files, transcripts,
    key points, and rich-note text.

    :return: The zip archive as an attachment, or an error.
    :rtype: flask.Response
    """

    data = request.get_json(silent=True) or {}
    note_ids = parse_bulk_note_ids(data)
    if not note_ids:
        return jsonify({"error": "No notes selected."}), 400

    notes = (
        Note.query.filter(Note.id.in_(note_ids))
        .order_by(Note.date, Note.start_time, Note.id)
        .all()
    )
    if not notes:
        return jsonify({"error": "No matching recordings found."}), 404

    buffer = io.BytesIO()
    used_names = set()
    summary_lines = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for note in notes:
            folder = unique_zip_foldername(note_download_basename(note), used_names)

            if note.recording_path:
                recording_file_path = os.path.join(BASE_DIR, note.recording_path)
                if os.path.exists(recording_file_path):
                    extension = note.recording_path.rsplit(".", 1)[-1]
                    zip_file.write(
                        recording_file_path,
                        f"{folder}/recording.{extension}",
                    )

            if note.transcription:
                transcript = (
                    format_transcript_with_speakers(note)
                    if note.speakers
                    else note.transcription
                )
                zip_file.writestr(f"{folder}/transcript.txt", transcript)

            if note.key_points:
                zip_file.writestr(f"{folder}/key_points.md", note.key_points)

            user_notes = rich_note_html_to_text(note.notes_html)
            if user_notes:
                zip_file.writestr(f"{folder}/notes.txt", user_notes)

            summary_lines.append(
                "\n".join(
                    [
                        f"ID: {note.id}",
                        f"Subject: {note.subject or 'Untitled'}",
                        f"Title: {note.title or 'No title'}",
                        f"Date: {format_display_date(note.date)}",
                        f"Time: {format_display_time(note.start_time)} - {format_display_time(note.end_time)}",
                        "Tags: " + (", ".join(tag.name for tag in note.tags) or "None"),
                    ]
                )
            )

        if summary_lines:
            zip_file.writestr("summary.txt", "\n\n---\n\n".join(summary_lines))

    buffer.seek(0)
    filename = (
        f"notes_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
    )
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )
