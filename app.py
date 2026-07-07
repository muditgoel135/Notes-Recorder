from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    send_from_directory,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
import os
import json
import re
import datetime
import socket
import uuid
import threading
import requests
import markdown
from markupsafe import Markup
from concurrent.futures import ThreadPoolExecutor
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()


# Flask settings
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
db = SQLAlchemy(app)
secret_key = os.environ.get("SECRET_KEY", "default_secret_key")
app.config["SECRET_KEY"] = secret_key


LIST_ITEM_RE = re.compile(r"^([ \t]*)([-*+]|\d+\.)\s+")


def normalize_list_indentation(text):
    """Clamp list-item indentation to what's reachable via preceding items.

    LLM-generated markdown sometimes indents top-level bullets by 4 spaces
    with no parent list item above them, which Python-Markdown parses as an
    indented code block instead of a list. This flattens such runaway
    indentation while still allowing genuine nested lists.
    """
    stack = []  # (raw_indent, normalized_indent) per open list level
    lines = []
    for line in text.split("\n"):
        match = LIST_ITEM_RE.match(line)
        if match:
            raw_indent = len(match.group(1).expandtabs())
            while stack and stack[-1][0] > raw_indent:
                stack.pop()

            if stack and stack[-1][0] == raw_indent:
                indent = stack[-1][1]
            elif stack:
                indent = stack[-1][1] + 4
            else:
                indent = 0

            stack.append((raw_indent, indent))
            lines.append(" " * indent + line[match.end(1) :])
        elif line.strip():
            lines.append(line)
            stack = []
        else:
            lines.append(line)
    return "\n".join(lines)


@app.template_filter("markdown")
def render_markdown(text):
    if not text:
        return ""
    return Markup(
        markdown.markdown(
            normalize_list_indentation(text), extensions=["sane_lists"]
        )
    )


@app.template_filter("from_json")
def parse_json(value):
    if not value:
        return []
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return []


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
if not os.path.exists(RECORDINGS_DIR):
    os.makedirs(RECORDINGS_DIR)

ALLOWED_EXTENSIONS = {"wav", "mp3", "ogg", "webm", "m4a", "mp4"}
TRANSCRIPTION_PENDING = "pending"
TRANSCRIPTION_PROCESSING = "processing"
TRANSCRIPTION_COMPLETED = "completed"
TRANSCRIPTION_FAILED = "failed"
WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "base")
TRANSCRIBE_EXISTING_ON_STARTUP = (
    os.environ.get("TRANSCRIBE_EXISTING_ON_STARTUP", "true").lower() != "false"
)

KEY_POINTS_PENDING = "pending"
KEY_POINTS_PROCESSING = "processing"
KEY_POINTS_COMPLETED = "completed"
KEY_POINTS_FAILED = "failed"
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_CHAT_URL = "https://ollama.com/api/chat"
KEY_POINTS_RETRY_SECONDS = int(os.environ.get("KEY_POINTS_RETRY_SECONDS", "30"))
transcription_executor = ThreadPoolExecutor(max_workers=1)
whisper_model = None
whisper_model_lock = threading.Lock()


# Database model
class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False)
    time = db.Column(db.String(8), nullable=False)
    start_time = db.Column(db.String(8), nullable=False)
    end_time = db.Column(db.String(8), nullable=True)
    subject = db.Column(db.String(100), nullable=True)
    recording_path = db.Column(db.String(200), nullable=True)
    transcription = db.Column(db.Text, nullable=True)
    transcription_segments = db.Column(db.Text, nullable=True)
    transcription_status = db.Column(
        db.String(20), nullable=False, default=TRANSCRIPTION_PENDING
    )

    transcription_error = db.Column(db.Text, nullable=True)
    title = db.Column(db.String(200), nullable=True)
    key_points = db.Column(db.Text, nullable=True)
    key_points_status = db.Column(
        db.String(20), nullable=False, default=KEY_POINTS_PENDING
    )

    key_points_error = db.Column(db.Text, nullable=True)


def init_database():
    db.create_all()
    inspector = inspect(db.engine)
    if "note" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("note")}
    required_columns = {
        "date": "VARCHAR(10) NOT NULL DEFAULT ''",
        "time": "VARCHAR(8) NOT NULL DEFAULT ''",
        "start_time": "VARCHAR(8) NOT NULL DEFAULT ''",
        "end_time": "VARCHAR(8)",
        "subject": "VARCHAR(100)",
        "recording_path": "VARCHAR(200)",
        "transcription": "TEXT",
        "transcription_segments": "TEXT",
        "transcription_status": f"VARCHAR(20) NOT NULL DEFAULT '{TRANSCRIPTION_PENDING}'",
        "transcription_error": "TEXT",
        "title": "VARCHAR(200)",
        "key_points": "TEXT",
        "key_points_status": f"VARCHAR(20) NOT NULL DEFAULT '{KEY_POINTS_PENDING}'",
        "key_points_error": "TEXT",
    }

    with db.engine.begin() as connection:
        for column_name, column_definition in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE note ADD COLUMN {column_name} {column_definition}"
                    )
                )


