"""
 
Tests for the chat module: serializers (unit), the Ollama call (mocked), and
the chat routes (integration with a mocked Ollama call).
 
"""

from types import SimpleNamespace

import pytest

from core.config import DEFAULT_UNIT, TRANSCRIPTION_COMPLETED
from core.extensions import db
from core.models import ChatMessage, ChatSession, Note, Speaker
from services.text_filters import render_markdown

# The serializers are pure helpers; call them directly. The route module is
# re-imported by the test_app fixture (conftest swaps ext.app), so route tests
# must patch the *live* module fetched from sys.modules at test time.


def _chat():
    import sys

    return sys.modules["routes.chat"]


def _serialize_chat_note(note, include_preview=True):
    return _chat().serialize_chat_note(note, include_preview=include_preview)

# ---------------------------------------------------------------------------
# DB seed helpers
# ---------------------------------------------------------------------------


def _create_note(db_session, **overrides):
    defaults = dict(
        date="2026-08-20",
        time="10:00:00",
        start_time="10:00:00",
        end_time="10:05:00",
        subject="Physics",
        unit="General",
        title="Physics Notes",
        transcription_status=TRANSCRIPTION_COMPLETED,
        transcription="hello world transcript",
        key_points_status="completed",
        key_points="- a point",
    )
    defaults.update(overrides)
    note = Note(**defaults)
    db_session.add(note)
    from services.notes_query import refresh_note_search_index

    db_session.flush()
    refresh_note_search_index(note)
    db_session.commit()
    return note


def _create_chat_session(db_session, notes=None):
    session = ChatSession(title="Test chat", notes=notes or [])
    db_session.add(session)
    db_session.commit()
    return session


def _add_message(db_session, session, role="user", content="hi"):
    message = ChatMessage(session=session, role=role, content=content)
    db_session.add(message)
    db_session.commit()
    return message


# ---------------------------------------------------------------------------
# Serializer unit tests
# ---------------------------------------------------------------------------


def test_serialize_chat_note_basic(test_app):
    note = _create_note(db.session)
    data = _chat().serialize_chat_note(note)
    assert data["id"] == note.id
    assert data["title"] == "Physics Notes"
    assert data["subject"] == "Physics"
    assert data["unit"] == "General"
    assert "preview" in data
    assert "- a point" in data["preview"]


def test_serialize_chat_note_preview_falls_back_to_transcript(test_app):
    note = _create_note(
        db.session,
        key_points=None,
        notes_html=None,
        transcription="transcript text",
    )
    data = _chat().serialize_chat_note(note)
    assert "transcript text" in data["preview"]


def test_serialize_chat_note_preview_priority(test_app):
    note = _create_note(
        db.session,
        key_points="KEYPOINTS-TEXT",
        notes_html="<p>html text</p>",
        transcription="trans",
    )
    data = _chat().serialize_chat_note(note)
    # Key points take priority for preview.
    assert data["preview"] == "KEYPOINTS-TEXT"


def test_serialize_chat_note_preview_truncation(test_app):
    long_text = "word " * 100
    note = _create_note(db.session, key_points=long_text)
    data = _chat().serialize_chat_note(note)
    assert data["preview"].endswith("...")
    assert len(data["preview"]) <= 244  # 240 + "..."


def test_serialize_chat_note_no_preview(test_app):
    note = _create_note(db.session)
    data = _chat().serialize_chat_note(note, include_preview=False)
    assert "preview" not in data


def test_serialize_chat_note_unit_fallback(test_app):
    note = _create_note(db.session, unit=None)
    data = _chat().serialize_chat_note(note)
    assert data["unit"] == DEFAULT_UNIT


def test_serialize_chat_message_assistant_gets_html(test_app):
    session = _create_chat_session(db.session)
    assistant = _add_message(db.session, session, role="assistant", content="**bold**")
    user = _add_message(db.session, session, role="user", content="plain")

    data = _chat().serialize_chat_message(assistant)
    assert "html" in data
    assert "<strong>bold</strong>" in data["html"]

    user_data = _chat().serialize_chat_message(user)
    assert "html" not in user_data


def test_serialize_chat_session_basic(test_app):
    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])
    _add_message(db.session, session, role="user")
    _add_message(db.session, session, role="assistant")

    data = _chat().serialize_chat_session(session)
    assert data["message_count"] == 2
    assert len(data["notes"]) == 1
    assert "messages" not in data

    with_messages = _chat().serialize_chat_session(session, include_messages=True)
    assert len(with_messages["messages"]) == 2


