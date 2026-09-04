"""

This module defines the chat routes for the Notes-Recorder application,
including the chat page, chat session management, and the Ollama-backed
conversation endpoint.

"""

# Import required modules
from datetime import datetime, timezone
import requests
from flask import render_template, request, jsonify, Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Import core extensions and models
from core.extensions import app, db
from core.models import ChatMessage, ChatSession, Note

# Import core.config constants
from core.config import (
    DEFAULT_UNIT,
    OLLAMA_API_KEY,
    OLLAMA_CHAT_URL,
    OLLAMA_MODEL,
    TRANSCRIPTION_COMPLETED,
)

# Import services helpers
from services.note_images import collect_ollama_note_images
from services.text_filters import (
    render_markdown,
    rich_note_html_to_text,
    format_display_date,
    format_display_time,
)
from services.notes_query import build_notes_query, parse_notes_filters_from_request
from services.video_embeds import collect_video_embed_images, format_video_transcripts

# Import audio transcription helpers
from audio.transcription import (
    format_transcript_with_speakers,
    has_speaker_annotations,
    is_internet_available,
)


def serialize_chat_note(note: "Note", include_preview: bool = True) -> dict:
    """
    Serialize a Note into a dict for the chat API.

    :param note: The Note instance to serialize.
    :type note: Note
    :param include_preview: Whether to include a truncated preview text.
    :type include_preview: bool
    :return: A dict of the note's serialized attributes.
    :rtype: dict
    """

    preview_source = (
        note.key_points
        or rich_note_html_to_text(note.notes_html)
        or note.transcription
        or ""
    )

    preview = preview_source.strip().replace("\r\n", "\n")
    if len(preview) > 240:
        preview = preview[:240].rstrip() + "..."

    data = {
        "id": note.id,
        "title": note.title,
        "subject": note.subject,
        "unit": note.unit or DEFAULT_UNIT,
        "date": note.date,
        "start_time": note.start_time,
        "end_time": note.end_time,
        "tags": [tag.to_dict() for tag in note.tags],
    }

    if include_preview:
        data["preview"] = preview

    return data


def serialize_chat_message(message: "ChatMessage") -> dict:
    """
    Serialize a ChatMessage into a dict for the chat API.

    Renders assistant messages to markdown HTML.

    :param message: The ChatMessage instance to serialize.
    :type message: ChatMessage
    :return: A dict of the message's serialized attributes.
    :rtype: dict
    """

    data = {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
    }

    if message.role == "assistant":
        data["html"] = str(render_markdown(message.content))

    return data


def serialize_chat_session(
    session: "ChatSession", include_messages: bool = False
) -> dict:
    """
    Serialize a ChatSession into a dict for the chat API.

    :param session: The ChatSession instance to serialize.
    :type session: ChatSession
    :param include_messages: Whether to include the session's messages.
    :type include_messages: bool
    :return: A dict of the session's serialized attributes.
    :rtype: dict
    """

    data = {
        "id": session.id,
        "title": session.title or f"Chat {session.id}",
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "notes": [
            serialize_chat_note(note, include_preview=False) for note in session.notes
        ],
        "message_count": len(session.messages),
    }

    if include_messages:
        data["messages"] = [
            serialize_chat_message(message) for message in session.messages
        ]

    return data


def transcript_context_for_note(note: "Note") -> str:
    """
    Build the transcript context block for a note used in chat prompts.

    Includes the note's metadata, tags, user notes, key points, transcript
    (with speaker labels), and any embedded video transcripts.

    :param note: The Note instance to build context for.
    :type note: Note
    :return: A formatted context string.
    :rtype: str
    """

    transcript = (
        format_transcript_with_speakers(note) if note.speakers else note.transcription
    )

    parts = [
        f"Recording ID: {note.id}",
        f"Subject: {note.subject or 'Untitled'}",
        f"Unit: {note.unit or DEFAULT_UNIT}",
        f"Title: {note.title or 'No title'}",
        f"Date/time: {format_display_date(note.date) or ''} {format_display_time(note.start_time) or ''}-{format_display_time(note.end_time) or ''}".strip(),
    ]

    if note.tags:
        parts.append("Tags: " + ", ".join(tag.name for tag in note.tags))

    user_notes = rich_note_html_to_text(note.notes_html)
    if user_notes:
        parts.append(f"User notes:\n{user_notes}")

    if note.key_points:
        parts.append(f"Key points:\n{note.key_points}")

    parts.append(f"Transcript:\n{transcript or ''}")

    video_transcript_text = format_video_transcripts(note)
    if video_transcript_text and has_speaker_annotations(note):
        parts.append(f"Embedded video transcripts:\n{video_transcript_text}")

    return "\n".join(parts)


