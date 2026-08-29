"""

Tests for query building, filter parsing, and the database migration.

"""

from core.extensions import app
from services.notes_query import (
    init_database,
    parse_notes_filters_from_request,
    _fts_match_query,
    refresh_note_search_index,
    remove_note_from_search_index,
    search_fts_table_exists,
)


def test_parse_notes_filters_from_request():
    with app.test_request_context(
        "/?q=hello&date_from=2026-01-01&tags=1,2,abc&sort=bogus&empty_notes=on"
    ):
        filters = parse_notes_filters_from_request()
        assert filters["search"] == "hello"
        assert filters["date_from"] == "2026-01-01"
        assert filters["tag_ids"] == [1, 2]
        assert filters["sort"] == "date_desc"
        assert filters["empty_notes"] is True


def test_parse_notes_filters_defaults():
    with app.test_request_context("/"):
        filters = parse_notes_filters_from_request()
        assert filters["search"] == ""
        assert filters["tag_ids"] == []
        assert filters["empty_notes"] is False
        assert filters["sort"] == "date_desc"


def test_fts_match_query_builds_safe_phrases():
    assert _fts_match_query("hello world") == '"hello" AND "world"'
    assert _fts_match_query('say "quoted" here') == '"say" AND "quoted" AND "here"'
    assert _fts_match_query("  ") is None
    assert _fts_match_query("") is None


def test_init_database_creates_fts_table(test_app):
    with test_app.app_context():
        init_database()
        assert search_fts_table_exists()


def test_refresh_and_remove_search_index(test_app):
    from core.extensions import db
    from core.models import Note

    with test_app.app_context():
        init_database()
        note = Note(
            date="2026-08-20",
            time="10:00:00",
            start_time="10:00:00",
            end_time="10:05:00",
            subject="Physics",
            unit="General",
            title="Fourier Transform",
            transcription="the transform equation",
            transcription_status="pending",
            key_points_status="pending",
        )
        db.session.add(note)
        db.session.flush()
        refresh_note_search_index(note)
        db.session.commit()

        # FTS should find it.
        from services.notes_query import _search_note_rowids

        assert note.id in _search_note_rowids(_fts_match_query("fourier"))

        # Removing the index row makes it undiscoverable.
        remove_note_from_search_index(note.id)
        db.session.commit()
        assert note.id not in _search_note_rowids(_fts_match_query("fourier"))


def test_init_database_migrates_recording_session(test_app):
    from sqlalchemy import inspect, text

    from core.extensions import db

    with test_app.app_context():
        db.session.execute(text("DROP TABLE recording_session"))
        db.session.execute(
            text(
                "CREATE TABLE recording_session ("
                "id INTEGER PRIMARY KEY, "
                "session_key VARCHAR(32), "
                "status VARCHAR(20) DEFAULT 'active', "
                "extension VARCHAR(10) DEFAULT 'webm', "
                "chunk_count INTEGER DEFAULT 0)"
            )
        )
        db.session.commit()

        init_database()

        columns = {
            column["name"]
            for column in inspect(db.engine).get_columns("recording_session")
        }
        assert {
            "notes_html",
            "bookmarks_json",
            "unit",
            "note_id",
            "segments_json",
            "mime_type",
            "start_time",
            "end_time",
            "subject",
        } <= columns
