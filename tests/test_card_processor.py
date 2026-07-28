import batch_processor

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


def check_batch_reports_elapsed_time():
    original_process = (
        batch_processor.process_field_definitions
    )

    original_timer = (
        batch_processor.perf_counter
    )

    timer_values = iter(
        [
            10.0,
            12.5,
        ]
    )

    try:
        batch_processor.process_field_definitions = (
            lambda fields, settings: {
                "statistics": {
                    "generated": 1,
                    "cached": 0,
                    "skipped": 0,
                },
            }
        )

        batch_processor.perf_counter = (
            lambda: next(
                timer_values
            )
        )

        result = batch_processor.process_notes(
            [
                {
                    "fields": [],
                },
            ],
            AppSettings(),
        )

        assert result[
            "elapsed_seconds"
        ] == 2.5

    finally:
        batch_processor.process_field_definitions = (
            original_process
        )

        batch_processor.perf_counter = (
            original_timer
        )


def run():
    checks = [
        check_front_profile,
        check_auto_profile,
        check_explicit_profiles,
        check_invalid_profile,
        check_batch_reports_elapsed_time,
    ]

    for check in checks:
        print(f"    {check.__name__}...", end=" ")
        check()
        print("✓")
