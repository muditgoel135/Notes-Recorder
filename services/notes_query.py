"""

Query building functions for retrieving notes based on various filters.

"""

# Import required modules
from flask import request
from sqlalchemy import func, inspect, text

# Import the database instance, models, and config constants
from core.extensions import db
from core.models import Note, Tag, Subject, get_tag_descendant_ids
from core.config import (
    TRANSCRIPTION_PENDING,
    TRANSCRIPTION_PROCESSING,
    TRANSCRIPTION_COMPLETED,
    TRANSCRIPTION_FAILED,
    KEY_POINTS_PENDING,
    KEY_POINTS_PROCESSING,
    KEY_POINTS_COMPLETED,
    KEY_POINTS_FAILED,
    DEFAULT_UNIT,
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

DEFAULT_SORT = "date_desc"

VALID_SORTS = {
    "date_desc",
    "date_asc",
    "title_asc",
    "title_desc",
    "subject_asc",
    "subject_desc",
    "transcription_status_asc",
    "transcription_status_desc",
    "key_points_status_asc",
    "key_points_status_desc",
}

VALID_TRANSCRIPTION_STATUS_FILTERS = {
    TRANSCRIPTION_PENDING,
    TRANSCRIPTION_PROCESSING,
    TRANSCRIPTION_COMPLETED,
    TRANSCRIPTION_FAILED,
}

VALID_KEY_POINTS_STATUS_FILTERS = {
    KEY_POINTS_PENDING,
    KEY_POINTS_PROCESSING,
    KEY_POINTS_COMPLETED,
    KEY_POINTS_FAILED,
}

EMPTY_NOTES_TRUE_VALUES = {"1", "true", "yes", "on"}

STATUS_RANK = {
    "pending": 0,
    "processing": 1,
    "completed": 2,
    "failed": 3,
}


def _status_rank_expression(column):
    """
    Build a SQL CASE expression ranking a note status column.

    Statuses are ranked pending < processing < completed < failed so that
    sorting by status groups notes in a meaningful order.

    :param column: The status column to rank.
    :type column: sqlalchemy.sql.elements.ColumnClause
    :return: A SQL expression assigning each status an integer rank.
    :rtype: sqlalchemy.sql.elements.Case
    """

    return db.case(STATUS_RANK, value=column, else_=99)


def init_database():
    """
    Initializes the database by creating all tables, seeding default subjects,
    and performing necessary schema migrations for the Note and recording_session tables.
    """

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
        "unit": "VARCHAR(100)",
        "recording_path": "VARCHAR(200)",
        "notes_html": "TEXT",
        "transcription": "TEXT",
        "transcription_segments": "TEXT",
        "transcription_status": f"VARCHAR(20) NOT NULL DEFAULT '{TRANSCRIPTION_PENDING}'",
        "transcription_progress": "INTEGER DEFAULT 0",
        "transcription_stage": "VARCHAR(20)",
        "transcription_error": "TEXT",
        "video_transcriptions": "TEXT",
        "title": "VARCHAR(200)",
        "key_points": "TEXT",
        "key_points_status": f"VARCHAR(20) NOT NULL DEFAULT '{KEY_POINTS_PENDING}'",
        "key_points_generation": "INTEGER NOT NULL DEFAULT 0",
        "key_points_error": "TEXT",
        "pinned": "BOOLEAN NOT NULL DEFAULT 0",
    }

    with db.engine.begin() as connection:
        for column_name, column_definition in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE note ADD COLUMN {column_name} {column_definition}"
                    )
                )

        connection.execute(
            text(
                "UPDATE note SET unit = :default_unit "
                "WHERE unit IS NULL OR unit = ''"
            ),
            {"default_unit": DEFAULT_UNIT},
        )

    if "recording_session" in inspector.get_table_names():
        session_columns = {
            column["name"] for column in inspector.get_columns("recording_session")
        }
        with db.engine.begin() as connection:
            if "notes_html" not in session_columns:
                connection.execute(
                    text("ALTER TABLE recording_session ADD COLUMN notes_html TEXT")
                )
            if "unit" not in session_columns:
                connection.execute(
                    text("ALTER TABLE recording_session ADD COLUMN unit VARCHAR(100)")
                )
            connection.execute(
                text(
                    "UPDATE recording_session SET unit = :default_unit "
                    "WHERE unit IS NULL OR unit = ''"
                ),
                {"default_unit": DEFAULT_UNIT},
            )


