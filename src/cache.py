import hashlib
from pathlib import Path


CACHE_DIR = Path("cache/audio")

CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


def get_audio_path(text, language):

    key = (
        language
        + ":"
        + text
    )

    filename = (
        hashlib.sha256(
            key.encode("utf-8")
        )
        .hexdigest()
        + ".mp3"
    )

    return CACHE_DIR / filename