from cache import (
    CACHE_DIR,
    clear_audio_cache,
    get_cache_statistics,
)


def check_empty_cache_statistics():
    clear_audio_cache()

    statistics = get_cache_statistics()

    assert statistics == {
        "file_count": 0,
        "total_size": 0,
    }


def check_cache_statistics():
    clear_audio_cache()

    first_file = CACHE_DIR / "first.mp3"
    second_file = CACHE_DIR / "second.mp3"

    first_file.write_bytes(
        b"12345"
    )

    second_file.write_bytes(
        b"1234567890"
    )

    statistics = get_cache_statistics()

    assert statistics == {
        "file_count": 2,
        "total_size": 15,
    }


def check_clear_audio_cache():
    clear_audio_cache()

    nested_directory = (
        CACHE_DIR
        / "temporary"
    )

    nested_directory.mkdir()

    (
        CACHE_DIR
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

    removed_statistics = clear_audio_cache()

    assert removed_statistics == {
        "file_count": 1,
        "total_size": 12,
    }

    assert CACHE_DIR.exists()
    assert list(
        CACHE_DIR.iterdir()
    ) == []


def run():
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