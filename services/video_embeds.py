"""

This module handles embedded YouTube/Vimeo videos found in rich notes. It
downloads each embed with yt-dlp, extracts the audio track for Whisper
transcription, extracts keyframes with ffmpeg, and merges the transcripts into
the note so key-points extraction and chat can make use of the video content.

"""

# Import required modules
import base64
import glob
import json
import os
import subprocess
from html.parser import HTMLParser
from urllib.parse import urlparse

# Import third-party libraries
import yt_dlp

# Import core.config, core.extensions, and text filter helpers
from core.config import (
    HINDI_INITIAL_PROMPT,
    HINDI_SUBJECT,
    VIDEO_CACHE_DIR,
    VIDEO_KEYFRAME_COUNT,
)
from core.extensions import db
from services.text_filters import sanitize_rich_note_html


class _VideoEmbedParser(HTMLParser):
    """HTML parser that collects iframe embeds and their attributes."""

    def __init__(self) -> None:
        """
        Initialize the parser with an empty embeds list.

        :return: None
        :rtype: None
        """

        super().__init__()
        self.embeds: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """
        Collect the src and title of each iframe embed.

        :param tag: The HTML tag name.
        :type tag: str
        :param attrs: The tag's attributes.
        :type attrs: list of tuple
        :return: None
        :rtype: None
        """
        if tag != "iframe":
            return

        attrs_by_name = dict(attrs)
        src = (attrs_by_name.get("src") or "").strip()
        if src:
            self.embeds.append(
                {
                    "src": src,
                    "title": (attrs_by_name.get("title") or "").strip(),
                }
            )


def extract_video_embeds(html: str | None) -> list[dict]:
    """
    Extract YouTube/Vimeo embeds from sanitized rich note HTML.

    :param html: The HTML content of the rich note.
    :return: A list of dicts with "host", "video_id", "url", and "title".
    """

    parser = _VideoEmbedParser()
    parser.feed(sanitize_rich_note_html(html) or "")

    embeds = []
    for item in parser.embeds:
        host, video_id = _embed_id_from_src(item["src"])
        if not video_id:
            continue

        embeds.append(
            {
                "host": host,
                "video_id": video_id,
                "url": _download_url_for(host, video_id),
                "title": item["title"] or f"{host} video",
            }
        )

    return embeds


def _embed_id_from_src(src: str) -> tuple[str | None, str | None]:
    """
    Parse an embed src URL into a host and video id.

    :param src: The iframe src URL.
    :type src: str
    :return: A tuple of (host, video_id), where host is "youtube" or "vimeo",
        or (None, None) if the URL is not a supported embed.
    :rtype: tuple of (str or None, str or None)
    """

    parsed = urlparse(src or "")
    host = parsed.netloc.lower()
    path = parsed.path or ""

    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if path.startswith("/embed/"):
            video_id = path[len("/embed/") :].split("/")[0].strip()
            if video_id:
                return "youtube", video_id

    if host == "player.vimeo.com" and path.startswith("/video/"):
        video_id = path[len("/video/") :].split("/")[0].strip()
        if video_id:
            return "vimeo", video_id

    return None, None


def _download_url_for(host: str, video_id: str) -> str:
    """
    Build a watchable download URL for a known host and video id.

    :param host: The embed host, "youtube" or "vimeo".
    :type host: str
    :param video_id: The video identifier.
    :type video_id: str
    :return: The full watch URL, or "" for unknown hosts.
    :rtype: str
    """

    if host == "youtube":
        return f"https://www.youtube.com/watch?v={video_id}"

    if host == "vimeo":
        return f"https://vimeo.com/{video_id}"

    return ""


def parse_video_transcriptions(value: str | None) -> dict:
    """
    Parse the note's stored per-video transcription JSON into a dict.

    :param value: The raw JSON text stored on the note.
    :return: A dict keyed by video id.
    """

    try:
        data = json.loads(value or "{}")
    except (TypeError, ValueError):
        data = {}

    return data if isinstance(data, dict) else {}


