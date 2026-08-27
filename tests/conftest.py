"""

Shared pytest fixtures.

"""

import sys

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
