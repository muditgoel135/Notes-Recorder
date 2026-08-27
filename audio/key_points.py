"""

This module generates titles and key points for notes from transcripts using
Ollama, including speaker-labeled transcript formatting and key points status
persistence.

"""

# Import required modules
import json
import re
import threading
import requests

# Import core extensions and models
from core.extensions import app, db
from core.models import Note

# Import core.config constants
from core.config import (
    KEY_POINTS_PENDING,
    KEY_POINTS_PROCESSING,
    KEY_POINTS_COMPLETED,
    KEY_POINTS_FAILED,
    KEY_POINTS_RETRY_SECONDS,
    KEY_POINTS_MAX_RETRIES,
    OLLAMA_API_KEY,
    OLLAMA_MODEL,
    OLLAMA_CHAT_URL,
)

# Import services and audio helpers
from services.note_images import collect_ollama_note_images
from services.text_filters import rich_note_html_to_text
from services.video_embeds import (
    extract_video_embeds,
    format_video_transcripts,
    process_video_embeds,
)
from audio.audio_processing import is_internet_available

_offline_retry_counts: dict[int, tuple[int | None, int]] = {}

_PUNCTUATION_ONLY_RE: "re.Pattern[str]" = re.compile(r"^[\W_]+$")

# Pattern for a stray backslash that isn't a valid JSON escape (e.g. LaTeX
# style "\(" or "\(\)"). Matched against a JSON candidate.
_STRAY_BACKSLASH_RE: "re.Pattern[str]" = re.compile(r"\\(?![\"\\/bfnrtu])")