def format_video_transcripts(note: "Note") -> str:
    """
    Render the note's embedded video transcripts as readable text.

    Kept separate from the speaker-labeled recording transcript so the
    transcripts are always passed to the model even when the recording has
    diarization.

    :param note: Note instance with a video_transcriptions column.
    :return: A formatted multi-video transcript string, or "".
    """

    sections = []
    for video_id, entry in parse_video_transcriptions(
        note.video_transcriptions
    ).items():
        if not isinstance(entry, dict):
            continue

        transcript = (entry.get("transcript") or "").strip()
        if not transcript:
            continue

        title = (entry.get("title") or "").strip() or video_id
        sections.append(f"[Embedded video: {title}]\n{transcript}")

    return "\n\n".join(sections)


def process_video_embeds(note: "Note") -> list[str]:
    """
    Download and transcribe each video embedded in the note's rich HTML.

    Best-effort: per-embed failures are recorded with an empty transcript so a
    broken link is only attempted once. Successful transcripts are merged into
    the note's transcription text and tracked in note.video_transcriptions so
    subsequent runs reuse them.

    :param note: Note instance.
    :return: A list of base64-encoded keyframe images for Ollama (deduplicated).
    """

    embeds = extract_video_embeds(note.notes_html)
    if not embeds:
        return []

    os.makedirs(VIDEO_CACHE_DIR, exist_ok=True)
    processed = parse_video_transcriptions(note.video_transcriptions)
    images = []
    seen = set()

    for embed in embeds:
        video_id = embed["video_id"]
        cache_dir = os.path.join(VIDEO_CACHE_DIR, f"{embed['host']}-{video_id}")

        if video_id not in processed:
            try:
                transcript, title = _process_embed(embed, cache_dir, note)
            except Exception:
                transcript = ""
                title = embed["title"]

            processed[video_id] = {"title": title, "transcript": transcript}

        else:
            entry = processed[video_id]
            title = entry.get("title") if isinstance(entry, dict) else embed["title"]
            transcript = entry.get("transcript") if isinstance(entry, dict) else ""

        # Always re-merge so a retranscribed note (whose transcription field is
        # reset to the raw recording transcript) keeps its video transcripts.
        if transcript:
            _merge_video_transcript(note, title, transcript)

        for frame in _collect_frame_paths(cache_dir):
            encoded = _encode_image(frame)
            if encoded and encoded not in seen:
                images.append(encoded)
                seen.add(encoded)

    note.video_transcriptions = json.dumps(processed, ensure_ascii=False)
    db.session.commit()
    return images


def collect_video_embed_images(notes: list) -> list[str]:
    """
    Collect base64 keyframes already cached for the given notes' video embeds.

    Unlike process_video_embeds, this never downloads anything, so it is safe
    to call on every chat request.

    :param notes: An iterable of Note instances.
    :return: A list of unique base64 image strings.
    """

    images = []
    seen = set()
    for note in notes:
        if not note or not note.notes_html:
            continue

        for embed in extract_video_embeds(note.notes_html):
            cache_dir = os.path.join(
                VIDEO_CACHE_DIR, f"{embed['host']}-{embed['video_id']}"
            )
            for frame in _collect_frame_paths(cache_dir):
                encoded = _encode_image(frame)
                if encoded and encoded not in seen:
                    images.append(encoded)
                    seen.add(encoded)

    return images


def _process_embed(embed: dict, cache_dir: str, note: "Note") -> tuple[str, str]:
    """
    Download, transcribe, and extract keyframes for a single video embed.

    :param embed: Dict with "host", "video_id", "url", and "title" keys.
    :type embed: dict
    :param cache_dir: Directory used to cache the video, audio, and frames.
    :type cache_dir: str
    :param note: The Note instance providing transcription settings.
    :type note: Note
    :return: A tuple of (transcript, title).
    :rtype: tuple of (str, str)
    """

    os.makedirs(cache_dir, exist_ok=True)
    video_path, title = _download_video(embed, cache_dir)
    try:
        audio_path = _extract_audio(video_path, cache_dir)
        transcript = _transcribe_audio(audio_path, note)
        _extract_keyframes(video_path, cache_dir, VIDEO_KEYFRAME_COUNT)
    finally:
        _cleanup_media(video_path, os.path.join(cache_dir, "audio.wav"))

    return transcript, title or embed["title"]


