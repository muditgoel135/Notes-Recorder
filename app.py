from extensions import app
from text_filters import render_markdown, parse_json
from notes_query import init_database
from transcription import enqueue_existing_transcriptions, enqueue_existing_key_points
from config import TRANSCRIBE_EXISTING_ON_STARTUP

app.jinja_env.filters["markdown"] = render_markdown
app.jinja_env.filters["from_json"] = parse_json

import routes  # noqa: F401  (registers @app.route views as a side effect)

with app.app_context():
    init_database()
    if TRANSCRIBE_EXISTING_ON_STARTUP:
        enqueue_existing_transcriptions()
        enqueue_existing_key_points()


if __name__ == "__main__":
    app.run(debug=False, use_reloader=False)
