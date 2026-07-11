from pathlib import Path
import hashlib
import json


BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "cache" / "audio"

CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


def get_audio_path(
    text,
    language,
    voice,
    rate="+0%",
    volume="+0%",
    pitch="+0Hz",
):
    """
    Return a cache path unique to the text and every setting
    that can affect the generated audio.
    """

    cache_data = {
        "text": text,
        "language": language,
        "voice": voice,
        "rate": rate,
        "volume": volume,
        "pitch": pitch,
    }

    serialized_data = json.dumps(
        cache_data,
        ensure_ascii=False,
        sort_keys=True,
    )

    cache_hash = hashlib.sha256(
        serialized_data.encode("utf-8")
    ).hexdigest()

    filename = f"{cache_hash}.mp3"

    return CACHE_DIR / filename