def test_serialize_chat_session_title_fallback(test_app):
    session = _create_chat_session(db.session, notes=[])
    session.title = None
    db.session.commit()
    session_id = session.id
    data = _chat().serialize_chat_session(session)
    assert data["title"] == f"Chat {session_id}"


def test_transcript_context_for_note_full(test_app):
    note = _create_note(
        db.session,
        subject="Math",
        title="Calc",
        unit="Chapter 2",
        notes_html="<p>user wrote this</p>",
        key_points="- point",
        transcription="some transcript",
    )
    tag = _make_tag(db.session, "important")
    note.tags.append(tag)
    db.session.commit()

    context = _chat().transcript_context_for_note(note)
    assert "Recording ID:" in context
    assert "Subject: Math" in context
    assert "Unit: Chapter 2" in context
    assert "Title: Calc" in context
    assert "important" in context
    assert "user wrote this" in context
    assert "- point" in context
    assert "some transcript" in context


def test_transcript_context_for_note_includes_video_when_speakers(test_app):
    note = _create_note(db.session, transcription_segments='[{"s": 0, "w": "hi", "spk": 0}]')
    from audio.key_points import has_speaker_annotations

    assert has_speaker_annotations(note)
    note.video_transcriptions = (
        '{"vid1": {"title": "Demo", "transcript": "video transcript text"}}'
    )
    db.session.commit()

    context = _chat().transcript_context_for_note(note)
    assert "Embedded video transcripts:" in context
    assert "video transcript text" in context


def test_transcript_context_for_note_omits_video_without_speakers(test_app):
    note = _create_note(
        db.session,
        transcription_segments="[]",
    )
    note.video_transcriptions = (
        '{"vid1": {"title": "Demo", "transcript": "video transcript text"}}'
    )
    db.session.commit()

    context = _chat().transcript_context_for_note(note)
    assert "Embedded video transcripts:" not in context


def _make_tag(db_session, name="important"):
    from core.models import Tag

    tag = Tag(name=name, color="#ff0000")
    db_session.add(tag)
    db_session.commit()
    return tag


# ---------------------------------------------------------------------------
# call_ollama_for_chat unit tests
# ---------------------------------------------------------------------------


class _FakeOllama:
    """Acts as both the requests.Session (context manager) and the response."""

    def __init__(self, response=None, json_exc=None, post_exc=None, http_error=False):
        self.response = response
        self.json_exc = json_exc
        self.post_exc = post_exc
        self.http_error = http_error
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def mount(self, *a, **k):
        pass

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.post_exc:
            raise self.post_exc
        return self

    def raise_for_status(self):
        import requests

        if self.http_error:
            raise requests.HTTPError("bad request")

    def json(self):
        if self.json_exc:
            raise self.json_exc
        return self.response if self.response is not None else {}


def test_call_ollama_no_api_key(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])
    monkeypatch.setattr(_chat(), "OLLAMA_API_KEY", "")
    content, error = _chat().call_ollama_for_chat(session)
    assert content is None
    assert error == ("OLLAMA_API_KEY is not configured.", 503)


def test_call_ollama_no_internet(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])
    monkeypatch.setattr(_chat(), "OLLAMA_API_KEY", "key")
    monkeypatch.setattr(_chat(), "is_internet_available", lambda: False)
    content, error = _chat().call_ollama_for_chat(session)
    assert content is None
    assert error is not None
    assert error[1] == 503


def test_call_ollama_success(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])
    _add_message(db.session, session, role="user", content="q")

    fake = _FakeOllama(response={"message": {"content": "  the answer  "}})
    monkeypatch.setattr(_chat(), "OLLAMA_API_KEY", "key")
    monkeypatch.setattr(_chat(), "is_internet_available", lambda: True)
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    content, error = _chat().call_ollama_for_chat(session)
    assert content == "the answer"
    assert error is None
    # The requests payload includes the user message history.
    assert len(fake.calls) == 1


def test_call_ollama_connection_error(test_app, monkeypatch):
    import requests

    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])

    fake = _FakeOllama(post_exc=requests.ConnectionError("connect failed"))
    monkeypatch.setattr(_chat(), "OLLAMA_API_KEY", "key")
    monkeypatch.setattr(_chat(), "is_internet_available", lambda: True)
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    content, error = _chat().call_ollama_for_chat(session)
    assert content is None
    assert error is not None
    assert error[1] == 503


def test_call_ollama_http_error(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])

    fake = _FakeOllama(
        response={"error": "model overloaded"},
        http_error=True,
    )
    monkeypatch.setattr(_chat(), "OLLAMA_API_KEY", "key")
    monkeypatch.setattr(_chat(), "is_internet_available", lambda: True)
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    content, error = _chat().call_ollama_for_chat(session)
    assert content is None
    assert error == ("model overloaded", 502)


