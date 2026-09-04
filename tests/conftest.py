"""
 
Shared pytest fixtures.
 
"""

import sys
from types import SimpleNamespace

import pytest
from flask import Flask

from core.extensions import db as _db


def _register_routes_on(app):
    """
    Import every route module so its view functions are registered on *app*.

    Each route module does ``from core.extensions import app`` and then uses
    ``@app.route``.  We temporarily swap the global reference so the decorators
    attach to the test app instead of the production one.
    """

    import core.extensions as ext

    original_app = ext.app
    ext.app = app

    # Remove any previously cached route modules so they are imported fresh.
    to_remove = [name for name in sys.modules if name.startswith("routes")]
    for name in to_remove:
        del sys.modules[name]

    # Importing routes.__init__ will pull in every route sub-module.
    import routes  # noqa: F401

    ext.app = original_app


@pytest.fixture()
def test_app(tmp_path):
    """
    Yield a Flask app with all production routes registered, bound to a
    throwaway SQLite database so tests never touch the real database.db.
    """

    db_path = tmp_path / "test.db"
    app = Flask("Notes Recorder Test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SECRET_KEY="test-secret",
        TESTING=True,
    )
    _db.init_app(app)
    _register_routes_on(app)

    # Register Jinja2 filters that the templates need.
    from services.text_filters import (
        render_markdown,
        parse_json,
        render_rich_note_html,
        format_display_date,
        format_display_time,
    )

    app.jinja_env.filters["markdown"] = render_markdown
    app.jinja_env.filters["from_json"] = parse_json
    app.jinja_env.filters["rich_note"] = render_rich_note_html
    app.jinja_env.filters["display_date"] = format_display_date
    app.jinja_env.filters["display_time"] = format_display_time

    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def tmp_recordings(tmp_path, monkeypatch):
    """
    Redirect the file directories used by audio.recordings (and the modules
    that import its constants) to throwaway temp dirs, and suppress the
    background transcription executor.

    The module-level constants are imported by reference into several modules,
    so we must patch each module's own copy rather than core.config.

    :yield: A SimpleNamespace with ``recordings``, ``note_images``,
        ``video_cache``, and ``session_chunks`` temp dir paths.
    """

    recordings_dir = tmp_path / "recordings"
    note_images_dir = recordings_dir / "note_images"
    video_cache_dir = recordings_dir / "video_cache"
    session_chunks_dir = recordings_dir / "session_chunks"

    note_images_dir.mkdir(parents=True, exist_ok=True)
    video_cache_dir.mkdir(parents=True, exist_ok=True)
    session_chunks_dir.mkdir(parents=True, exist_ok=True)

    import audio.recordings as recordings_mod
    import audio.transcription as transcription_mod
    import services.note_images as note_images_mod
    import services.video_embeds as video_embeds_mod

    monkeypatch.setattr(recordings_mod, "RECORDINGS_DIR", str(recordings_dir))
    monkeypatch.setattr(recordings_mod, "SESSION_CHUNKS_DIR", str(session_chunks_dir))

    from core import config as config_mod

    monkeypatch.setattr(config_mod, "RECORDINGS_DIR", str(recordings_dir))
    monkeypatch.setattr(config_mod, "NOTE_IMAGES_DIR", str(note_images_dir))
    monkeypatch.setattr(config_mod, "VIDEO_CACHE_DIR", str(video_cache_dir))
    monkeypatch.setattr(note_images_mod, "NOTE_IMAGES_DIR", str(note_images_dir))
    monkeypatch.setattr(video_embeds_mod, "VIDEO_CACHE_DIR", str(video_cache_dir))

    # routes.recordings imports RECORDINGS_DIR/NOTE_IMAGES_DIR by reference at
    # import time; patch its copies so the file-serving routes target temp dirs.
    try:
        import routes.recordings as routes_recordings_mod

        monkeypatch.setattr(
            routes_recordings_mod, "RECORDINGS_DIR", str(recordings_dir)
        )
        monkeypatch.setattr(
            routes_recordings_mod, "NOTE_IMAGES_DIR", str(note_images_dir)
        )
    except ImportError:
        pass

    submissions = []
    real_submit = transcription_mod.transcription_executor.submit

    def _recording_submit(fn, *args, **kwargs):
        submissions.append((fn, args, kwargs))

    monkeypatch.setattr(
        transcription_mod.transcription_executor, "submit", _recording_submit
    )

    try:
        yield SimpleNamespace(
            recordings=str(recordings_dir),
            note_images=str(note_images_dir),
            video_cache=str(video_cache_dir),
            session_chunks=str(session_chunks_dir),
            submissions=submissions,
        )
    finally:
        # Restore the real executor submit so app-level teardown is unaffected.
        monkeypatch.setattr(
            transcription_mod.transcription_executor, "submit", real_submit
        )
