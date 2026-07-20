import json
import re

import markdown
from markupsafe import Markup

LIST_ITEM_RE = re.compile(r"^([ \t]*)([-*+]|\d+\.)\s+")


def normalize_list_indentation(text):
    """Clamp list-item indentation to what's reachable via preceding items.

    LLM-generated markdown sometimes indents top-level bullets by 4 spaces
    with no parent list item above them, which Python-Markdown parses as an
    indented code block instead of a list. This flattens such runaway
    indentation while still allowing genuine nested lists.
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
    if not text:
        return ""
    return Markup(
        markdown.markdown(
            normalize_list_indentation(text),
            extensions=["sane_lists", "tables"],
        )
    )


def parse_json(value):
    if not value:
        return []
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return []