def build_notes_query(
    search=None,
    date_from=None,
    date_to=None,
    time_from=None,
    time_to=None,
    tag_ids=None,
    subjects=None,
    units=None,
    transcription_statuses=None,
    key_points_statuses=None,
    empty_notes=False,
    sort=None,
):
    """
    Builds a SQLAlchemy query to retrieve notes based on search terms and filters.

    :param search: Search term for title, transcription, subject, etc.
    :type search: str or None
    :param date_from: Start date filter (inclusive).
    :type date_from: str or None
    :param date_to: End date filter (inclusive).
    :type date_to: str or None
    :param time_from: Start time filter (inclusive).
    :type time_from: str or None
    :param time_to: End time filter (inclusive).
    :type time_to: str or None
    :param tag_ids: List of tag IDs to filter by.
    :type tag_ids: list of int or None
    :param subjects: List of subjects to filter by.
    :type subjects: list of str or None
    :param units: List of (subject, unit) pairs to filter by.
    :type units: list of tuple of (str, str) or None
    :param transcription_statuses: List of transcription statuses to include.
    :type transcription_statuses: list of str or None
    :param key_points_statuses: List of key points statuses to include.
    :type key_points_statuses: list of str or None
    :param empty_notes: Only include notes without saved user notes.
    :type empty_notes: bool
    :param sort: Sort key, e.g. "date_desc", "title_asc", or "subject_desc".
    :type sort: str or None

    :return: A SQLAlchemy query object ordered by the requested sort.
    :rtype: sqlalchemy.orm.query.Query
    """

    query = Note.query

    if search:
        like_pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                Note.title.ilike(like_pattern),
                Note.transcription.ilike(like_pattern),
                Note.subject.ilike(like_pattern),
                Note.unit.ilike(like_pattern),
                Note.key_points.ilike(like_pattern),
                Note.notes_html.ilike(like_pattern),
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

    subject_conditions = []
    if subjects:
        subject_conditions.append(Note.subject.in_(subjects))

    if units:
        subject_conditions.extend(
            db.and_(Note.subject == subject_name, Note.unit == unit_name)
            for subject_name, unit_name in units
        )

    if subject_conditions:
        query = query.filter(db.or_(*subject_conditions))

    if transcription_statuses:
        query = query.filter(Note.transcription_status.in_(transcription_statuses))

    if key_points_statuses:
        query = query.filter(Note.key_points_status.in_(key_points_statuses))

    if empty_notes:
        query = query.filter(
            db.or_(
                Note.notes_html.is_(None),
                func.trim(func.coalesce(Note.notes_html, "")) == "",
            )
        )

    order_rules = {
        "date_desc": (Note.date.desc(), Note.start_time.desc(), Note.id.desc()),
        "date_asc": (Note.date.asc(), Note.start_time.asc(), Note.id.asc()),
        "title_asc": (
            func.coalesce(Note.title, "").asc(),
            Note.id.desc(),
        ),
        "title_desc": (
            func.coalesce(Note.title, "").desc(),
            Note.id.asc(),
        ),
        "subject_asc": (
            func.coalesce(Note.subject, "").asc(),
            Note.id.desc(),
        ),
        "subject_desc": (
            func.coalesce(Note.subject, "").desc(),
            Note.id.asc(),
        ),
        "transcription_status_asc": (
            _status_rank_expression(Note.transcription_status).asc(),
            Note.id.desc(),
        ),
        "transcription_status_desc": (
            _status_rank_expression(Note.transcription_status).desc(),
            Note.id.asc(),
        ),
        "key_points_status_asc": (
            _status_rank_expression(Note.key_points_status).asc(),
            Note.id.desc(),
        ),
        "key_points_status_desc": (
            _status_rank_expression(Note.key_points_status).desc(),
            Note.id.asc(),
        ),
    }

    return query.order_by(
        Note.pinned.desc(),
        *order_rules.get(sort, order_rules[DEFAULT_SORT]),
    )


def parse_notes_filters_from_request():
    """
    Parses notes filtering criteria from the current Flask request arguments.

    :return: A dictionary containing filtered search, date, time, tag, subject,
        status, and empty-notes criteria.
    :rtype: dict
    """

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

    units = []
    for entry in (request.args.get("units") or "").split(","):
        entry = entry.strip()
        if "::" in entry:
            subject_name, unit_name = entry.split("::", 1)
            if subject_name.strip() and unit_name.strip():
                units.append((subject_name.strip(), unit_name.strip()))

    transcription_statuses = [
        status
        for status in (request.args.get("transcription_statuses") or "").split(",")
        if status.strip() in VALID_TRANSCRIPTION_STATUS_FILTERS
    ]

    key_points_statuses = [
        status
        for status in (request.args.get("key_points_statuses") or "").split(",")
        if status.strip() in VALID_KEY_POINTS_STATUS_FILTERS
    ]

    empty_notes = (request.args.get("empty_notes") or "").strip().lower()
    empty_notes = empty_notes in EMPTY_NOTES_TRUE_VALUES

    sort = (request.args.get("sort") or "").strip() or DEFAULT_SORT
    if sort not in VALID_SORTS:
        sort = DEFAULT_SORT

    return {
        "search": (request.args.get("q") or "").strip(),
        "date_from": (request.args.get("date_from") or "").strip() or None,
        "date_to": (request.args.get("date_to") or "").strip() or None,
        "time_from": (request.args.get("time_from") or "").strip() or None,
        "time_to": (request.args.get("time_to") or "").strip() or None,
        "tag_ids": tag_ids,
        "subjects": subjects,
        "units": units,
        "transcription_statuses": transcription_statuses,
        "key_points_statuses": key_points_statuses,
        "empty_notes": empty_notes,
        "sort": sort,
    }


def check_has_active_transcription():
    """
    Checks if there are any notes currently awaiting or undergoing transcription or key point generation.

    :return: True if at least one note is pending or processing, False otherwise.
    :rtype: bool
    """

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
