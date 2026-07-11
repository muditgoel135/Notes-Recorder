import os
import re

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    send_from_directory,
    Response,
)

from extensions import app, db
from models import Note, Tag, Subject, Speaker, get_tag_descendant_ids
from notes_query import (
    build_notes_query,
    parse_notes_filters_from_request,
    check_has_active_transcription,
)
from recordings import allowed_file, note_download_basename, save_audio_file
from transcription import enqueue_transcription, extract_key_points
from config import (
    BASE_DIR,
    RECORDINGS_DIR,
    DEFAULT_PER_PAGE,
    TRANSCRIPTION_PENDING,
    TRANSCRIPTION_COMPLETED,
    KEY_POINTS_PENDING,
)
from transcription import transcription_executor


@app.route("/")
def index():
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
    )


@app.route("/api/notes")
def api_notes():
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
    )

    html = render_template(
        "_notes_list.html",
        notes=pagination.items,
        page=pagination.page,
        total_pages=pagination.pages or 1,
        total=pagination.total,
        has_filters=has_filters,
        subjects=Subject.query.order_by(Subject.name).all(),
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


@app.route("/save_recording", methods=["POST"])
def save_recording():
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


@app.route("/upload", methods=["POST"])
def upload():
    uploaded_file = request.files.get("file")
    if not uploaded_file or uploaded_file.filename == "":
        return redirect(url_for("index"))

    if not allowed_file(uploaded_file.filename):
        return redirect(url_for("index"))

    save_audio_file(uploaded_file, request.form.get("subject") or "Uploaded")
    return redirect(url_for("index"))


@app.route("/recordings/<path:filename>")
def recording_file(filename):
    return send_from_directory(RECORDINGS_DIR, filename)


@app.route("/download_transcript/<int:note_id>")
def download_transcript(note_id):
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
def download_key_points(note_id):
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


@app.route("/api/subjects")
def api_subjects():
    subjects = Subject.query.order_by(Subject.name).all()
    return jsonify({"subjects": [subject.to_dict() for subject in subjects]})


@app.route("/api/subjects", methods=["POST"])
def create_subject():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "A subject name is required."}), 400

    if Subject.query.filter(db.func.lower(Subject.name) == name.lower()).first():
        return jsonify({"error": "That subject already exists."}), 400

    subject = Subject(name=name[:100])
    db.session.add(subject)
    db.session.commit()
    return jsonify({"subject": subject.to_dict()})


@app.route("/api/subjects/<int:subject_id>/delete", methods=["POST"])
def delete_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    db.session.delete(subject)
    db.session.commit()
    return jsonify({"message": "Subject deleted."})


@app.route("/api/tags")
def api_tags():
    tags = Tag.query.order_by(Tag.name).all()
    return jsonify({"tags": [tag.to_dict() for tag in tags]})


@app.route("/api/tags", methods=["POST"])
def create_tag():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    color = (data.get("color") or "").strip()
    parent_id = data.get("parent_id")

    if not name or not re.match(r"^#[0-9a-fA-F]{6}$", color):
        return jsonify({"error": "A tag name and a valid hex color are required."}), 400

    if parent_id is not None:
        parent_id = int(parent_id)
        Tag.query.get_or_404(parent_id)

    tag = Tag(name=name[:100], color=color, parent_id=parent_id)
    db.session.add(tag)
    db.session.commit()
    return jsonify({"tag": tag.to_dict()})


@app.route("/api/tags/<int:tag_id>", methods=["POST"])
def update_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    color = (data.get("color") or "").strip()

    if not name or not re.match(r"^#[0-9a-fA-F]{6}$", color):
        return jsonify({"error": "A tag name and a valid hex color are required."}), 400

    tag.name = name[:100]
    tag.color = color
    db.session.commit()
    return jsonify({"tag": tag.to_dict()})


@app.route("/api/tags/<int:tag_id>/delete", methods=["POST"])
def delete_tag(tag_id):
    Tag.query.get_or_404(tag_id)
    ids_to_delete = get_tag_descendant_ids([tag_id])
    Tag.query.filter(Tag.id.in_(ids_to_delete)).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({"message": "Tag deleted."})


@app.route("/notes/<int:note_id>/tags", methods=["POST"])
def set_note_tags(note_id):
    note = Note.query.get_or_404(note_id)
    data = request.get_json(silent=True) or {}
    tag_ids = [int(tag_id) for tag_id in (data.get("tag_ids") or [])]
    note.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
    db.session.commit()
    return jsonify({"tags": [tag.to_dict() for tag in note.tags]})


@app.route("/notes/<int:note_id>/subject", methods=["POST"])
def update_note_subject(note_id):
    note = Note.query.get_or_404(note_id)
    data = request.get_json(silent=True) or {}
    subject = (data.get("subject") or "").strip()

    if not subject:
        return jsonify({"error": "A subject is required."}), 400

    note.subject = subject[:100]
    db.session.commit()
    return jsonify({"subject": note.subject})


@app.route("/notes/<int:note_id>/speakers/<int:speaker_id>/rename", methods=["POST"])
def rename_speaker(note_id, speaker_id):
    speaker = Speaker.query.filter_by(id=speaker_id, note_id=note_id).first_or_404()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "A speaker name is required."}), 400

    speaker.display_name = name[:100]
    db.session.commit()
    return jsonify({"speaker": speaker.to_dict()})


@app.route("/notes/<int:note_id>/retry_transcription", methods=["POST"])
def retry_transcription(note_id):
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
    enqueue_transcription(note.id, audio_path)
    return jsonify({"message": "Retrying transcription."})


@app.route("/notes/<int:note_id>/retry_key_points", methods=["POST"])
def retry_key_points(note_id):
    note = Note.query.get_or_404(note_id)
    if note.transcription_status != TRANSCRIPTION_COMPLETED or not note.transcription:
        return jsonify({"error": "Transcript is not available yet."}), 400

    note.key_points_status = KEY_POINTS_PENDING
    note.key_points_error = None
    db.session.commit()
    transcription_executor.submit(extract_key_points, note.id, note.transcription)
    return jsonify({"message": "Retrying key point extraction."})


@app.route("/update_note/<int:note_id>", methods=["POST"])
def update_note(note_id):
    note = Note.query.get_or_404(note_id)
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    key_points = (data.get("key_points") or "").strip()

    note.title = title[:200] or None
    note.key_points = key_points or None
    db.session.commit()
    return jsonify({"message": "Note updated."})


@app.route("/delete/<int:note_id>", methods=["POST"])
def delete_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.recording_path:
        recording_file_path = os.path.join(BASE_DIR, note.recording_path)
        if os.path.exists(recording_file_path):
            os.remove(recording_file_path)

    db.session.delete(note)
    db.session.commit()
    return redirect(url_for("index"))
