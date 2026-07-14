from pathlib import Path
from shutil import rmtree
import hashlib
import json


BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "cache" / "audio"

CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


def get_cache_statistics():
    """
    Return the number and total size of cached audio files.
    """

    file_count = 0
    total_size = 0

    if not CACHE_DIR.exists():
        return {
            "file_count": 0,
            "total_size": 0,
        }

    for cache_file in CACHE_DIR.iterdir():
        if not cache_file.is_file():
            continue

        file_count += 1
        total_size += cache_file.stat().st_size

    return {
        "file_count": file_count,
        "total_size": total_size,
    }


def clear_audio_cache():
    """
    Delete every cached audio file and recreate the cache directory.

    Return statistics describing what was removed.
    """

    statistics = get_cache_statistics()

    if CACHE_DIR.exists():
        rmtree(
            CACHE_DIR
        )

    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    return statistics


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