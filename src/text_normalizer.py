import html
import re


BLOCK_BREAK_PATTERN = re.compile(
    r"<\s*(?:br|div|p|li|tr|h[1-6])\b[^>]*>",
    flags=re.IGNORECASE,
)

CLOSING_BLOCK_PATTERN = re.compile(
    r"<\s*/\s*(?:div|p|li|tr|h[1-6])\s*>",
    flags=re.IGNORECASE,
)

HTML_TAG_PATTERN = re.compile(
    r"<[^>]+>"
)


def strip_html(text):
    """
    Convert Anki field HTML into readable plain text.

    Block-level elements become spaces before the remaining tags
    are removed, preventing adjacent pieces of text from merging.
    """

    text = BLOCK_BREAK_PATTERN.sub(
        " ",
        text,
    )

    text = CLOSING_BLOCK_PATTERN.sub(
        " ",
        text,
    )

    text = HTML_TAG_PATTERN.sub(
        "",
        text,
    )

    return html.unescape(
        text
    )


def normalize_text(text):
    """Normalize Anki field content before parsing and speech."""

    text = strip_html(
        text
    )

    # Treat every slash as a comma-like spoken pause,
    # regardless of whether spaces surround it.
    text = re.sub(
        r"\s*/\s*",
        ", ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()