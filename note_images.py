"""

This module provides functions to extract and process images from rich note HTML content. It includes functionality to parse HTML, extract image sources, validate local image paths, and encode images for use with Ollama.

"""

# Import required modules
import base64
import os
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urlparse

# Import configuration and text filter functions
from config import NOTE_IMAGES_DIR
from text_filters import sanitize_rich_note_html

LOCAL_NOTE_IMAGE_ROUTE = "/recordings/note_images/"
SUPPORTED_OLLAMA_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
DATA_IMAGE_RE = re.compile(
    r"^data:image/(?P<type>png|jpe?g|gif|webp);base64,(?P<data>.+)$",
    re.IGNORECASE | re.DOTALL,
)


class RichNoteImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []

    def handle_starttag(self, tag, attrs):
        if tag != "img":
            return
        attrs_by_name = dict(attrs)
        src = (attrs_by_name.get("src") or "").strip()
        if src:
            self.images.append(
                {
                    "src": src,
                    "alt": (attrs_by_name.get("alt") or "").strip(),
                }
            )


def extract_rich_note_images(html):
    parser = RichNoteImageParser()
    parser.feed(sanitize_rich_note_html(html) or "")
    return parser.images


def note_image_path_from_src(src):
    parsed = urlparse(src)
    if parsed.scheme or parsed.netloc:
        return None

    path = unquote(parsed.path or "")
    if not path.startswith(LOCAL_NOTE_IMAGE_ROUTE):
        return None

    filename = path[len(LOCAL_NOTE_IMAGE_ROUTE) :]
    if not filename:
        return None

    image_path = os.path.abspath(os.path.join(NOTE_IMAGES_DIR, filename))
    note_images_dir = os.path.abspath(NOTE_IMAGES_DIR)
    if os.path.commonpath([note_images_dir, image_path]) != note_images_dir:
        return None

    extension = os.path.splitext(image_path)[1].lower()
    if extension not in SUPPORTED_OLLAMA_IMAGE_EXTENSIONS or not os.path.exists(
        image_path
    ):
        return None

    return image_path


def ollama_image_from_src(src):
    data_match = DATA_IMAGE_RE.match(src or "")
    if data_match:
        return re.sub(r"\s+", "", data_match.group("data"))

    image_path = note_image_path_from_src(src)
    if not image_path:
        return None

    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("ascii")


def collect_ollama_note_images(notes):
    images = []
    seen = set()
    for note in notes:
        for image in extract_rich_note_images(note.notes_html):
            encoded = ollama_image_from_src(image["src"])
            if not encoded or encoded in seen:
                continue
            images.append(encoded)
            seen.add(encoded)
    return images