def _download_video(embed: dict, cache_dir: str) -> tuple[str, str]:
    """
    Download a video to the cache dir, reusing an existing download.

    :param embed: Dict with "host", "video_id", "url", and "title" keys.
    :type embed: dict
    :param cache_dir: Directory where the video is cached.
    :type cache_dir: str
    :return: A tuple of (video_path, title).
    :rtype: tuple of (str, str)
    :raises RuntimeError: If yt-dlp did not produce a video file.
    """

    cached_path = _find_downloaded_video(cache_dir)
    if cached_path:
        return cached_path, _cached_title(cache_dir, embed)

    ydl_opts = {
        "format": "best[height<=720]/best",
        "outtmpl": os.path.join(cache_dir, "video.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 3,
        "socket_timeout": 30,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(embed["url"], download=True)

    video_path = _find_downloaded_video(cache_dir)
    if not video_path:
        raise RuntimeError("yt-dlp did not produce a video file.")

    title = (info or {}).get("title") or embed["title"]
    _write_cache_json(cache_dir, {"title": title})
    return video_path, title


def _find_downloaded_video(cache_dir: str) -> str | None:
    """
    Find the largest cached video file in the given directory.

    :param cache_dir: Directory to search for downloaded videos.
    :type cache_dir: str
    :return: Path to the video file, or None if none is found.
    :rtype: str or None
    """

    if not os.path.isdir(cache_dir):
        return None

    candidates = [
        path
        for path in glob.glob(os.path.join(cache_dir, "video.*"))
        if not path.endswith((".part", ".ytdl", ".info.json"))
    ]

    return max(candidates, key=os.path.getsize) if candidates else None


def _write_cache_json(cache_dir: str, data: dict) -> None:
    """
    Write metadata for a cached video, ignoring write failures.

    :param cache_dir: Directory containing the cache.
    :type cache_dir: str
    :param data: Dict of metadata to persist.
    :type data: dict
    :return: None
    :rtype: None
    """

    try:
        with open(os.path.join(cache_dir, "info.json"), "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False)

    except OSError:
        pass


def _cached_title(cache_dir: str, embed: dict) -> str:
    """
    Return the cached video title, falling back to the embed title.

    :param cache_dir: Directory containing the cache.
    :type cache_dir: str
    :param embed: Dict with a "title" fallback value.
    :type embed: dict
    :return: The video title string.
    :rtype: str
    """

    try:
        with open(os.path.join(cache_dir, "info.json"), "r", encoding="utf-8") as file:
            data = json.load(file)
        return data.get("title") or embed["title"]
    except (OSError, ValueError):
        return embed["title"]


def _extract_audio(video_path: str, cache_dir: str) -> str:
    """
    Extract a mono 16kHz WAV track from a video using ffmpeg.

    Reuses an existing audio file when one is already cached.

    :param video_path: Path to the video file.
    :type video_path: str
    :param cache_dir: Directory where the audio file is cached.
    :type cache_dir: str
    :return: Path to the extracted audio file.
    :rtype: str
    :raises subprocess.CalledProcessError: If ffmpeg fails.
    """

    audio_path = os.path.join(cache_dir, "audio.wav")
    if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
        return audio_path

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            video_path,
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            audio_path,
        ],
        check=True,
        capture_output=True,
    )
    return audio_path


def _extract_keyframes(video_path: str, cache_dir: str, count: int) -> list[str]:
    """
    Extract up to count keyframe images from a video.

    Prefers scene-detected frames and falls back to evenly spaced frames when
    too few are found. Reuses existing frames when enough are cached.

    :param video_path: Path to the video file.
    :type video_path: str
    :param cache_dir: Directory where the frames are cached.
    :type cache_dir: str
    :param count: Maximum number of frames to extract.
    :type count: int
    :return: List of paths to the extracted frame images.
    :rtype: list of str
    """

    frames_dir = os.path.join(cache_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    frames = _collect_frame_paths(cache_dir)
    if len(frames) >= count:
        return frames

    for frame in frames:
        os.remove(frame)

    # Scene-detection first: keep frames where the content changes noticeably,
    # scaled to a max width of 640px to keep the encoded images small.
    scene_filter = "select='gt(scene,0.35)',scale='min(640,iw)':-2"
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                video_path,
                "-vf",
                scene_filter,
                "-frames:v",
                str(count),
                "-q:v",
                "3",
                os.path.join(frames_dir, "frame_%03d.jpg"),
            ],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass

    frames = _collect_frame_paths(cache_dir)
    if len(frames) >= count:
        return frames

    # Fall back to evenly spaced frames for static or scene-light videos.
    for frame in frames:
        os.remove(frame)

    duration = _probe_duration(video_path)
    step = (duration or 60.0) / (count + 1)
    for index in range(1, count + 1):
        out_path = os.path.join(frames_dir, f"frame_{index:03d}.jpg")
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    str(step * index),
                    "-i",
                    video_path,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    "-vf",
                    "scale='min(640,iw)':-2",
                    out_path,
                ],
                check=True,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            break

    return _collect_frame_paths(cache_dir)


