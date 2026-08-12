"""

Shared pytest fixtures.

"""

import pytest
from flask import Flask

from core.extensions import db as _db


@pytest.fixture()
def test_app(tmp_path):
    """
    Yield a bare Flask app bound to the extension's db against a throwaway
    SQLite database, so tests never touch the real database.db.
    """

    db_path = tmp_path / "test.db"
    test_app = Flask("Notes Recorder Test")
    test_app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SECRET_KEY="test-secret",
        TESTING=True,
    )
    _db.init_app(test_app)
    with test_app.app_context():
        _db.create_all()
        yield test_app
        _db.session.remove()
        _db.drop_all()
