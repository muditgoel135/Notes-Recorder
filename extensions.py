"""

This module initializes the Flask app and sets up the database connection using SQLAlchemy.

"""

# Import required modules
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Import config to ensure environment variables are loaded before accessing SECRET_KEY
import config  # noqa: F401  (ensures load_dotenv() has run before SECRET_KEY is read)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "default_secret_key")

db = SQLAlchemy(app)