def _parse_ollama_json(content: str) -> dict | None:
    """
    Parse a JSON object out of an Ollama chat response.

    Models asked for JSON sometimes wrap it in prose or markdown code fences,
    or emit backslashes that aren't valid JSON escapes (e.g. LaTeX-style
    "\\(" ). This extracts the first balanced {...} object from the content,
    escapes stray backslashes, and retries the parse.

    :param content: Raw model content string.
    :type content: str
    :return: The parsed JSON value, or None if no valid JSON object was found.
    :rtype: object or None
    """

    if not content:
        return None

    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
    if fenced:
        content = fenced.group(1)

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    candidate = content[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        sanitized = _STRAY_BACKSLASH_RE.sub(r"\\\\", candidate)
        try:
            return json.loads(sanitized)
        except json.JSONDecodeError:
            return None


def _join_words_with_spacing(words: list[str]) -> str:
    """
    Join Whisper word tokens into a continuous string.

    Whisper word tokens usually carry their leading whitespace, so tokens can
    be concatenated directly, but some tokens (notably with
    ``condition_on_previous_text`` disabled or in non-English languages) lack
    it. A single space is inserted before tokens that neither start with
    whitespace nor are punctuation-only, so strings like "hello!" and
    "नमस्ते दुनिया" still join correctly.

    :param words: A list of word token strings.
    :type words: list of str
    :return: The joined string.
    :rtype: str
    """

    parts = []
    for index, word in enumerate(words):
        if (
            index > 0
            and not word[:1].isspace()
            and not _PUNCTUATION_ONLY_RE.match(word)
        ):
            parts.append(" ")
        parts.append(word)
    return "".join(parts)


def reset_key_points_offline_retries(note_id: int) -> None:
    """
    Clear the offline-retry counter for a note.

    Called when extraction is re-triggered manually or by a generation bump so
    an earlier retry cap doesn't fail the new attempt immediately.

    :param note_id: ID of the note.
    :type note_id: int
    :return: None
    :rtype: None
    """

    _offline_retry_counts.pop(note_id, None)


def update_key_points_status(
    note_id: int,
    status: str,
    title: str | None = None,
    key_points: str | None = None,
    error: str | None = None,
    generation: int | None = None,
) -> Note | None:
    """
    Update the key points state for a note.

    Retrieves the Note with the given note_id and updates its key points
    status, optional title, key points text, error message, and generation
    number. The generation guard prevents stale background jobs from
    overwriting newer key points.

    :param note_id: ID of the note to update.
    :type note_id: int
    :param status: New key points status value.
    :type status: str
    :param title: Optional new title for the note.
    :type title: str or None
    :param key_points: Optional new key points markdown text.
    :type key_points: str or None
    :param error: Optional key points error message.
    :type error: str or None
    :param generation: Key points generation this update belongs to.
    :type generation: int or None
    :return: Updated Note instance, or None if note_id was not found or the
        generation is stale.
    :rtype: Note or None
    """

    note = db.session.get(Note, note_id)
    if not note:
        return None

    if generation is not None and note.key_points_generation != generation:
        return None

    note.key_points_status = status
    if title is not None:
        note.title = title

    if key_points is not None:
        note.key_points = key_points

    note.key_points_error = error
    db.session.commit()
    return note


def format_transcript_with_speakers(note: "Note") -> str:
    """
    Render transcription_segments as "Speaker N: ..." lines per turn.

    Falls back to the plain transcript when there's no per-word speaker
    data (diarization disabled/unavailable), so the Ollama prompt still
    gets a usable transcript either way.

    :param note: Note instance with transcription_segments and speakers_by_order()
    :return: Formatted transcript string
    """

    words = (
        json.loads(note.transcription_segments) if note.transcription_segments else []
    )

    if not words or all(word.get("spk") is None for word in words):
        return note.transcription or ""

    speakers = note.speakers_by_order()

    def speaker_name(spk):
        """
        Resolve a 0-based speaker index to a display name.

        :param spk: 0-based speaker index.
        :type spk: int or None
        :return: Display name for the speaker.
        :rtype: str
        """
        speaker = speakers.get(spk)
        if speaker:
            return speaker.display_name or speaker.label

        return f"Speaker {spk + 1}" if spk is not None else "Unknown speaker"

    lines = []
    current_spk = object()
    current_words = []
    for word in words:
        spk = word.get("spk")
        if spk != current_spk:
            if current_words:
                lines.append(
                    f"{speaker_name(current_spk)}: {_join_words_with_spacing(current_words).strip()}"
                )

            current_spk = spk
            current_words = []
        current_words.append(word["w"])

    if current_words:
        lines.append(
            f"{speaker_name(current_spk)}: {_join_words_with_spacing(current_words).strip()}"
        )

    return "\n".join(lines)


def is_key_points_generation_current(note_id: int, generation: int) -> bool:
    """
    Check whether the note's key points generation matches the given value.

    :param note_id: ID of the note to check.
    :type note_id: int
    :param generation: Key points generation value to compare against.
    :type generation: int
    :return: True if the note exists and its generation matches, False otherwise.
    :rtype: bool
    """

    note = db.session.get(Note, note_id)
    return bool(note and note.key_points_generation == generation)


def has_speaker_annotations(note: "Note") -> bool:
    """
    Whether the note's transcription segments carry per-word speaker labels.

    When diarization is available, format_transcript_with_speakers() returns
    only the speaker-labeled recording words, so embedded-video transcripts
    must be appended to the model prompt separately.

    :param note: Note instance with transcription_segments.
    :return: True if any word has a "spk" annotation.
    """

    words = (
        json.loads(note.transcription_segments) if note.transcription_segments else []
    )

    return bool(words) and any(word.get("spk") is not None for word in words)


def extract_key_points(
    note_id: int, transcript: str, generation: int | None = None
) -> None:
    """
    Generate a title and key points for a note using Ollama.

    Builds a prompt from the user's notes, the transcript (with speaker labels
    and embedded video transcripts when available), and any extracted images,
    then posts it to Ollama. Waits for an internet connection when needed and
    guards against stale generations. Runs inside the app context.

    :param note_id: ID of the note to update.
    :type note_id: int
    :param transcript: The transcription text to summarize.
    :type transcript: str
    :param generation: Key points generation this run belongs to.
    :type generation: int or None
    :return: None
    :rtype: None
    """

    with app.app_context():
        note = db.session.get(Note, note_id)
        if not note:
            return

        if generation is None:
            generation = note.key_points_generation or 0

        if note.key_points_generation != generation:
            _offline_retry_counts.pop(note_id, None)
            return

        if not transcript and not (
            note.notes_html and extract_video_embeds(note.notes_html)
        ):
            update_key_points_status(
                note_id,
                KEY_POINTS_FAILED,
                error="No transcript to summarize.",
                generation=generation,
            )
            return

        user_notes = rich_note_html_to_text(note.notes_html)

        if not OLLAMA_API_KEY:
            update_key_points_status(
                note_id,
                KEY_POINTS_FAILED,
                error="OLLAMA_API_KEY is not configured.",
                generation=generation,
            )

            return

        if not is_internet_available():
            # Cap the number of consecutive offline retries so a long outage
            # doesn't leave one timer thread per note rescheduling forever.
            retry_entry = _offline_retry_counts.get(note_id)
            retry_count = (
                retry_entry[1] if retry_entry and retry_entry[0] == generation else 0
            )
            if retry_count >= KEY_POINTS_MAX_RETRIES:
                update_key_points_status(
                    note_id,
                    KEY_POINTS_FAILED,
                    error="Ollama is unreachable. Retry key point extraction manually.",
                    generation=generation,
                )
                return

            _offline_retry_counts[note_id] = (generation, retry_count + 1)
            update_key_points_status(
                note_id,
                KEY_POINTS_PENDING,
                error="Waiting for an internet connection to reach Ollama.",
                generation=generation,
            )

            def schedule_retry():
                # Imported lazily to avoid a circular import: transcription
                # imports this module to call extract_key_points.
                from audio.transcription import transcription_executor  # noqa: PLC0415

                transcription_executor.submit(
                    extract_key_points, note_id, transcript, generation
                )

            threading.Timer(KEY_POINTS_RETRY_SECONDS, schedule_retry).start()

            return

        try:
            update_key_points_status(
                note_id, KEY_POINTS_PROCESSING, generation=generation
            )

            # Download embedded YouTube/Vimeo videos, transcribe their audio,
            # and extract keyframes to attach to the model request.
            video_images = []
            video_transcript_text = ""
            try:
                video_images = process_video_embeds(note)
                video_transcript_text = format_video_transcripts(note)

            except Exception:
                video_images = []

            if (
                not (note.transcription or "").strip()
                and not (transcript or "").strip()
            ):
                update_key_points_status(
                    note_id,
                    KEY_POINTS_FAILED,
                    error="No transcript to summarize.",
                    generation=generation,
                )
                return

            prompt_transcript = (
                format_transcript_with_speakers(note) if note else transcript
            )

            context_parts = []
            if user_notes:
                context_parts.append(f"User notes:\n{user_notes}")

            context_parts.append(f"Transcript:\n{prompt_transcript}")
            # When diarization is available the speaker-labeled transcript above
            # omits the merged video text, so append it separately.
            if video_transcript_text and has_speaker_annotations(note):
                context_parts.append(
                    f"Embedded video transcripts:\n{video_transcript_text}"
                )

            message = {
                "role": "user",
                "content": (
                    "You are given a class recording transcript. Lines "
                    "are prefixed with the speaker who said them (e.g. "
                    "'Speaker 1: ...') when that information is "
                    "available; use it to attribute points to the "
                    "right speaker where relevant, but don't let it "
                    "distract from summarizing the content. Embedded "
                    "video transcripts, when present, describe videos "
                    "linked in the user's notes and are equally part of "
                    "the lesson. Respond "
                    "with ONLY a JSON object of the form "
                    '{"title": "short descriptive title (max 8 words)", '
                    '"key_points": "markdown notes summarizing the '
                    "transcript\"}. In key_points, use '## ' headings "
                    "to group related points into sections when the "
                    "transcript covers multiple topics, and '-' for "
                    "bullets under each heading. Nested bullets must be "
                    "indented by exactly 4 spaces per level (required "
                    "for the list to render as nested). Bold with "
                    "**text** where useful. Treat the user's notes as "
                    "important context that may clarify, correct, or "
                    "prioritize parts of the transcript. Images attached "
                    "to this message are keyframes extracted from embedded "
                    "videos or images from the user's notes. "
                    "No preamble or "
                    f"closing remarks.\n\n{chr(10).join(context_parts)}"
                ),
            }
            note_images = collect_ollama_note_images([note])
            for image in video_images:
                if image not in note_images:
                    note_images.append(image)
            if note_images:
                message["images"] = note_images  # type: ignore[assignment]
            response = requests.post(
                OLLAMA_CHAT_URL,
                headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [message],
                    "format": "json",
                    "stream": False,
                },
                timeout=120,
            )

            response.raise_for_status()
            try:
                content = (
                    response.json().get("message", {}).get("content", "") or ""
                ).strip()

            except json.JSONDecodeError:
                raise ValueError(
                    "Ollama returned a non-JSON response. Check that the "
                    "Ollama server is running and reachable."
                )

            if not content:
                raise ValueError("Ollama returned an empty response.")

            parsed = _parse_ollama_json(content)
            if parsed is None:
                raise ValueError(
                    "Ollama did not return a valid JSON object. The model "
                    "may have refused or returned an unexpected format."
                )

            title = (parsed.get("title") or "").strip()
            key_points = (parsed.get("key_points") or "").strip()

            if not key_points:
                raise ValueError("Ollama returned no key points.")

            if generation is not None and not is_key_points_generation_current(
                note_id, generation
            ):
                return

            update_key_points_status(
                note_id,
                KEY_POINTS_COMPLETED,
                title=title[:200] or None,
                key_points=key_points,
                error=None,
                generation=generation,
            )
            _offline_retry_counts.pop(note_id, None)

        except Exception as exc:
            db.session.rollback()
            if generation is not None and not is_key_points_generation_current(
                note_id, generation
            ):
                return
            error_message = str(exc).strip() or exc.__class__.__name__

            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                try:
                    error_message = exc.response.json().get("error") or error_message
                except (ValueError, AttributeError):
                    pass

            update_key_points_status(
                note_id,
                KEY_POINTS_FAILED,
                error=error_message[:1000],
                generation=generation,
            )