def call_ollama_for_chat(
    session: "ChatSession",
) -> tuple[str | None, tuple[str, int] | None]:
    """
    Send a chat request to Ollama with the session's context.

    Builds the system prompt, selected-note context, attached images, and prior
    messages, then posts to Ollama and parses the reply.

    :param session: The ChatSession containing notes and messages.
    :type session: ChatSession
    :return: A tuple of (content, error), where content is the assistant reply
        string and error is None on success, or None and an (message, status)
        tuple on failure.
    :rtype: tuple of (str or None, tuple or None)
    """

    if not OLLAMA_API_KEY:
        return None, ("OLLAMA_API_KEY is not configured.", 503)

    if not is_internet_available():
        return None, ("No internet connection available to reach Ollama.", 503)

    context = "\n\n---\n\n".join(
        transcript_context_for_note(note) for note in session.notes
    )

    note_images = collect_ollama_note_images(session.notes)
    video_images = collect_video_embed_images(session.notes)
    for image in video_images:
        if image not in note_images:
            note_images.append(image)

    messages = [
        {
            "role": "system",
            "content": (
                "You answer questions about the user's selected class recordings. "
                "Use only the supplied recording context and prior chat messages. "
                "If the answer is not supported by the selected recordings, say so. "
                "When useful, cite recordings by subject/title/date rather than by ID."
            ),
        }
    ]

    context_message = {
        "role": "user",
        "content": (
            "Selected recording context follows. Images attached to this message were "
            "embedded in the selected user notes or captured as keyframes from "
            "embedded videos.\n\n"
            f"{context}"
        ),
    }

    if note_images:
        context_message["images"] = note_images

    messages.append(context_message)
    messages.extend(
        {"role": message.role, "content": message.content}
        for message in session.messages
        if message.role in {"user", "assistant"}
    )

    try:
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        with requests.Session() as chat_session:
            chat_session.mount("https://", adapter)
            chat_session.mount("http://", adapter)
            response = chat_session.post(
                OLLAMA_CHAT_URL,
                headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                },
                timeout=120,
            )
            response.raise_for_status()

    except (requests.ConnectionError, requests.Timeout) as exc:
        return None, (str(exc) or "Could not reach Ollama.", 503)

    except requests.HTTPError as exc:
        detail = str(exc)
        try:
            detail = response.json().get("error") or detail

        except (ValueError, AttributeError):
            pass

        return None, (detail, 502)

    except requests.RequestException as exc:
        return None, (str(exc) or "Ollama request failed.", 502)

    try:
        content = (response.json().get("message", {}).get("content", "") or "").strip()

    except (ValueError, AttributeError):
        return None, ("Ollama returned a malformed response.", 502)

    if not content:
        return None, ("Ollama returned an empty response.", 502)

    return content, None


@app.route("/chat")
def chat() -> str:
    """
    Render the chat page.

    :return: The rendered chat template.
    :rtype: str
    """

    return render_template("chat.html")


@app.route("/api/chat/recordings")
def api_chat_recordings() -> Response:
    """
    List recordings available for chat, filtered and with completed transcripts.

    :return: A JSON response with the serialized recordings.
    :rtype: flask.Response
    """

    filters = parse_notes_filters_from_request()
    notes = (
        build_notes_query(**filters)
        .filter(Note.transcription_status == TRANSCRIPTION_COMPLETED)
        .filter(Note.transcription.isnot(None))
        .limit(100)
        .all()
    )

    return jsonify({"recordings": [serialize_chat_note(note) for note in notes]})


@app.route("/api/chat/sessions")
def api_chat_sessions() -> Response:
    """
    List all chat sessions ordered by most recently updated.

    :return: A JSON response with the serialized sessions.
    :rtype: flask.Response
    """

    sessions = ChatSession.query.order_by(ChatSession.updated_at.desc()).all()
    return jsonify(
        {"sessions": [serialize_chat_session(session) for session in sessions]}
    )


