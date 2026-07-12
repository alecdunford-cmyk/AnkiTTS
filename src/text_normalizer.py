import re


def normalize_text(text):
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