import datetime
import os
import uuid

from werkzeug.utils import secure_filename

from extensions import db
from models import Note
from config import ALLOWED_EXTENSIONS, RECORDINGS_DIR, TRANSCRIPTION_PENDING
from transcription import enqueue_transcription

if not os.path.exists(RECORDINGS_DIR):
    os.makedirs(RECORDINGS_DIR)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def note_download_basename(note):
    safe_subject = secure_filename(note.title or note.subject or "note") or "note"
    return f"{note.date}_{safe_subject}"


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