DEFAULT_PER_PAGE = 30


def build_notes_query(
    search=None, date_from=None, date_to=None, time_from=None, time_to=None
):
    query = Note.query

    if search:
        like_pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                Note.title.ilike(like_pattern),
                Note.transcription.ilike(like_pattern),
                Note.subject.ilike(like_pattern),
                Note.key_points.ilike(like_pattern),
            )
        )

    if date_from:
        query = query.filter(Note.date >= date_from)

    if date_to:
        query = query.filter(Note.date <= date_to)

    if time_from:
        query = query.filter(
            Note.start_time >= (time_from + ":00" if len(time_from) == 5 else time_from)
        )

    if time_to:
        query = query.filter(
            Note.start_time <= (time_to + ":59" if len(time_to) == 5 else time_to)
        )

    return query.order_by(Note.id.desc())


def parse_notes_filters_from_request():
    return {
        "search": (request.args.get("q") or "").strip(),
        "date_from": (request.args.get("date_from") or "").strip() or None,
        "date_to": (request.args.get("date_to") or "").strip() or None,
        "time_from": (request.args.get("time_from") or "").strip() or None,
        "time_to": (request.args.get("time_to") or "").strip() or None,
    }


def check_has_active_transcription():
    return db.session.query(
        Note.query.filter(
            db.or_(
                Note.transcription_status.in_(
                    [TRANSCRIPTION_PENDING, TRANSCRIPTION_PROCESSING]
                ),
                Note.key_points_status.in_([KEY_POINTS_PENDING, KEY_POINTS_PROCESSING]),
            )
        ).exists()
    ).scalar()


# Flask routes
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
    )

    return render_template(
        "index.html",
        notes=pagination.items,
        page=pagination.page,
        total_pages=pagination.pages or 1,
        total=pagination.total,
        has_active_transcription=has_active_transcription,
        has_filters=has_filters,
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
    )

    html = render_template(
        "_notes_list.html",
        notes=pagination.items,
        page=pagination.page,
        total_pages=pagination.pages or 1,
        total=pagination.total,
        has_filters=has_filters,
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


def is_internet_available(host="8.8.8.8", port=53, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_whisper_model():
    global whisper_model
    if whisper_model is None:
        with whisper_model_lock:
            if whisper_model is None:
                import whisper

                whisper_model = whisper.load_model(WHISPER_MODEL_NAME)

    return whisper_model


def update_transcription_status(
    note_id, status, transcription=None, segments=None, error=None
):
    note = db.session.get(Note, note_id)
    if not note:
        return None

    note.transcription_status = status
    if transcription is not None:
        note.transcription = transcription

    if segments is not None:
        note.transcription_segments = segments

    note.transcription_error = error
    db.session.commit()
    return note


def update_key_points_status(note_id, status, title=None, key_points=None, error=None):
    note = db.session.get(Note, note_id)
    if not note:
        return None

    note.key_points_status = status
    if title is not None:
        note.title = title

    if key_points is not None:
        note.key_points = key_points

    note.key_points_error = error
    db.session.commit()
    return note


HINDI_SUBJECT = "Hindi"
HINDI_INITIAL_PROMPT = (
    "यह एक हिंदी कक्षा की रिकॉर्डिंग है। बातचीत मुख्यतः हिंदी में है, "
    "लेकिन बीच-बीच में अंग्रेजी शब्द और वाक्य भी बोले जाते हैं, "
    "जिन्हें अंग्रेजी में ही लिखा जाना चाहिए।"
)


def transcribe_note(note_id, audio_path):
    with app.app_context():
        try:
            note = update_transcription_status(note_id, TRANSCRIPTION_PROCESSING)
            if not note:
                return

            transcribe_kwargs = {"fp16": False, "word_timestamps": True}
            if note.subject == HINDI_SUBJECT:
                transcribe_kwargs["language"] = "hi"
                transcribe_kwargs["initial_prompt"] = HINDI_INITIAL_PROMPT

            result = get_whisper_model().transcribe(audio_path, **transcribe_kwargs)
            transcription = (result.get("text") or "").strip()
            words = [
                {"s": word["start"], "w": word["word"]}
                for segment in result.get("segments") or []
                for word in segment.get("words") or []
            ]
            segments_json = json.dumps(words) if words else None
            update_transcription_status(
                note_id,
                TRANSCRIPTION_COMPLETED,
                transcription=transcription,
                segments=segments_json,
                error=None,
            )

        except Exception as exc:
            db.session.rollback()
            error_message = str(exc).strip() or exc.__class__.__name__
            update_transcription_status(
                note_id,
                TRANSCRIPTION_FAILED,
                error=error_message[:1000],
            )
            return

        extract_key_points(note_id, transcription)


def extract_key_points(note_id, transcript):
    with app.app_context():
        if not transcript:
            update_key_points_status(
                note_id, KEY_POINTS_FAILED, error="No transcript to summarize."
            )
            return

        if not OLLAMA_API_KEY:
            update_key_points_status(
                note_id,
                KEY_POINTS_FAILED,
                error="OLLAMA_API_KEY is not configured.",
            )
            return

        if not is_internet_available():
            update_key_points_status(
                note_id,
                KEY_POINTS_PENDING,
                error="Waiting for an internet connection to reach Ollama.",
            )
            threading.Timer(
                KEY_POINTS_RETRY_SECONDS,
                lambda: transcription_executor.submit(
                    extract_key_points, note_id, transcript
                ),
            ).start()
            return

        try:
            update_key_points_status(note_id, KEY_POINTS_PROCESSING)
            response = requests.post(
                OLLAMA_CHAT_URL,
                headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "You are given a class recording transcript. Respond "
                                "with ONLY a JSON object of the form "
                                '{"title": "short descriptive title (max 8 words)", '
                                '"key_points": "markdown notes summarizing the '
                                "transcript\"}. In key_points, use '## ' headings "
                                "to group related points into sections when the "
                                "transcript covers multiple topics, and '-' for "
                                "bullets under each heading. Nested bullets must be "
                                "indented by exactly 4 spaces per level (required "
                                "for the list to render as nested). Bold with "
                                "**text** where useful. No preamble or closing "
                                f"remarks.\n\nTranscript:\n{transcript}"
                            ),
                        }
                    ],
                    "format": "json",
                    "stream": False,
                },
                timeout=120,
            )

            response.raise_for_status()
            content = (
                response.json().get("message", {}).get("content", "") or ""
            ).strip()

            if not content:
                raise ValueError("Ollama returned an empty response.")

            parsed = json.loads(content)
            title = (parsed.get("title") or "").strip()
            key_points = (parsed.get("key_points") or "").strip()

            if not key_points:
                raise ValueError("Ollama returned no key points.")

            update_key_points_status(
                note_id,
                KEY_POINTS_COMPLETED,
                title=title[:200] or None,
                key_points=key_points,
                error=None,
            )

        except Exception as exc:
            db.session.rollback()
            error_message = str(exc).strip() or exc.__class__.__name__
            update_key_points_status(
                note_id, KEY_POINTS_FAILED, error=error_message[:1000]
            )


