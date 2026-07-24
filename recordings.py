import datetime
import json
import os
import shutil
import struct
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
WEBM_INFO_ID = bytes.fromhex("1549a966")
WEBM_SEGMENT_ID = bytes.fromhex("18538067")
WEBM_TRACKS_ID = bytes.fromhex("1654ae6b")
WEBM_DURATION_ID = bytes.fromhex("4489")


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

    if extension == "webm":
        add_webm_duration_metadata(
            file_path, duration_seconds_from_times(start_time, end_time)
        )

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

    if session.extension == "webm":
        add_webm_duration_metadata(
            final_path, duration_seconds_from_times(session.start_time, end_time)
        )

    relative_path = f"recordings/{os.path.basename(final_path)}"
    note = Note(
        date=now.strftime("%Y-%m-%d"),
        time=session.start_time,
        start_time=session.start_time,
        end_time=end_time,
        subject=session.subject,
        recording_path=relative_path,
        notes_html=session.notes_html,
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


def duration_seconds_from_times(start_time, end_time):
    if not start_time or not end_time:
        return None

    try:
        start = datetime.datetime.strptime(start_time, "%H:%M:%S")
        end = datetime.datetime.strptime(end_time, "%H:%M:%S")

    except ValueError:
        return None

    if end < start:
        end += datetime.timedelta(days=1)

    return max(0, int(round((end - start).total_seconds())))


def add_webm_duration_metadata(file_path, duration_seconds):
    if duration_seconds is None or duration_seconds <= 0:
        return False

    try:
        with open(file_path, "rb") as file:
            data = bytearray(file.read())

        patched = patch_webm_duration(data, duration_seconds)
        if patched is None:
            return False

        temp_path = f"{file_path}.duration.tmp"
        with open(temp_path, "wb") as file:
            file.write(patched)

        os.replace(temp_path, file_path)
        return True

    except OSError:
        return False

    finally:
        temp_path = f"{file_path}.duration.tmp"
        if os.path.exists(temp_path):
            os.remove(temp_path)


def patch_webm_duration(data, duration_seconds):
    info_pos = data.find(WEBM_INFO_ID)
    if info_pos < 0:
        return None

    size_pos = info_pos + len(WEBM_INFO_ID)
    try:
        info_size, size_len = read_ebml_size(data, size_pos)

    except ValueError:
        return None

    content_pos = size_pos + size_len
    info_end = content_pos + info_size
    if info_end > len(data):
        return None

    duration_payload = struct.pack(">d", float(duration_seconds * 1000))
    duration_element = (
        WEBM_DURATION_ID + encode_ebml_size(len(duration_payload)) + duration_payload
    )

    duration_pos = data.find(WEBM_DURATION_ID, content_pos, info_end)
    if duration_pos >= 0:
        value_pos = duration_pos + len(WEBM_DURATION_ID)
        try:
            value_size, value_size_len = read_ebml_size(data, value_pos)

        except ValueError:
            return None

        if value_size == len(duration_payload):
            data[
                value_pos + value_size_len : value_pos + value_size_len + value_size
            ] = duration_payload
            return data

        return None

    insert_pos = info_end
    if data[insert_pos : insert_pos + len(WEBM_TRACKS_ID)] != WEBM_TRACKS_ID:
        tracks_pos = data.find(WEBM_TRACKS_ID, content_pos)
        if tracks_pos < 0:
            return None
        insert_pos = tracks_pos

    new_info_size = info_size + len(duration_element)
    encoded_info_size = encode_ebml_size(new_info_size, size_len)
    if encoded_info_size is None:
        return None

    data[size_pos : size_pos + size_len] = encoded_info_size
    if not expand_webm_segment_size(data, len(duration_element)):
        return None

    data[insert_pos:insert_pos] = duration_element
    return data


def read_ebml_size(data, pos):
    value, size_len, unknown = read_ebml_size_metadata(data, pos)
    if unknown:
        raise ValueError("Unknown EBML size cannot be patched.")

    return value, size_len


def read_ebml_size_metadata(data, pos):
    if pos >= len(data):
        raise ValueError("EBML size is missing.")

    first_byte = data[pos]
    mask = 0x80
    size_len = 1
    while size_len <= 8 and not (first_byte & mask):
        mask >>= 1
        size_len += 1

    if size_len > 8 or pos + size_len > len(data):
        raise ValueError("Invalid EBML size.")

    raw_value = int.from_bytes(data[pos : pos + size_len], "big")
    value = raw_value & ((1 << (7 * size_len)) - 1)
    unknown = value == (1 << (7 * size_len)) - 1
    return value, size_len, unknown


def encode_ebml_size(value, size_len=1):
    if size_len < 1 or size_len > 8 or value >= (1 << (7 * size_len)) - 1:
        return None

    return ((1 << (7 * size_len)) | value).to_bytes(size_len, "big")


def expand_webm_segment_size(data, added_bytes):
    segment_pos = data.find(WEBM_SEGMENT_ID)
    if segment_pos < 0:
        return True

    size_pos = segment_pos + len(WEBM_SEGMENT_ID)
    try:
        segment_size, size_len, unknown = read_ebml_size_metadata(data, size_pos)

    except ValueError:
        return False

    if unknown:
        return True

    encoded_segment_size = encode_ebml_size(segment_size + added_bytes, size_len)
    if encoded_segment_size is None:
        return False

    data[size_pos : size_pos + size_len] = encoded_segment_size
    return True
