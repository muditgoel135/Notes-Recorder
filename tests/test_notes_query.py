"""

Tests for query building, filter parsing, and the database migration.

"""

from core.extensions import app
from services.notes_query import init_database, parse_notes_filters_from_request


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
