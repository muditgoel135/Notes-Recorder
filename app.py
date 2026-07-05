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
import datetime
import uuid
from werkzeug.utils import secure_filename

# Flask settings
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
db = SQLAlchemy(app)
secret_key = os.environ.get("SECRET_KEY", "default_secret_key")
app.config["SECRET_KEY"] = secret_key


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
if not os.path.exists(RECORDINGS_DIR):
    os.makedirs(RECORDINGS_DIR)
ALLOWED_EXTENSIONS = {"wav", "mp3", "ogg", "webm", "m4a", "mp4"}


# Database model
class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False)
    time = db.Column(db.String(8), nullable=False)
    start_time = db.Column(db.String(8), nullable=False)
    end_time = db.Column(db.String(8), nullable=True)
    subject = db.Column(db.String(100), nullable=True)
    recording_path = db.Column(db.String(200), nullable=True)


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
    }

    with db.engine.begin() as connection:
        for column_name, column_definition in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE note ADD COLUMN {column_name} {column_definition}"
                    )
                )


# Flask routes
@app.route("/")
def index():
    notes = Note.query.order_by(Note.id.desc()).all()
    return render_template("index.html", notes=notes)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


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
    )
    db.session.add(new_note)
    db.session.commit()
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


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