def test_call_ollama_empty_response(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])

    fake = _FakeOllama(response={"message": {}})
    monkeypatch.setattr(_chat(), "OLLAMA_API_KEY", "key")
    monkeypatch.setattr(_chat(), "is_internet_available", lambda: True)
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    content, error = _chat().call_ollama_for_chat(session)
    assert content is None
    assert error is not None
    assert error[0] == "Ollama returned an empty response."


def test_call_ollama_malformed_json(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])

    fake = _FakeOllama(json_exc=ValueError("no json"))
    monkeypatch.setattr(_chat(), "OLLAMA_API_KEY", "key")
    monkeypatch.setattr(_chat(), "is_internet_available", lambda: True)
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    content, error = _chat().call_ollama_for_chat(session)
    assert content is None
    assert error is not None
    assert error[0] == "Ollama returned a malformed response."


# ---------------------------------------------------------------------------
# Chat route integration tests
# ---------------------------------------------------------------------------


def test_api_chat_sessions_empty(test_app):
    response = test_app.test_client().get("/api/chat/sessions")
    assert response.status_code == 200
    assert response.json["sessions"] == []


def test_api_chat_sessions_lists(test_app):
    _create_chat_session(db.session, notes=[])
    response = test_app.test_client().get("/api/chat/sessions")
    assert response.status_code == 200
    assert len(response.json["sessions"]) == 1


def test_api_chat_session_detail(test_app):
    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])
    _add_message(db.session, session, role="user", content="hi")

    response = test_app.test_client().get(f"/api/chat/sessions/{session.id}")
    assert response.status_code == 200
    assert len(response.json["session"]["messages"]) == 1


def test_api_chat_session_detail_404(test_app):
    response = test_app.test_client().get("/api/chat/sessions/9999")
    assert response.status_code == 404


def test_create_chat_session_success(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()
    response = client.post("/api/chat/sessions", json={"note_ids": [note.id]})
    assert response.status_code == 200
    session = ChatSession.query.first()
    assert session is not None
    assert response.json["session"]["id"] == session.id


def test_create_chat_session_empty_ids(test_app):
    response = test_app.test_client().post("/api/chat/sessions", json={"note_ids": []})
    assert response.status_code == 400


def test_create_chat_session_no_completed_transcript(test_app):
    note = _create_note(db.session, transcription_status="pending")
    response = test_app.test_client().post(
        "/api/chat/sessions", json={"note_ids": [note.id]}
    )
    assert response.status_code == 400


def test_create_chat_session_multi_title(test_app):
    n1 = _create_note(db.session, title="Alpha", transcription="t1")
    n2 = _create_note(db.session, title="Beta", transcription="t2")
    response = test_app.test_client().post(
        "/api/chat/sessions", json={"note_ids": [n1.id, n2.id]}
    )
    assert response.status_code == 200
    assert response.json["session"]["title"] == "Alpha + 1 more"


def test_create_chat_message_success(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])
    _add_message(db.session, session, role="user", content="hello")

    monkeypatch.setattr(_chat(), "call_ollama_for_chat", lambda s: ("assistant reply", None))
    client = test_app.test_client()
    response = client.post(
        f"/api/chat/sessions/{session.id}/messages",
        json={"message": "question?"},
    )
    assert response.status_code == 200
    assert response.json["message"]["role"] == "assistant"
    assert response.json["message"]["content"] == "assistant reply"


def test_create_chat_message_empty(test_app):
    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])
    response = test_app.test_client().post(
        f"/api/chat/sessions/{session.id}/messages", json={"message": "  "}
    )
    assert response.status_code == 400


def test_create_chat_message_unready_note(test_app):
    note = _create_note(db.session, transcription_status="pending")
    session = _create_chat_session(db.session, notes=[note])
    response = test_app.test_client().post(
        f"/api/chat/sessions/{session.id}/messages",
        json={"message": "hello"},
    )
    assert response.status_code == 400


