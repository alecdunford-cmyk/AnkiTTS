import hashlib
import re


def create_filename(text):
    """
    Create a stable filename from card text.
    """

    cleaned = re.sub(
        r'[^a-zA-Z0-9]+',
        '_',
        text
    ).strip("_")

    short_hash = hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()[:8]

    return f"{cleaned[:40]}_{short_hash}.mp3"