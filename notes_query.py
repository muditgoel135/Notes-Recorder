from flask import request
from sqlalchemy import inspect, text

from extensions import db
from models import Note, Tag, Subject, get_tag_descendant_ids
from config import (
    TRANSCRIPTION_PENDING,
    TRANSCRIPTION_PROCESSING,
    KEY_POINTS_PENDING,
    KEY_POINTS_PROCESSING,
)

DEFAULT_SUBJECTS = [
    "Math",
    "Physics",
    "Chemistry",
    "Biology",
    "English",
    "Hindi",
    "Individuals and Societies",
]


def init_database():
    db.create_all()

    if not Subject.query.first():
        db.session.add_all(Subject(name=name) for name in DEFAULT_SUBJECTS)
        db.session.commit()

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
        "transcription_progress": "INTEGER DEFAULT 0",
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


def build_notes_query(
    search=None,
    date_from=None,
    date_to=None,
    time_from=None,
    time_to=None,
    tag_ids=None,
    subjects=None,
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

    if tag_ids:
        expanded_ids = get_tag_descendant_ids(tag_ids)
        query = query.filter(Note.tags.any(Tag.id.in_(expanded_ids)))

    if subjects:
        query = query.filter(Note.subject.in_(subjects))

    return query.order_by(Note.id.desc())


def parse_notes_filters_from_request():
    tag_ids = [
        int(tag_id)
        for tag_id in (request.args.get("tags") or "").split(",")
        if tag_id.strip().isdigit()
    ]
    subjects = [
        subject
        for subject in (request.args.get("subjects") or "").split(",")
        if subject.strip()
    ]
    return {
        "search": (request.args.get("q") or "").strip(),
        "date_from": (request.args.get("date_from") or "").strip() or None,
        "date_to": (request.args.get("date_to") or "").strip() or None,
        "time_from": (request.args.get("time_from") or "").strip() or None,
        "time_to": (request.args.get("time_to") or "").strip() or None,
        "tag_ids": tag_ids,
        "subjects": subjects,
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