def test_create_chat_message_ollama_error(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_chat_session(db.session, notes=[note])

    monkeypatch.setattr(
        _chat(), "call_ollama_for_chat", lambda s: (None, ("boom", 502))
    )
    response = test_app.test_client().post(
        f"/api/chat/sessions/{session.id}/messages",
        json={"message": "hello"},
    )
    assert response.status_code == 502
    assert response.json["error"] == "boom"
    assert "user_message" in response.json


def test_update_chat_session_title_success(test_app):
    session = _create_chat_session(db.session, notes=[])
    response = test_app.test_client().post(
        f"/api/chat/sessions/{session.id}/title", json={"title": "New Title"}
    )
    assert response.status_code == 200
    assert response.json["session"]["title"] == "New Title"


def test_update_chat_session_title_empty(test_app):
    session = _create_chat_session(db.session, notes=[])
    response = test_app.test_client().post(
        f"/api/chat/sessions/{session.id}/title", json={"title": "  "}
    )
    assert response.status_code == 400


def test_update_chat_session_title_404(test_app):
    response = test_app.test_client().post(
        "/api/chat/sessions/9999/title", json={"title": "New"}
    )
    assert response.status_code == 404


def test_api_chat_recordings_completed_only(test_app):
    _create_note(db.session, title="Ready", transcription_status=TRANSCRIPTION_COMPLETED, transcription="data")
    _create_note(db.session, title="Pending", transcription_status="pending", transcription=None)
    response = test_app.test_client().get("/api/chat/recordings")
    assert response.status_code == 200
    titles = [r["title"] for r in response.json["recordings"]]
    assert titles == ["Ready"]


def test_create_chat_session_requires_transcript(test_app):
    pending = _create_note(db.session, title="Pending", transcription_status="pending",
                           transcription=None)
    response = test_app.test_client().post(
        "/api/chat/sessions", json={"note_ids": [pending.id]})
    assert response.status_code == 400
    assert test_app.test_client().post(
        "/api/chat/sessions/9999/messages", json={"message": "hi"}).status_code == 404


def test_chat_end_to_end(test_app, monkeypatch):
    """Full mechanism: discover -> filter -> start -> ask -> reopen -> rename."""
    note = _create_note(
        db.session,
        title="E2E Note",
        transcription="photosynthesis converts light into sugar",
    )
    client = test_app.test_client()

    # 1. Discover: the transcript-ready note is listed.
    found = client.get("/api/chat/recordings")
    assert found.status_code == 200
    assert note.id in [r["id"] for r in found.json["recordings"]]

    # 2. Filter: a matching query keeps it, a junk query drops it.
    matching = client.get("/api/chat/recordings?q=photosynthesis")
    assert note.id in [r["id"] for r in matching.json["recordings"]]
    assert client.get("/api/chat/recordings?q=zzz-no-match").json["recordings"] == []

    # 3. Start: create a session from the selection.
    created = client.post("/api/chat/sessions", json={"note_ids": [note.id]})
    assert created.status_code == 200
    session_id = created.json["session"]["id"]
    assert created.json["session"]["title"] == "E2E Note"

    # 4. Ask: mocked Ollama answers, both messages persist.
    monkeypatch.setattr(
        _chat(), "call_ollama_for_chat", lambda session: ("Light drives it.", None)
    )
    sent = client.post(
        f"/api/chat/sessions/{session_id}/messages", json={"message": "summarize"}
    )
    assert sent.status_code == 200
    assert sent.json["message"]["role"] == "assistant"
    assert sent.json["message"]["content"] == "Light drives it."

    # 5. Reopen: the session shows the full exchange.
    opened = client.get(f"/api/chat/sessions/{session_id}")
    assert opened.status_code == 200
    contents = [(m["role"], m["content"]) for m in opened.json["session"]["messages"]]
    assert ("user", "summarize") in contents
    assert ("assistant", "Light drives it.") in contents

    # 6. Rename: title updates and the sessions list reflects it.
    renamed = client.post(
        f"/api/chat/sessions/{session_id}/title", json={"title": "E2E Renamed"}
    )
    assert renamed.status_code == 200
    assert renamed.json["session"]["title"] == "E2E Renamed"
    listed = client.get("/api/chat/sessions")
    assert any(s["title"] == "E2E Renamed" for s in listed.json["sessions"])


def test_render_markdown_used_by_serializer():
    # Sanity check that render_markdown is importable for assistant html.
    assert callable(render_markdown)


def test_chat_recording_preview_has_no_markdown(test_app):
    _create_note(
        db.session,
        title="Preview Note",
        transcription_status=TRANSCRIPTION_COMPLETED,
        transcription="plain transcript",
        key_points="## Life Expectancy\nDeterminants - **bold** point",
    )
    response = test_app.test_client().get("/api/chat/recordings")
    assert response.status_code == 200
    previews = [r["preview"] for r in response.json["recordings"]]
    assert previews == ["Life Expectancy\nDeterminants - bold point"]
    assert all("##" not in p and "**" not in p for p in previews)