def _collect_frame_paths(cache_dir: str) -> list[str]:
    """
    List cached keyframe image paths in sorted order.

    :param cache_dir: Directory containing the frames subdirectory.
    :type cache_dir: str
    :return: Sorted list of frame image paths.
    :rtype: list of str
    """

    return sorted(glob.glob(os.path.join(cache_dir, "frames", "frame_*.jpg")))


def _probe_duration(video_path: str) -> float | None:
    """
    Probe a video's duration in seconds with ffprobe.

    :param video_path: Path to the video file.
    :type video_path: str
    :return: The duration in seconds, or None on failure.
    :rtype: float or None
    """

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())

    except (subprocess.CalledProcessError, ValueError, FileNotFoundError, OSError):
        return None


def _encode_image(path: str) -> str | None:
    """
    Encode an image file as a base64 string for Ollama.

    :param path: Path to the image file.
    :type path: str
    :return: Base64-encoded image string, or None on failure.
    :rtype: str or None
    """

    try:
        with open(path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("ascii")
    except OSError:
        return None


def _transcribe_audio(audio_path: str, note: "Note") -> str:
    """
    Transcribe an audio file with Whisper and return the text.

    Whisper is imported lazily to avoid a circular import. Hindi-specific
    settings are used when the note's subject is Hindi.

    :param audio_path: Path to the audio file to transcribe.
    :type audio_path: str
    :param note: The Note instance providing transcription settings.
    :type note: Note
    :return: The stripped transcription text.
    :rtype: str
    """

    # Imported lazily to avoid a circular import (audio.transcription imports
    # this module at the top level).
    from audio.transcription import get_whisper_model  # noqa: PLC0415

    transcribe_kwargs = {
        "fp16": False,
        "word_timestamps": False,
        "verbose": False,
    }

    if note and note.subject == HINDI_SUBJECT:
        transcribe_kwargs["language"] = "hi"
        transcribe_kwargs["initial_prompt"] = HINDI_INITIAL_PROMPT
        transcribe_kwargs["beam_size"] = 5

    result = get_whisper_model().transcribe(audio_path, **transcribe_kwargs)
    return (result.get("text") or "").strip()


def _merge_video_transcript(note: "Note", title: str, transcript: str) -> None:
    """
    Append a video transcript to a note's transcription text.

    Skips the merge when the transcript is empty or already present.

    :param note: The Note instance to update.
    :type note: Note
    :param title: Title of the embedded video.
    :type title: str
    :param transcript: The video's transcription text.
    :type transcript: str
    :return: None
    :rtype: None
    """

    if not transcript:
        return

    header = f"[Embedded video: {title}]" if title else "[Embedded video]"
    if header in (note.transcription or ""):
        return

    existing = (note.transcription or "").rstrip()
    note.transcription = (
        f"{existing}\n\n{header}\n{transcript}"
        if existing
        else f"{header}\n{transcript}"
    )


def _cleanup_media(video_path: str, audio_path: str) -> None:
    """
    Best-effort removal of temporary video and audio files.

    :param video_path: Path to the video file to remove.
    :type video_path: str
    :param audio_path: Path to the audio file to remove.
    :type audio_path: str
    :return: None
    :rtype: None
    """

    for path in (video_path, audio_path):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
