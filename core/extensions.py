"""

This module initializes the Flask app and sets up the database connection using SQLAlchemy.

"""

# Import required modules
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Import core.config so environment variables are loaded before SECRET_KEY is read
from core.config import SECRET_KEY, BASE_DIR
import os

app = Flask("Notes Recorder")
app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'database.db')}"
)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db = SQLAlchemy(app)
