import datetime
import json
import os
import shutil
import subprocess
import uuid

from werkzeug.utils import secure_filename

from extensions import db
from models import Note, RecordingSession
from config import ALLOWED_EXTENSIONS, RECORDINGS_DIR, TRANSCRIPTION_PENDING
from transcription import enqueue_transcription

if not os.path.exists(RECORDINGS_DIR):
    os.makedirs(RECORDINGS_DIR)

SESSION_CHUNKS_DIR = os.path.join(RECORDINGS_DIR, "session_chunks")
ACTIVE_RECORDING_STATUS = "active"
FINISHED_RECORDING_STATUS = "finished"
CANCELED_RECORDING_STATUS = "canceled"


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


def create_recording_session(subject, mime_type, extension, start_time=None):
    now = datetime.datetime.now()
    session = RecordingSession(
        session_key=uuid.uuid4().hex,
        subject=(subject or "unnamed")[:100],
        start_time=start_time or now.strftime("%H:%M:%S"),
        status=ACTIVE_RECORDING_STATUS,
        mime_type=(mime_type or "")[:100],
        extension=extension if extension in ALLOWED_EXTENSIONS else "webm",
        segments_json="[]",
    )
    db.session.add(session)
    db.session.commit()
    os.makedirs(get_session_chunk_dir(session), exist_ok=True)
    return session


def get_session_chunk_dir(session):
    return os.path.join(SESSION_CHUNKS_DIR, session.session_key)


def get_session_by_key(session_key):
    return RecordingSession.query.filter_by(session_key=session_key).first()


def save_recording_chunk(session, chunk_file, segment_index, chunk_index):
    if session.status != ACTIVE_RECORDING_STATUS:
        raise ValueError("Recording session is not active.")

    segment_index = max(0, int(segment_index))
    chunk_index = max(0, int(chunk_index))
    chunk_dir = get_session_chunk_dir(session)
    os.makedirs(chunk_dir, exist_ok=True)
    filename = (
        f"segment_{segment_index:04d}_chunk_{chunk_index:06d}.{session.extension}"
    )
    chunk_file.save(os.path.join(chunk_dir, filename))

    segments = set(json.loads(session.segments_json or "[]"))
    segments.add(segment_index)
    session.segments_json = json.dumps(sorted(segments))
    session.chunk_count = (session.chunk_count or 0) + 1
    db.session.commit()


def finish_recording_session(session, end_time=None):
    if session.status == FINISHED_RECORDING_STATUS and session.note_id:
        return session.note
    if session.status != ACTIVE_RECORDING_STATUS:
        raise ValueError("Recording session is not active.")

    chunk_dir = get_session_chunk_dir(session)
    chunks = (
        sorted(
            filename
            for filename in os.listdir(chunk_dir)
            if filename.endswith(f".{session.extension}")
            and filename.startswith("segment_")
        )
        if os.path.exists(chunk_dir)
        else []
    )
    if not chunks:
        raise ValueError("No recording chunks were received.")

    now = datetime.datetime.now()
    end_time = end_time or now.strftime("%H:%M:%S")
    final_path = build_recording_path(session, now)
    segment_paths = build_segment_files(session, chunks)

    try:
        if len(segment_paths) == 1:
            shutil.move(segment_paths[0], final_path)
        else:
            concat_segments(segment_paths, final_path)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as error:
        raise ValueError("Could not assemble recording chunks.") from error

    relative_path = f"recordings/{os.path.basename(final_path)}"
    note = Note(
        date=now.strftime("%Y-%m-%d"),
        time=session.start_time,
        start_time=session.start_time,
        end_time=end_time,
        subject=session.subject,
        recording_path=relative_path,
        transcription_status=TRANSCRIPTION_PENDING,
    )
    db.session.add(note)
    db.session.flush()

    session.status = FINISHED_RECORDING_STATUS
    session.end_time = end_time
    session.note_id = note.id
    db.session.commit()

    shutil.rmtree(chunk_dir, ignore_errors=True)
    enqueue_transcription(note.id, final_path)
    return note


def cancel_recording_session(session):
    if session.status == FINISHED_RECORDING_STATUS:
        raise ValueError("Finished recordings cannot be canceled.")
    session.status = CANCELED_RECORDING_STATUS
    db.session.commit()
    shutil.rmtree(get_session_chunk_dir(session), ignore_errors=True)


def build_recording_path(session, now):
    safe_subject = secure_filename(session.subject or "unnamed") or "unnamed"
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{safe_subject}_{uuid.uuid4().hex}.{session.extension}"
    return os.path.join(RECORDINGS_DIR, filename)


def build_segment_files(session, chunks):
    chunk_dir = get_session_chunk_dir(session)
    segments = {}
    for filename in chunks:
        segment_id = filename.split("_chunk_", 1)[0].replace("segment_", "")
        segments.setdefault(segment_id, []).append(filename)

    segment_paths = []
    for segment_id in sorted(segments):
        segment_path = os.path.join(
            chunk_dir, f"segment_{segment_id}.{session.extension}"
        )
        with open(segment_path, "wb") as output_file:
            for filename in sorted(segments[segment_id]):
                with open(os.path.join(chunk_dir, filename), "rb") as input_file:
                    shutil.copyfileobj(input_file, output_file)
        segment_paths.append(segment_path)
    return segment_paths


def concat_segments(segment_paths, final_path):
    list_path = f"{final_path}.concat.txt"
    with open(list_path, "w", encoding="utf-8") as list_file:
        for path in segment_paths:
            escaped_path = path.replace("\\", "/").replace("'", "'\\''")
            list_file.write(f"file '{escaped_path}'\n")

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_path,
                "-c",
                "copy",
                final_path,
            ],
            check=True,
            capture_output=True,
        )
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)
