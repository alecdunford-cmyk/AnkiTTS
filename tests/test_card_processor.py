from card_processor import resolve_field_language
from settings import AppSettings


def check_front_profile():
    settings = AppSettings()
    settings.front_language = "fr"

    assert (
        resolve_field_language(
            {"speech_profile": "front"},
            settings,
        )
        == "fr"
    )


def check_auto_profile():
    settings = AppSettings()

    assert (
        resolve_field_language(
            {"speech_profile": "auto"},
            settings,
        )
        is None
    )


def check_explicit_profiles():
    settings = AppSettings()

    for language in (
        "fr",
        "en",
        "ja",
    ):
        assert (
            resolve_field_language(
                {
                    "speech_profile": language,
                },
                settings,
            )
            == language
        )


def check_invalid_profile():
    settings = AppSettings()

    try:
        resolve_field_language(
            {
                "speech_profile": "banana",
            },
            settings,
        )

    except ValueError:
        return

    raise AssertionError(
        "Invalid speech profile was accepted."
    )


def run():
    checks = [
        check_front_profile,
        check_auto_profile,
        check_explicit_profiles,
        check_invalid_profile,
    ]

    for check in checks:
        print(f"    {check.__name__}...", end=" ")
        check()
        print("✓")