from pathlib import Path
import hashlib


BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "cache" / "audio"

CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


def get_audio_path(text, language):
    safe_text = hashlib.md5(
        text.encode("utf-8")
    ).hexdigest()

    filename = f"{safe_text}_{language}.mp3"

    return CACHE_DIR / filename