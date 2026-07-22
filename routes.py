import os
import re
from datetime import datetime, timedelta

import requests
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
from models import (
    ChatMessage,
    ChatSession,
    Note,
    Tag,
    Subject,
    Speaker,
    get_tag_descendant_ids,
)
from notes_query import (
    build_notes_query,
    parse_notes_filters_from_request,
    check_has_active_transcription,
)
from recordings import (
    ACTIVE_RECORDING_STATUS,
    allowed_file,
    cancel_recording_session,
    create_recording_session,
    finish_recording_session,
    get_session_by_key,
    note_download_basename,
    save_audio_file,
    save_recording_chunk,
    duration_seconds_from_times,
)
from transcription import (
    enqueue_transcription,
    extract_key_points,
    format_transcript_with_speakers,
    is_internet_available,
)
from text_filters import render_markdown
from config import (
    BASE_DIR,
    RECORDINGS_DIR,
    DEFAULT_PER_PAGE,
    OLLAMA_API_KEY,
    OLLAMA_CHAT_URL,
    OLLAMA_MODEL,
    TRANSCRIPTION_PENDING,
    TRANSCRIPTION_COMPLETED,
    KEY_POINTS_PENDING,
)
from transcription import transcription_executor


def serialize_chat_note(note, include_preview=True):
    preview_source = note.key_points or note.transcription or ""
    preview = preview_source.strip().replace("\r\n", "\n")
    if len(preview) > 240:
        preview = preview[:240].rstrip() + "..."

    data = {
        "id": note.id,
        "title": note.title,
        "subject": note.subject,
        "date": note.date,
        "start_time": note.start_time,
        "end_time": note.end_time,
        "tags": [tag.to_dict() for tag in note.tags],
    }
    if include_preview:
        data["preview"] = preview
    return data


def serialize_chat_message(message):
    data = {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
    }
    if message.role == "assistant":
        data["html"] = str(render_markdown(message.content))
    return data


def serialize_chat_session(session, include_messages=False):
    data = {
        "id": session.id,
        "title": session.title or f"Chat {session.id}",
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "notes": [
            serialize_chat_note(note, include_preview=False) for note in session.notes
        ],
        "message_count": len(session.messages),
    }
    if include_messages:
        data["messages"] = [
            serialize_chat_message(message) for message in session.messages
        ]
    return data


def transcript_context_for_note(note):
    transcript = (
        format_transcript_with_speakers(note) if note.speakers else note.transcription
    )
    parts = [
        f"Recording ID: {note.id}",
        f"Subject: {note.subject or 'Untitled'}",
        f"Title: {note.title or 'No title'}",
        f"Date/time: {note.date} {note.start_time or ''}-{note.end_time or ''}".strip(),
    ]
    if note.tags:
        parts.append("Tags: " + ", ".join(tag.name for tag in note.tags))
    if note.key_points:
        parts.append(f"Key points:\n{note.key_points}")
    parts.append(f"Transcript:\n{transcript or ''}")
    return "\n".join(parts)


