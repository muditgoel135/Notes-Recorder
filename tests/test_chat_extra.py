"""
Extra tests for chat functionality: SSL verify handling, Ollama error
branches, request payload shape, and route edge cases.
"""

import json

from core.config import TRANSCRIPTION_COMPLETED
from core.extensions import db
from core.models import ChatMessage, ChatSession, Note, Speaker


def _chat():
    import sys

    return sys.modules["routes.chat"]


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


def _create_session(db_session, notes=None, title="Test chat"):
    session = ChatSession(title=title, notes=notes or [])
    db_session.add(session)
    db_session.commit()
    return session


def _add_message(db_session, session, role="user", content="hi"):
    message = ChatMessage(session=session, role=role, content=content)
    db_session.add(message)
    db_session.commit()
    return message


class _FakeOllama:
    """Fake requests.Session + response that records verify flag."""

    def __init__(self, response=None, json_exc=None, post_exc=None, http_error=False):
        self.response = response
        self.json_exc = json_exc
        self.post_exc = post_exc
        self.http_error = http_error
        self.calls = []
        self.verify = "unset"

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


def _patch_ollama_env(monkeypatch, verify_value=True):
    monkeypatch.setattr(_chat(), "OLLAMA_API_KEY", "key")
    monkeypatch.setattr(_chat(), "OLLAMA_VERIFY_SSL", verify_value)
    monkeypatch.setattr(_chat(), "is_internet_available", lambda: True)


# --- SSL verify handling (regression for broken CA bundle fix) ---


