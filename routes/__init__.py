"""

This package registers all of the application's routes by importing each
route module, which attaches its view functions to the Flask app.

"""

from . import chat, notes, recordings, taxonomy, bulk
