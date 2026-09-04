"""

The main app to run the Flask server. It initializes the database, sets up Jinja filters, and registers routes.

"""

from core.extensions import app
from services.csrf import reject_cross_origin_state_changes
from services.text_filters import (
    render_markdown,
    parse_json,
    render_rich_note_html,
    format_display_date,
    format_display_time,
)

from services.notes_query import init_database
from audio.transcription import (
    enqueue_existing_transcriptions,
    enqueue_existing_key_points,
)

from core.config import TRANSCRIBE_EXISTING_ON_STARTUP

app.jinja_env.filters["markdown"] = render_markdown
app.jinja_env.filters["from_json"] = parse_json
app.jinja_env.filters["rich_note"] = render_rich_note_html
app.jinja_env.filters["display_date"] = format_display_date
app.jinja_env.filters["display_time"] = format_display_time

app.before_request(reject_cross_origin_state_changes)

import routes  # noqa: F401  (registers @app.route views as a side effect)


with app.app_context():
    init_database()
    if TRANSCRIBE_EXISTING_ON_STARTUP:
        enqueue_existing_transcriptions()
        enqueue_existing_key_points()


if __name__ == "__main__":
    app.run(debug=False, use_reloader=False)
