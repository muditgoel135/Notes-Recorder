"""

Query building functions for retrieving notes based on various filters.

"""

# Import required modules
from flask import request
from sqlalchemy import Column, func, inspect, text, Case

# Import the database instance, models, and config constants
from core.extensions import db
from core.models import Note, Tag, Subject, get_tag_descendant_ids
from services.text_filters import rich_note_html_to_text
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


# Name of the FTS5 virtual table used for full-text search over notes.
SEARCH_FTS_TABLE: str = "notes_fts"
_HAS_FTS5: bool | None = None


def fts5_available() -> bool:
    """
    Whether the active SQLite build ships the FTS5 module.

    Result is cached after the first probe (using the pragma_compile_options
    table of the database's SQLite engine). Used to decide whether the full
    text search index can be created and used.

    :return: True when FTS5 is available, False otherwise.
    :rtype: bool
    """

    global _HAS_FTS5
    if _HAS_FTS5 is None:
        try:
            row = db.session.execute(
                text(
                    "SELECT count(*) FROM pragma_compile_options "
                    "WHERE compile_options = 'ENABLE_FTS5'"
                )
            ).fetchone()
            _HAS_FTS5 = bool(row and row[0])
        except Exception:
            _HAS_FTS5 = False
    return _HAS_FTS5


def search_fts_table_exists() -> bool:
    """
    Whether the notes FTS table has been created in this database.

    :return: True when the FTS table exists, False otherwise.
    :rtype: bool
    """

    if not fts5_available():
        return False
    try:
        rows = db.session.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = :name"
            ),
            {"name": SEARCH_FTS_TABLE},
        ).fetchall()
        return bool(rows)
    except Exception:
        return False


def _create_search_fts_table() -> None:
    """
    Create the notes FTS5 virtual table if FTS5 is available.

    The table is standalone (the original content is stored in the index), so
    its rows are maintained explicitly by ``refresh_note_search_index``.

    :return: None
    :rtype: None
    """

    if not fts5_available():
        return
    db.session.execute(
        text(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {SEARCH_FTS_TABLE} "
            "USING fts5("
            "title, "
            "subject, "
            "unit, "
            "transcription, "
            "key_points, "
            "notes_text, "
            "tokenize = 'porter unicode61'"
            ")"
        )
    )


def _fts_match_query(search: str) -> str | None:
    """
    Build a safe FTS5 MATCH phrase from the user's raw search text.

    Each whitespace-delimited token is wrapped in double quotes (a phrase) and
    ANDed together, so FTS operators like quotes, asterisks, and parentheses in
    the user input are treated as literal text rather than query syntax.

    :param search: The raw search string.
    :type search: str
    :return: A safe MATCH expression, or None when there is nothing to match.
    :rtype: str or None
    """

    tokens = []
    for token in search.split():
        token = token.strip().strip('"')
        if token:
            tokens.append(f'"{token.replace(chr(34), chr(34) + chr(34))}"')
    return " AND ".join(tokens) if tokens else None


def _search_note_rowids(match_query: str) -> list[int]:
    """
    Return note ids matching an FTS5 MATCH expression, ordered by relevance.

    :param match_query: A validated FTS5 MATCH expression.
    :type match_query: str
    :return: A list of matching note ids.
    :rtype: list of int
    """

    rows = db.session.execute(
        text(
            f"SELECT rowid FROM {SEARCH_FTS_TABLE} "
            f"WHERE {SEARCH_FTS_TABLE} MATCH :q "
            f"ORDER BY bm25({SEARCH_FTS_TABLE})"
        ),
        {"q": match_query},
    ).fetchall()
    return [row[0] for row in rows]


def refresh_note_search_index(note: "Note | None") -> None:
    """
    Rebuild the FTS5 row for a note from its current searchable fields.

    Deletes and reinserts the note's row so the index stays in sync with the
    note's title, subject, unit, transcription, key points, and rich-note text.
    Runs within the caller's transaction (it does not commit), so the updated
    model fields and the refreshed index row are persisted atomically by the
    caller's commit.

    :param note: The Note instance to reindex.
    :type note: Note or None
    :return: None
    :rtype: None
    """

    if not note or note.id is None:
        return
    if not search_fts_table_exists():
        return

    try:
        db.session.execute(
            text(f"DELETE FROM {SEARCH_FTS_TABLE} WHERE rowid = :id"),
            {"id": note.id},
        )
        db.session.execute(
            text(
                f"INSERT INTO {SEARCH_FTS_TABLE} "
                "(rowid, title, subject, unit, transcription, key_points, notes_text) "
                "VALUES (:id, :title, :subject, :unit, :transcription, :key_points, :notes_text)"
            ),
            {
                "id": note.id,
                "title": note.title or "",
                "subject": note.subject or "",
                "unit": note.unit or "",
                "transcription": note.transcription or "",
                "key_points": note.key_points or "",
                "notes_text": rich_note_html_to_text(note.notes_html),
            },
        )
    except Exception:
        db.session.rollback()