def test_call_ollama_sets_verify_false(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_session(db.session, notes=[note])
    _patch_ollama_env(monkeypatch, verify_value=False)
    fake = _FakeOllama(response={"message": {"content": "ok"}})
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    content, error = _chat().call_ollama_for_chat(session)

    assert content == "ok"
    assert error is None
    assert fake.verify is False


def test_call_ollama_sets_verify_true(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_session(db.session, notes=[note])
    _patch_ollama_env(monkeypatch, verify_value=True)
    fake = _FakeOllama(response={"message": {"content": "ok"}})
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    content, error = _chat().call_ollama_for_chat(session)

    assert content == "ok"
    assert fake.verify is True


# --- Ollama error branches not covered by test_chat.py ---


def test_call_ollama_timeout_returns_503(test_app, monkeypatch):
    import requests

    note = _create_note(db.session)
    session = _create_session(db.session, notes=[note])
    _patch_ollama_env(monkeypatch)
    fake = _FakeOllama(post_exc=requests.Timeout("timed out"))
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    content, error = _chat().call_ollama_for_chat(session)

    assert content is None
    assert error[1] == 503


def test_call_ollama_generic_request_exception_returns_502(test_app, monkeypatch):
    import requests

    note = _create_note(db.session)
    session = _create_session(db.session, notes=[note])
    _patch_ollama_env(monkeypatch)
    fake = _FakeOllama(post_exc=requests.TooManyRedirects("redirect loop"))
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    content, error = _chat().call_ollama_for_chat(session)

    assert content is None
    assert error[1] == 502


def test_call_ollama_http_error_with_unparsable_body_falls_back(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_session(db.session, notes=[note])
    _patch_ollama_env(monkeypatch)
    fake = _FakeOllama(json_exc=ValueError("no json"), http_error=True)
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    content, error = _chat().call_ollama_for_chat(session)

    assert content is None
    assert error[1] == 502
    assert error[0] == "bad request"


# --- Request payload shape ---


def test_call_ollama_payload_has_system_prompt_history_and_auth(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_session(db.session, notes=[note])
    _add_message(db.session, session, role="user", content="first q")
    _add_message(db.session, session, role="assistant", content="first a")
    _patch_ollama_env(monkeypatch)
    fake = _FakeOllama(response={"message": {"content": "ok"}})
    monkeypatch.setattr(_chat(), "OLLAMA_MODEL", "test-model")
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    content, error = _chat().call_ollama_for_chat(session)

    assert error is None
    assert len(fake.calls) == 1
    url, kwargs = fake.calls[0]
    assert url == _chat().OLLAMA_CHAT_URL
    assert kwargs["headers"] == {"Authorization": "Bearer key"}
    payload = kwargs["json"]
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    messages = payload["messages"]
    assert messages[0]["role"] == "system"
    assert "selected class recordings" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "hello world transcript" in messages[1]["content"]
    history = [(m["role"], m["content"]) for m in messages[2:]]
    assert ("user", "first q") in history
    assert ("assistant", "first a") in history


def test_call_ollama_filters_non_user_assistant_roles(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_session(db.session, notes=[note])
    _add_message(db.session, session, role="user", content="keep me")
    _add_message(db.session, session, role="system", content="drop me")
    _patch_ollama_env(monkeypatch)
    fake = _FakeOllama(response={"message": {"content": "ok"}})
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    _chat().call_ollama_for_chat(session)

    messages = fake.calls[0][1]["json"]["messages"]
    forwarded = [(m["role"], m["content"]) for m in messages[2:]]
    assert ("user", "keep me") in forwarded
    assert not any(role == "system" and c == "drop me" for role, c in forwarded)


def test_call_ollama_attaches_deduped_images(test_app, monkeypatch):
    note = _create_note(db.session)
    session = _create_session(db.session, notes=[note])
    _patch_ollama_env(monkeypatch)
    monkeypatch.setattr(
        _chat(), "collect_ollama_note_images", lambda notes: ["img1"]
    )
    monkeypatch.setattr(
        _chat(), "collect_video_embed_images", lambda notes: ["img2", "img1"]
    )
    fake = _FakeOllama(response={"message": {"content": "ok"}})
    monkeypatch.setattr(_chat().requests, "Session", lambda: fake)

    _chat().call_ollama_for_chat(session)

    context_msg = fake.calls[0][1]["json"]["messages"][1]
    assert context_msg["images"] == ["img1", "img2"]


# --- Route edge cases ---


def test_chat_page_renders(test_app):
    response = test_app.test_client().get("/chat")
    assert response.status_code == 200
    assert b"Chat with recordings" in response.data


def test_create_chat_message_persists_user_message_on_ollama_error(
    test_app, monkeypatch
):
    note = _create_note(db.session)
    session = _create_session(db.session, notes=[note])
    monkeypatch.setattr(
        _chat(), "call_ollama_for_chat", lambda s: (None, ("boom", 502))
    )

    response = test_app.test_client().post(
        f"/api/chat/sessions/{session.id}/messages", json={"message": "hello"}
    )

    assert response.status_code == 502
    stored = ChatMessage.query.filter_by(chat_session_id=session.id).all()
    assert [m.role for m in stored] == ["user"]
    assert stored[0].content == "hello"


def test_create_chat_session_custom_title_and_truncation(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()

    custom = client.post(
        "/api/chat/sessions", json={"note_ids": [note.id], "title": "My title"}
    )
    assert custom.status_code == 200
    assert custom.json["session"]["title"] == "My title"

    long_title = "x" * 300
    truncated = client.post(
        "/api/chat/sessions", json={"note_ids": [note.id], "title": long_title}
    )
    assert truncated.status_code == 200
    assert len(truncated.json["session"]["title"]) == 200


def test_create_chat_session_ignores_non_digit_ids(test_app):
    note = _create_note(db.session)
    client = test_app.test_client()

    mixed = client.post(
        "/api/chat/sessions", json={"note_ids": ["abc", str(note.id)]}
    )
    assert mixed.status_code == 200

    only_bad = client.post("/api/chat/sessions", json={"note_ids": ["abc"]})
    assert only_bad.status_code == 400


def test_update_chat_title_truncates_to_200(test_app):
    session = _create_session(db.session)
    response = test_app.test_client().post(
        f"/api/chat/sessions/{session.id}/title", json={"title": "y" * 300}
    )
    assert response.status_code == 200
    assert len(response.json["session"]["title"]) == 200


def test_transcript_context_uses_speaker_labels(test_app):
    note = _create_note(
        db.session,
        transcription="plain fallback",
        transcription_segments=json.dumps(
            [
                {"s": 0.0, "w": "hello", "spk": 0},
                {"s": 1.0, "w": "world", "spk": 1},
            ]
        ),
    )
    db.session.add(
        Speaker(note_id=note.id, order_index=0, label="Speaker 1", color="#4c78a8")
    )
    db.session.add(
        Speaker(note_id=note.id, order_index=1, label="Speaker 2", color="#f58518")
    )
    db.session.commit()

    context = _chat().transcript_context_for_note(note)

    assert "Speaker 1: hello" in context
    assert "Speaker 2: world" in context
