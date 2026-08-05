"""

This module provides utilities for filtering, sanitizing, and converting rich text
and markdown content, including HTML parsing and sanitization for notes.

"""

# Import required modules
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse
import markdown
from markupsafe import Markup, escape
import bleach
from bleach.css_sanitizer import CSSSanitizer

LIST_ITEM_RE = re.compile(r"^([ \t]*)([-*+]|\d+\.)\s+")
ALLOWED_RICH_NOTE_TAGS = [
    "a",
    "b",
    "blockquote",
    "br",
    "caption",
    "code",
    "col",
    "colgroup",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "iframe",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "span",
    "strike",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
]

ALLOWED_RICH_NOTE_ATTRIBUTES = {
    "*": ["style", "class", "dir"],
    "a": ["href", "title", "target", "rel"],
    "iframe": [
        "src",
        "title",
        "allow",
        "allowfullscreen",
        "loading",
        "referrerpolicy",
        "width",
        "height",
    ],
    "img": ["src", "alt", "title", "width", "height"],
    "li": ["data-checked"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
    "span": ["style", "class", "data-latex", "contenteditable", "title", "id"],
}

ALLOWED_RICH_NOTE_PROTOCOLS = ["http", "https", "mailto", "data"]
ALLOWED_IMAGE_DATA_RE = re.compile(
    r"^data:image/(png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$",
    re.IGNORECASE,
)

RICH_NOTE_CSS_SANITIZER = CSSSanitizer(
    allowed_css_properties=[
        "background-color",
        "color",
        "font-weight",
        "font-style",
        "font-size",
        "font-family",
        "text-align",
        "text-decoration",
        "direction",
        "unicode-bidi",
        "list-style-type",
        "white-space",
    ]
)

ALLOWED_VIDEO_EMBED_HOSTS = {
    "www.youtube-nocookie.com",
    "youtube-nocookie.com",
    "www.youtube.com",
    "youtube.com",
    "player.vimeo.com",
}


class RichNoteTextParser(HTMLParser):
    """
    HTML parser that converts rich note HTML into plain text.
    """

    def __init__(self):
        """
        Initialize the parser with empty output parts.

        :return: None
        :rtype: None
        """

        super().__init__()
        self.parts = []
        self.skip_math_depth = 0

    def handle_starttag(self, tag, attrs):
        """
        Handle the start of an HTML tag, appending text separators or markers.

        Appends newlines for block elements, "- " for list items, image/video
        placeholders, and skips LaTeX math-field content.

        :param tag: The HTML tag name.
        :type tag: str
        :param attrs: The tag's attributes.
        :type attrs: list of tuple
        :return: None
        :rtype: None
        """
        if self.skip_math_depth:
            self.skip_math_depth += 1
            return

        if tag in {"p", "div", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

        elif tag == "li":
            self.parts.append("\n- ")

        elif tag == "br":
            self.parts.append("\n")

        elif tag == "img":
            attrs_by_name = dict(attrs)
            alt = (attrs_by_name.get("alt") or "").strip()
            src = (attrs_by_name.get("src") or "").strip()
            if alt or src:
                self.parts.append(f" [Image: {alt or src}] ")

        elif tag == "iframe":
            attrs_by_name = dict(attrs)
            title = (attrs_by_name.get("title") or "Video").strip()
            self.parts.append(f" [{title}] ")

        elif tag == "span":
            attrs_by_name = dict(attrs)
            classes = set((attrs_by_name.get("class") or "").split())
            latex = (attrs_by_name.get("data-latex") or "").strip()
            if "math-field" in classes and latex:
                self.parts.append(f" ${latex}$ ")
                self.skip_math_depth = 1

    def handle_endtag(self, tag):
        """
        Handle the end of an HTML tag, unwinding math-field skipping.

        :param tag: The HTML tag name.
        :type tag: str
        :return: None
        :rtype: None
        """
        if self.skip_math_depth:
            self.skip_math_depth -= 1

    def handle_data(self, data):
        """
        Append text data unless inside a skipped math-field span.

        :param data: The text content of the element.
        :type data: str
        :return: None
        :rtype: None
        """
        if self.skip_math_depth:
            return
        self.parts.append(data)

    def get_text(self):
        """
        Build and clean the collected plain text.

        Collapses runs of whitespace and drops blank lines.

        :return: The plain text representation of the HTML.
        :rtype: str
        """
        text = "".join(self.parts)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def normalize_list_indentation(text):
    """
    Clamp list-item indentation to what's reachable via preceding items.

    LLM-generated markdown sometimes indents top-level bullets by 4 spaces
    with no parent list item above them, which Python-Markdown parses as an
    indented code block instead of a list. This flattens such runaway
    indentation while still allowing genuine nested lists.

    :param text: Markdown text to normalize
    :return: Markdown text with normalized list indentation
    """

    stack = []  # (raw_indent, normalized_indent) per open list level
    lines = []
    for line in text.split("\n"):
        match = LIST_ITEM_RE.match(line)
        if match:
            raw_indent = len(match.group(1).expandtabs())
            while stack and stack[-1][0] > raw_indent:
                stack.pop()

            if stack and stack[-1][0] == raw_indent:
                indent = stack[-1][1]

            elif stack:
                indent = stack[-1][1] + 4

            else:
                indent = 0

            stack.append((raw_indent, indent))
            lines.append(" " * indent + line[match.end(1) :])

        elif line.strip():
            lines.append(line)
            stack = []

        else:
            lines.append(line)

    return "\n".join(lines)


def render_markdown(text):
    """
    Render markdown text to safe HTML.

    Normalizes list indentation before rendering and returns the result as a
    Markup object.

    :param text: The markdown text to render.
    :type text: str
    :return: Rendered HTML as a Markup object, or "" if text is empty.
    :rtype: markupsafe.Markup or str
    """

    if not text:
        return ""

    return Markup(
        markdown.markdown(
            normalize_list_indentation(text),
            extensions=["sane_lists", "tables"],
        )
    )


def sanitize_rich_note_html(html):
    """
    Sanitize HTML content for rich notes, removing unsafe tags and attributes.

    :param html: The HTML content to sanitize.
    :type html: str or None
    :return: Sanitized HTML content safe for rendering in the application.
    :rtype: str or None
    """

    html = (html or "").strip()
    if not html:
        return None

    html = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=re.IGNORECASE | re.DOTALL
    )

    html = re.sub(
        r"<iframe\b(?P<attrs>[^>]*)>.*?</iframe>",
        keep_allowed_iframe,
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if bleach is None:
        return str(escape(html))

    cleaned = bleach.clean(
        html,
        tags=ALLOWED_RICH_NOTE_TAGS,
        attributes=allow_rich_note_attribute,
        protocols=ALLOWED_RICH_NOTE_PROTOCOLS,
        css_sanitizer=RICH_NOTE_CSS_SANITIZER,
        strip=True,
    )

    cleaned = bleach.linkify(cleaned, callbacks=[set_link_attrs])
    return cleaned.strip() or None


def allow_rich_note_attribute(tag, name, value):
    """
    Callback function for bleach.clean to determine if a specific attribute
    is allowed for a given HTML tag.

    :param tag: The HTML tag name (e.g., 'a', 'img').
    :type tag: str
    :param name: The attribute name (e.g., 'href', 'src').
    :type name: str
    :param value: The attribute value (e.g., 'https://example.com').
    :type value: str
    :return: True if the attribute is allowed for the tag, False otherwise.
    :rtype: bool
    """

    allowed = set(ALLOWED_RICH_NOTE_ATTRIBUTES.get("*", []))
    allowed.update(ALLOWED_RICH_NOTE_ATTRIBUTES.get(tag, []))
    if name not in allowed:
        return False

    if name == "dir":
        return value in {"ltr", "rtl", "auto"}

    if tag == "li" and name == "data-checked":
        return value in {"true", "false"}

    if tag == "img" and name == "src" and (value or "").lower().startswith("data:"):
        return bool(ALLOWED_IMAGE_DATA_RE.match(value or ""))

    if tag == "iframe" and name == "src":
        return is_allowed_video_embed_src(value)

    if (
        tag not in {"img", "iframe"}
        and name in {"href", "src"}
        and (value or "").lower().startswith("data:")
    ):
        return False

    return True


def keep_allowed_iframe(match):
    """
    Keep an iframe match only if its src is an allowed video embed.

    Used as the replacement callable when stripping iframes from rich note HTML.

    :param match: A regex match for an iframe tag.
    :type match: re.Match
    :return: The original iframe HTML if allowed, otherwise "".
    :rtype: str
    """

    src_match = re.search(
        r"\bsrc=[\"']([^\"']+)[\"']", match.group("attrs"), flags=re.IGNORECASE
    )

    if not src_match or not is_allowed_video_embed_src(src_match.group(1)):
        return ""

    return match.group(0)


def is_allowed_video_embed_src(value):
    """
    Check whether a URL is an allowed YouTube or Vimeo embed source.

    :param value: The iframe src URL to check.
    :type value: str
    :return: True if the URL is an allowed embed, False otherwise.
    :rtype: bool
    """

    parsed = urlparse(value or "")
    host = parsed.netloc.lower()
    path = parsed.path or ""
    if parsed.scheme != "https" or host not in ALLOWED_VIDEO_EMBED_HOSTS:
        return False

    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        return path.startswith("/embed/")

    if host == "player.vimeo.com":
        return path.startswith("/video/")

    return False


def set_link_attrs(attrs, new=False):
    """
    Add target and rel attributes to a linkified anchor.

    Used as a bleach linkify callback.

    :param attrs: The current link attributes dict.
    :type attrs: dict
    :param new: Whether the link was newly created by linkify.
    :type new: bool
    :return: The updated attributes dict.
    :rtype: dict
    """

    attrs[(None, "target")] = "_blank"
    attrs[(None, "rel")] = "noopener noreferrer"
    return attrs


def render_rich_note_html(html):
    """
    Sanitize rich note HTML and return it as a safe Markup object.

    :param html: The HTML content to sanitize.
    :type html: str
    :return: Sanitized HTML as a Markup object.
    :rtype: markupsafe.Markup
    """

    return Markup(sanitize_rich_note_html(html) or "")


def rich_note_html_to_text(html):
    """
    Convert rich note HTML into plain text.

    :param html: The HTML content to convert.
    :type html: str
    :return: The plain text representation of the HTML.
    :rtype: str
    """

    parser = RichNoteTextParser()
    parser.feed(sanitize_rich_note_html(html) or "")
    return parser.get_text()


def parse_json(value):
    """
    Parse a JSON string into a list, defaulting to an empty list.

    :param value: The JSON string to parse.
    :type value: str or None
    :return: The parsed list, or [] if the value is empty or invalid.
    :rtype: list
    """

    if not value:
        return []

    try:
        return json.loads(value)

    except (TypeError, ValueError):
        return []
