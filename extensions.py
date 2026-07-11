import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

import config  # noqa: F401  (ensures load_dotenv() has run before SECRET_KEY is read)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "default_secret_key")

db = SQLAlchemy(app)
