from pathlib import Path
from tempfile import TemporaryDirectory

import cache


def check_empty_cache_statistics():
    cache.clear_audio_cache()

    statistics = cache.get_cache_statistics()

    assert statistics == {
        "file_count": 0,
        "total_size": 0,
    }


def check_cache_statistics():
    cache.clear_audio_cache()

    first_file = cache.CACHE_DIR / "first.mp3"
    second_file = cache.CACHE_DIR / "second.mp3"

    first_file.write_bytes(
        b"12345"
    )

    second_file.write_bytes(
        b"1234567890"
    )

    statistics = cache.get_cache_statistics()

    assert statistics == {
        "file_count": 2,
        "total_size": 15,
    }


def check_clear_audio_cache():
    cache.clear_audio_cache()

    nested_directory = (
        cache.CACHE_DIR
        / "temporary"
    )

    nested_directory.mkdir()

    (
        cache.CACHE_DIR
        / "cached.mp3"
    ).write_bytes(
        b"cached audio"
    )

    (
        nested_directory
        / "nested.tmp"
    ).write_bytes(
        b"temporary"
    )

    removed_statistics = cache.clear_audio_cache()

    assert removed_statistics == {
        "file_count": 1,
        "total_size": 12,
    }

    assert cache.CACHE_DIR.exists()
    assert list(
        cache.CACHE_DIR.iterdir()
    ) == []


def run():
    original_cache_dir = cache.CACHE_DIR

    try:
        with TemporaryDirectory() as temporary_directory:
            cache.CACHE_DIR = (
                Path(
                    temporary_directory
                )
                / "audio"
            )

            cache.CACHE_DIR.mkdir(
                parents=True,
                exist_ok=True,
            )

            checks = [
                check_empty_cache_statistics,
                check_cache_statistics,
                check_clear_audio_cache,
            ]

            for check in checks:
                print(
                    f"    {check.__name__}...",
                    end=" ",
                )

                check()

                print("✓")

    finally:
        cache.CACHE_DIR = original_cache_dir