@app.route("/api/chat/sessions/<int:session_id>")
def api_chat_session(session_id: int) -> Response:
    """
    Return a single chat session with its messages.

    :param session_id: ID of the chat session.
    :type session_id: int
    :return: A JSON response with the serialized session, or 404 if not found.
    :rtype: flask.Response
    """

    session = ChatSession.query.get_or_404(session_id)
    return jsonify({"session": serialize_chat_session(session, include_messages=True)})


@app.route("/api/chat/sessions", methods=["POST"])
def create_chat_session() -> Response:
    """
    Create a chat session from the requested note ids.

    :return: A JSON response with the created session, or an error.
    :rtype: flask.Response
    """

    data = request.get_json(silent=True) or {}
    note_ids = [
        int(note_id)
        for note_id in (data.get("note_ids") or [])
        if str(note_id).isdigit()
    ]

    if not note_ids:
        return jsonify({"error": "Choose at least one recording to chat about."}), 400

    notes = (
        Note.query.filter(Note.id.in_(note_ids))
        .filter(Note.transcription_status == TRANSCRIPTION_COMPLETED)
        .filter(Note.transcription.isnot(None))
        .all()
    )

    found_ids = {note.id for note in notes}
    if len(found_ids) != len(set(note_ids)):
        return (
            jsonify(
                {"error": "All selected recordings must have completed transcripts."}
            ),
            400,
        )

    first_note = notes[0]
    title = (data.get("title") or "").strip()
    if not title:
        title = first_note.title or first_note.subject or "Recording chat"
        if len(notes) > 1:
            title = f"{title} + {len(notes) - 1} more"

    session = ChatSession(title=title[:200], notes=notes)
    db.session.add(session)
    db.session.commit()
    return jsonify({"session": serialize_chat_session(session, include_messages=True)})


@app.route("/api/chat/sessions/<int:session_id>/messages", methods=["POST"])
def create_chat_message(session_id: int) -> Response:
    """
    Add a user message to a session and get the assistant's reply.

    :param session_id: ID of the chat session.
    :type session_id: int
    :return: A JSON response with the messages, or an error.
    :rtype: flask.Response
    """

    session = ChatSession.query.get_or_404(session_id)
    data = request.get_json(silent=True) or {}
    content = (data.get("message") or "").strip()
    if not content:
        return jsonify({"error": "Enter a message first."}), 400

    transcript_ready_notes = [
        note
        for note in session.notes
        if note.transcription_status == TRANSCRIPTION_COMPLETED and note.transcription
    ]

    if not transcript_ready_notes or len(transcript_ready_notes) != len(session.notes):
        return (
            jsonify(
                {"error": "This chat has recordings without completed transcripts."}
            ),
            400,
        )

    user_message = ChatMessage(session=session, role="user", content=content)
    session.updated_at = datetime.now(timezone.utc)
    db.session.add(user_message)
    db.session.commit()

    answer, error = call_ollama_for_chat(session)
    if error:
        message, status_code = error
        return (
            jsonify(
                {"error": message, "user_message": serialize_chat_message(user_message)}
            ),
            status_code,
        )

    assistant_message = ChatMessage(session=session, role="assistant", content=answer)
    session.updated_at = datetime.now(timezone.utc)
    db.session.add(assistant_message)
    db.session.commit()

    return jsonify(
        {
            "message": serialize_chat_message(assistant_message),
            "user_message": serialize_chat_message(user_message),
            "session": serialize_chat_session(session),
            "model": OLLAMA_MODEL,
        }
    )


@app.route("/api/chat/sessions/<int:session_id>/title", methods=["POST"])
def update_chat_session_title(session_id: int) -> Response:
    """
    Update a chat session's title.

    :param session_id: ID of the chat session.
    :type session_id: int
    :return: A JSON response with the updated session, or an error.
    :rtype: flask.Response
    """

    session = ChatSession.query.get_or_404(session_id)
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "A title is required."}), 400

    session.title = title[:200]
    session.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"session": serialize_chat_session(session, include_messages=True)})