def enqueue_transcription(note_id, audio_path):
    transcription_executor.submit(transcribe_note, note_id, audio_path)


def enqueue_existing_transcriptions():
    notes = Note.query.filter(
        Note.transcription_status.in_(
            [TRANSCRIPTION_PENDING, TRANSCRIPTION_PROCESSING]
        ),
        Note.recording_path.isnot(None),
    ).all()

    for note in notes:
        audio_path = os.path.join(BASE_DIR, note.recording_path)
        if os.path.exists(audio_path):
            enqueue_transcription(note.id, audio_path)
        else:
            note.transcription_status = TRANSCRIPTION_FAILED
            note.transcription_error = "Audio file not found."

    db.session.commit()


def enqueue_existing_key_points():
    notes = Note.query.filter(
        Note.transcription_status == TRANSCRIPTION_COMPLETED,
        Note.key_points_status.in_([KEY_POINTS_PENDING, KEY_POINTS_PROCESSING]),
    ).all()

    for note in notes:
        transcription_executor.submit(extract_key_points, note.id, note.transcription)


def save_audio_file(file_storage, subject, start_time=None, end_time=None):
    now = datetime.datetime.now()
    date = now.strftime("%Y-%m-%d")
    start_time = start_time or now.strftime("%H:%M:%S")
    end_time = end_time or now.strftime("%H:%M:%S")
    extension = file_storage.filename.rsplit(".", 1)[1].lower()
    safe_subject = secure_filename(subject or "unnamed") or "unnamed"
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{safe_subject}_{uuid.uuid4().hex}.{extension}"
    file_path = os.path.join(RECORDINGS_DIR, filename)
    file_storage.save(file_path)

    relative_path = f"recordings/{filename}"
    new_note = Note(
        date=date,
        time=start_time,
        start_time=start_time,
        end_time=end_time,
        subject=subject,
        recording_path=relative_path,
        transcription_status=TRANSCRIPTION_PENDING,
    )

    db.session.add(new_note)
    db.session.commit()
    enqueue_transcription(new_note.id, file_path)
    return new_note


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


with app.app_context():
    init_database()
    if TRANSCRIBE_EXISTING_ON_STARTUP:
        enqueue_existing_transcriptions()
        enqueue_existing_key_points()


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