def remove_note_from_search_index(note_id: int) -> None:
    """
    Remove a note's row from the FTS5 search index.

    Runs within the caller's transaction (it does not commit), so the removal
    is persisted atomically with the caller's commit. Safe to call for notes
    that are not in the index.

    :param note_id: ID of the note to remove from the index.
    :type note_id: int
    :return: None
    :rtype: None
    """

    if not search_fts_table_exists():
        return

    try:
        db.session.execute(
            text(f"DELETE FROM {SEARCH_FTS_TABLE} WHERE rowid = :id"),
            {"id": note_id},
        )
    except Exception:
        db.session.rollback()


def _status_rank_expression(column: "Column") -> "Case":
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


def _register_sqlite_pragmas() -> None:
    """
    Configure SQLite for safe concurrent access from the request threads and
    the background transcription worker thread.

    ``init_database`` runs inside an app context so ``db.engine`` is available
    here. The listener runs once per new DB-API connection (including the worker
    thread's connections) and:
      - switches the database to WAL journal mode, which lets a single writer
        proceed alongside concurrent readers;
      - sets a busy timeout so a writer waits for a momentarily-held lock instead
        of immediately raising ``sqlite3.OperationalError: database is locked``;
      - relaxes the synchronous level, which is safe in WAL mode and reduces the
        write latency that made lock contention worse.

    Without this, a recording being transcribed by the worker while a request
    commits can raise ``database is locked`` and surface as intermittent 500s.
    """

    global _SQLITE_PRAGMA_REGISTERED

    from sqlalchemy import event

    if _SQLITE_PRAGMA_REGISTERED:
        return

    @event.listens_for(db.engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    _SQLITE_PRAGMA_REGISTERED = True


_SQLITE_PRAGMA_REGISTERED = False


def init_database() -> None:
    """
    Initializes the database by creating all tables, seeding default subjects,
    and performing necessary schema migrations for the Note and recording_session tables.
    """

    _register_sqlite_pragmas()
    db.create_all()

    if not Subject.query.first():
        db.session.add_all(Subject(name=name) for name in DEFAULT_SUBJECTS)
        db.session.commit()

    inspector = inspect(db.engine)

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
        "bookmarks_json": "TEXT",
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
        required_session_columns = {
            "session_key": "VARCHAR(32) NOT NULL DEFAULT ''",
            "subject": "VARCHAR(100)",
            "unit": "VARCHAR(100)",
            "start_time": "VARCHAR(8) NOT NULL DEFAULT ''",
            "end_time": "VARCHAR(8)",
            "status": "VARCHAR(20) NOT NULL DEFAULT 'active'",
            "mime_type": "VARCHAR(100)",
            "extension": "VARCHAR(10) NOT NULL DEFAULT 'webm'",
            "chunk_count": "INTEGER NOT NULL DEFAULT 0",
            "segments_json": "TEXT",
            "notes_html": "TEXT",
            "bookmarks_json": "TEXT",
            "note_id": "INTEGER",
        }
        with db.engine.begin() as connection:
            for column_name, column_definition in required_session_columns.items():
                if column_name not in session_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE recording_session ADD COLUMN {column_name} {column_definition}"
                        )
                    )
            connection.execute(
                text(
                    "UPDATE recording_session SET unit = :default_unit "
                    "WHERE unit IS NULL OR unit = ''"
                ),
                {"default_unit": DEFAULT_UNIT},
            )

    _create_search_fts_table()
    _backfill_search_index()


def _backfill_search_index() -> None:
    """
    Rebuild the entire notes FTS index from the current notes table.

    Deletes and recreates the index rows so startup stays consistent even if a
    prior run left the table partially out of sync. Safe to run repeatedly.
    Called during ``init_database``.

    :return: None
    :rtype: None
    """

    if not search_fts_table_exists():
        return

    try:
        db.session.execute(text(f"DELETE FROM {SEARCH_FTS_TABLE}"))
        for note in Note.query.all():
            refresh_note_search_index(note)
        db.session.commit()
    except Exception:
        db.session.rollback()


def build_notes_query(
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
    tag_ids: list[int] | None = None,
    subjects: list[str] | None = None,
    units: list[tuple[str, str]] | None = None,
    transcription_statuses: list[str] | None = None,
    key_points_statuses: list[str] | None = None,
    empty_notes: bool = False,
    sort: str | None = None,
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
        match_query = _fts_match_query(search) if search_fts_table_exists() else None
        if match_query:
            try:
                row_ids = _search_note_rowids(match_query)
                query = query.filter(Note.id.in_(row_ids))
                search_used_fts = True
            except Exception:
                search_used_fts = False
        else:
            search_used_fts = False

        if not search_used_fts:
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
        *order_rules.get(
            sort, order_rules[DEFAULT_SORT]
        ),  # pyright: ignore[reportCallIssue], ignore[reportArgumentType]
    )


def parse_notes_filters_from_request() -> dict:
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


def check_has_active_transcription() -> bool:
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
