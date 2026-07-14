from filename import (
    create_filename,
    create_readable_filename_part,
)


def check_french_diacritics():
    assert (
        create_readable_filename_part(
            "un bâtiment très âgé"
        )
        == "un_bâtiment_très_âgé"
    )


def check_japanese_text():
    assert (
        create_readable_filename_part(
            "読む（よむ）— to read"
        )
        == "読む_よむ_to_read"
    )


def check_multiple_writing_systems():
    examples = {
        "Здравствуйте, мир!": (
            "Здравствуйте_мир"
        ),
        "안녕하세요": "안녕하세요",
        "مرحبا بالعالم": (
            "مرحبا_بالعالم"
        ),
        "नमस्ते दुनिया": (
            "नमस्ते_दुनिया"
        ),
    }

    for text, expected in examples.items():
        assert (
            create_readable_filename_part(
                text
            )
            == expected
        )


def check_forbidden_characters():
    assert (
        create_readable_filename_part(
            'one/two\\three:*?"<>|four'
        )
        == "one_two_three_four"
    )


def check_emoji_and_punctuation_fallback():
    assert (
        create_readable_filename_part(
            "😀 !!!"
        )
        == "audio"
    )


def check_windows_reserved_names():
    assert (
        create_readable_filename_part(
            "CON"
        )
        == "audio"
    )

    assert (
        create_readable_filename_part(
            "LPT1"
        )
        == "audio"
    )


def check_deterministic_filename():
    first = create_filename(
        "un bâtiment"
    )

    second = create_filename(
        "un bâtiment"
    )

    assert first == second
    assert first.startswith(
        "un_bâtiment_"
    )
    assert first.endswith(
        ".mp3"
    )


def check_different_text_has_different_hash():
    assert (
        create_filename(
            "café"
        )
        != create_filename(
            "cafe"
        )
    )


def check_readable_part_is_limited():
    filename = create_filename(
        "語" * 100
    )

    readable_part = filename.rsplit(
        "_",
        1,
    )[0]

    assert len(
        readable_part
    ) == 40


def run():
    checks = [
        check_french_diacritics,
        check_japanese_text,
        check_multiple_writing_systems,
        check_forbidden_characters,
        check_emoji_and_punctuation_fallback,
        check_windows_reserved_names,
        check_deterministic_filename,
        check_different_text_has_different_hash,
        check_readable_part_is_limited,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")