def call_ollama_for_chat(session):
    if not OLLAMA_API_KEY:
        return None, ("OLLAMA_API_KEY is not configured.", 503)

    if not is_internet_available():
        return None, ("No internet connection available to reach Ollama.", 503)

    context = "\n\n---\n\n".join(
        transcript_context_for_note(note) for note in session.notes
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You answer questions about the user's selected class recordings. "
                "Use only the supplied recording context and prior chat messages. "
                "If the answer is not supported by the selected recordings, say so. "
                "When useful, cite recordings by subject/title/date rather than by ID.\n\n"
                f"Selected recording context:\n{context}"
            ),
        }
    ]
    messages.extend(
        {"role": message.role, "content": message.content}
        for message in session.messages
        if message.role in {"user", "assistant"}
    )

    try:
        response = requests.post(
            OLLAMA_CHAT_URL,
            headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
    except (requests.ConnectionError, requests.Timeout) as exc:
        return None, (str(exc) or "Could not reach Ollama.", 503)
    except requests.HTTPError as exc:
        detail = str(exc)
        try:
            detail = response.json().get("error") or detail
        except (ValueError, AttributeError):
            pass
        return None, (detail, 502)
    except requests.RequestException as exc:
        return None, (str(exc) or "Ollama request failed.", 502)

    try:
        content = (response.json().get("message", {}).get("content", "") or "").strip()
    except (ValueError, AttributeError):
        return None, ("Ollama returned a malformed response.", 502)

    if not content:
        return None, ("Ollama returned an empty response.", 502)
    return content, None


@app.route("/chat")
def chat():
    return render_template("chat.html")


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


@app.route("/api/chat/recordings")
def api_chat_recordings():
    filters = parse_notes_filters_from_request()
    notes = (
        build_notes_query(**filters)
        .filter(Note.transcription_status == TRANSCRIPTION_COMPLETED)
        .filter(Note.transcription.isnot(None))
        .limit(100)
        .all()
    )
    return jsonify({"recordings": [serialize_chat_note(note) for note in notes]})


@app.route("/api/chat/sessions")
def api_chat_sessions():
    sessions = ChatSession.query.order_by(ChatSession.updated_at.desc()).all()
    return jsonify(
        {"sessions": [serialize_chat_session(session) for session in sessions]}
    )


@app.route("/api/chat/sessions/<int:session_id>")
def api_chat_session(session_id):
    session = ChatSession.query.get_or_404(session_id)
    return jsonify({"session": serialize_chat_session(session, include_messages=True)})


@app.route("/api/chat/sessions", methods=["POST"])
def create_chat_session():
    data = request.get_json(silent=True) or {}
    note_ids = [
        int(note_id)
        for note_id in (data.get("note_ids") or [])
        if str(note_id).isdigit()
    ]
    if not note_ids:
        return jsonify({"error": "Choose at least one recording to chat about."}), 400

    notes = (
        Note.query.filter(Note.id.in_(note_ids))
        .filter(Note.transcription_status == TRANSCRIPTION_COMPLETED)
        .filter(Note.transcription.isnot(None))
        .all()
    )
    found_ids = {note.id for note in notes}
    if len(found_ids) != len(set(note_ids)):
        return (
            jsonify(
                {"error": "All selected recordings must have completed transcripts."}
            ),
            400,
        )

    first_note = notes[0]
    title = (data.get("title") or "").strip()
    if not title:
        title = first_note.title or first_note.subject or "Recording chat"
        if len(notes) > 1:
            title = f"{title} + {len(notes) - 1} more"

    session = ChatSession(title=title[:200], notes=notes)
    db.session.add(session)
    db.session.commit()
    return jsonify({"session": serialize_chat_session(session, include_messages=True)})


@app.route("/api/chat/sessions/<int:session_id>/messages", methods=["POST"])
def create_chat_message(session_id):
    session = ChatSession.query.get_or_404(session_id)
    data = request.get_json(silent=True) or {}
    content = (data.get("message") or "").strip()
    if not content:
        return jsonify({"error": "Enter a message first."}), 400

    transcript_ready_notes = [
        note
        for note in session.notes
        if note.transcription_status == TRANSCRIPTION_COMPLETED and note.transcription
    ]
    if not transcript_ready_notes or len(transcript_ready_notes) != len(session.notes):
        return (
            jsonify(
                {"error": "This chat has recordings without completed transcripts."}
            ),
            400,
        )

    user_message = ChatMessage(session=session, role="user", content=content)
    session.updated_at = datetime.utcnow()
    db.session.add(user_message)
    db.session.commit()

    answer, error = call_ollama_for_chat(session)
    if error:
        message, status_code = error
        return (
            jsonify(
                {"error": message, "user_message": serialize_chat_message(user_message)}
            ),
            status_code,
        )

    assistant_message = ChatMessage(session=session, role="assistant", content=answer)
    session.updated_at = datetime.utcnow()
    db.session.add(assistant_message)
    db.session.commit()

    return jsonify(
        {
            "message": serialize_chat_message(assistant_message),
            "user_message": serialize_chat_message(user_message),
            "session": serialize_chat_session(session),
            "model": OLLAMA_MODEL,
        }
    )


@app.route("/api/chat/sessions/<int:session_id>/title", methods=["POST"])
def update_chat_session_title(session_id):
    session = ChatSession.query.get_or_404(session_id)
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "A title is required."}), 400

    session.title = title[:200]
    session.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"session": serialize_chat_session(session, include_messages=True)})


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


@app.route("/api/recording_sessions", methods=["POST"])
def create_recording_session_route():
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
def get_recording_session_route(session_key):
    session = get_session_by_key(session_key)
    if not session:
        return jsonify({"error": "Recording session was not found."}), 404
    return jsonify({"session": session.to_dict()})


@app.route("/api/recording_sessions/<session_key>/chunks", methods=["POST"])
def save_recording_chunk_route(session_key):
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


@app.route("/api/recording_sessions/<session_key>/finish", methods=["POST"])
def finish_recording_session_route(session_key):
    session = get_session_by_key(session_key)
    if not session:
        return jsonify({"error": "Recording session was not found."}), 404

    data = request.get_json(silent=True) or {}
    end_time = (data.get("end_time") or "").strip() or None
    try:
        note = finish_recording_session(session, end_time)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify({"message": "Recording saved.", "id": note.id})


@app.route("/api/recording_sessions/<session_key>/cancel", methods=["POST"])
def cancel_recording_session_route(session_key):
    session = get_session_by_key(session_key)
    if not session:
        return jsonify({"error": "Recording session was not found."}), 404

    try:
        cancel_recording_session(session)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify({"message": "Recording canceled."})


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


def parse_note_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def parse_note_time(value):
    value = (value or "").strip()
    if re.match(r"^\d{2}:\d{2}$", value):
        value = f"{value}:00"

    try:
        return datetime.strptime(value, "%H:%M:%S").time()
    except (TypeError, ValueError):
        return None


@app.route("/notes/<int:note_id>/datetime", methods=["POST"])
def update_note_datetime(note_id):
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

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"message": "Note deleted."})
    return redirect(url_for("index"))
