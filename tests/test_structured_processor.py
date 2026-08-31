from __future__ import annotations

from decimal import Decimal
import json

from settings import AppSettings
from speech_plan import parse_speech_plan
from structured_processor import (
    StructuredSpeechProcessingError,
    compose_edge_rate,
    parse_edge_rate_multiplier,
    resolve_speech_plan,
)


def create_segment(
    **overrides,
):
    segment = {
        "sequence": 1,
        "segmentId": "cue:repetition:1",
        "cueId": "cue",
        "contentNodeId": "content",
        "repetitionNumber": 1,
        "repetitionCount": 1,
        "text": "faire",
        "language": "fr-FR",
        "voiceProfileId": "",
        "speakingRate": 1.0,
        "pauseBeforeMilliseconds": 300,
        "pauseAfterMilliseconds": 500,
    }

    segment.update(
        overrides
    )

    return segment


def create_plan(
    side="front",
    segments=None,
):
    if segments is None:
        segments = [
            create_segment()
        ]

    return parse_speech_plan(
        json.dumps(
            {
                "schemaVersion": 1,
                "side": side,
                "segments": segments,
            },
            ensure_ascii=False,
        ),
        side,
    )


def expect_processing_error(
    action,
):
    try:
        action()

    except StructuredSpeechProcessingError:
        return

    raise AssertionError(
        "Invalid structured speech input was accepted."
    )


def check_locale_profile_resolution():
    examples = (
        (
            "fr-FR",
            "fr",
            "fr-FR-DeniseNeural",
        ),
        (
            "en-US",
            "en",
            "en-US-JennyNeural",
        ),
        (
            "ja-JP",
            "ja",
            "ja-JP-NanamiNeural",
        ),
        (
            "FR-ca",
            "fr",
            "fr-FR-DeniseNeural",
        ),
        (
            "en_GB",
            "en",
            "en-US-JennyNeural",
        ),
    )

    for language, expected_key, expected_voice in examples:
        track = resolve_speech_plan(
            create_plan(
                segments=[
                    create_segment(
                        language=language
                    )
                ]
            ),
            AppSettings(),
        )

        segment = track.segments[0]

        assert (
            segment.resolved_profile_key
            == expected_key
        )

        assert segment.voice == expected_voice
        assert segment.language == language


def check_known_logical_aliases():
    examples = (
        (
            "french-primary",
            "fr-FR",
            "fr",
        ),
        (
            "english-primary",
            "en-US",
            "en",
        ),
        (
            "japanese-primary",
            "ja-JP",
            "ja",
        ),
        (
            "FRENCH-PRIMARY",
            "fr-FR",
            "fr",
        ),
    )

    for profile_id, language, expected_key in examples:
        track = resolve_speech_plan(
            create_plan(
                segments=[
                    create_segment(
                        language=language,
                        voiceProfileId=profile_id,
                    )
                ]
            ),
            AppSettings(),
        )

        assert (
            track.segments[0].resolved_profile_key
            == expected_key
        )


def check_direct_profile_key():
    track = resolve_speech_plan(
        create_plan(
            segments=[
                create_segment(
                    voiceProfileId="fr"
                )
            ]
        ),
        AppSettings(),
    )

    assert (
        track.segments[0].resolved_profile_key
        == "fr"
    )


def check_und_requires_logical_profile():
    expect_processing_error(
        lambda: resolve_speech_plan(
            create_plan(
                segments=[
                    create_segment(
                        language="und",
                        voiceProfileId="",
                    )
                ]
            ),
            AppSettings(),
        )
    )

    track = resolve_speech_plan(
        create_plan(
            segments=[
                create_segment(
                    language="und",
                    voiceProfileId="english-primary",
                )
            ]
        ),
        AppSettings(),
    )

    assert (
        track.segments[0].resolved_profile_key
        == "en"
    )


def check_unknown_or_mismatched_profile_fails():
    expect_processing_error(
        lambda: resolve_speech_plan(
            create_plan(
                segments=[
                    create_segment(
                        voiceProfileId="banana"
                    )
                ]
            ),
            AppSettings(),
        )
    )

    expect_processing_error(
        lambda: resolve_speech_plan(
            create_plan(
                segments=[
                    create_segment(
                        language="en-US",
                        voiceProfileId="french-primary",
                    )
                ]
            ),
            AppSettings(),
        )
    )


def check_unsupported_locale_fails():
    expect_processing_error(
        lambda: resolve_speech_plan(
            create_plan(
                segments=[
                    create_segment(
                        language="de-DE"
                    )
                ]
            ),
            AppSettings(),
        )
    )


def check_missing_anki_profile_fails():
    settings = AppSettings()
    settings.voices.clear()
    settings.speech_profiles.clear()

    expect_processing_error(
        lambda: resolve_speech_plan(
            create_plan(),
            settings,
        )
    )


def check_authoritative_schedule_is_preserved():
    text = (
        "  <b>faire</b> / agir; "
        "(especially Sport) 日本語  "
    )

    track = resolve_speech_plan(
        create_plan(
            side="back",
            segments=[
                create_segment(
                    sequence=1,
                    segmentId="cue:repetition:1",
                    cueId="cue",
                    contentNodeId="",
                    repetitionNumber=1,
                    repetitionCount=2,
                    text=text,
                    speakingRate=1.125,
                    pauseBeforeMilliseconds=650,
                    pauseAfterMilliseconds=600,
                ),
                create_segment(
                    sequence=2,
                    segmentId="cue:repetition:2",
                    cueId="cue",
                    contentNodeId="",
                    repetitionNumber=2,
                    repetitionCount=2,
                    text=text,
                    speakingRate=1.125,
                    pauseBeforeMilliseconds=0,
                    pauseAfterMilliseconds=1000,
                ),
            ],
        ),
        AppSettings(),
    )

    assert track.side == "back"
    assert len(track.segments) == 2

    first = track.segments[0]
    second = track.segments[1]

    assert first.text == text
    assert second.text == text
    assert first.sequence == 1
    assert second.sequence == 2
    assert first.segment_id == "cue:repetition:1"
    assert second.segment_id == "cue:repetition:2"
    assert first.cue_id == second.cue_id == "cue"
    assert first.content_node_id == ""
    assert first.repetition_number == 1
    assert second.repetition_number == 2
    assert first.repetition_count == 2
    assert second.repetition_count == 2
    assert first.speaking_rate == Decimal("1.125")
    assert first.pause_before_milliseconds == 650
    assert first.pause_after_milliseconds == 600
    assert second.pause_before_milliseconds == 0
    assert second.pause_after_milliseconds == 1000


def check_empty_track_is_preserved():
    track = resolve_speech_plan(
        create_plan(
            segments=[]
        ),
        AppSettings(),
    )

    assert track.segments == ()


def check_profile_audio_settings_are_resolved():
    settings = AppSettings.from_dict(
        {
            "speech_profiles": {
                "fr": {
                    "voice": "fr-FR-HenriNeural",
                    "rate": "+10%",
                    "volume": "-5%",
                    "pitch": "+2Hz",
                }
            }
        }
    )

    track = resolve_speech_plan(
        create_plan(
            segments=[
                create_segment(
                    speakingRate=1.1
                )
            ]
        ),
        settings,
    )

    segment = track.segments[0]

    assert segment.voice == "fr-FR-HenriNeural"
    assert segment.edge_rate == "+21%"
    assert segment.volume == "-5%"
    assert segment.pitch == "+2Hz"


def check_edge_rate_parsing():
    assert (
        parse_edge_rate_multiplier(
            "+0%"
        )
        == Decimal("1")
    )

    assert (
        parse_edge_rate_multiplier(
            "+10%"
        )
        == Decimal("1.1")
    )

    assert (
        parse_edge_rate_multiplier(
            "-10%"
        )
        == Decimal("0.9")
    )

    assert (
        parse_edge_rate_multiplier(
            "+125%"
        )
        == Decimal("2.25")
    )


def check_edge_rate_composition():
    examples = (
        (
            "+0%",
            "1.10",
            "+10%",
        ),
        (
            "+10%",
            "1.10",
            "+21%",
        ),
        (
            "-10%",
            "1.10",
            "-1%",
        ),
        (
            "+0%",
            "1.125",
            "+13%",
        ),
        (
            "+0%",
            "0.95",
            "-5%",
        ),
        (
            "-25%",
            "2",
            "+50%",
        ),
    )

    for base_rate, multiplier, expected in examples:
        assert (
            compose_edge_rate(
                base_rate,
                Decimal(
                    multiplier
                ),
            )
            == expected
        )


def check_invalid_edge_rates():
    for value in (
        "0%",
        "10%",
        "+1.5%",
        "+10",
        "fast",
        "",
        None,
        10,
        "-100%",
        "-101%",
    ):
        expect_processing_error(
            lambda value=value: (
                parse_edge_rate_multiplier(
                    value
                )
            )
        )


def check_invalid_segment_multipliers():
    for value in (
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("Infinity"),
        1,
        1.0,
        True,
        "1",
        None,
    ):
        expect_processing_error(
            lambda value=value: compose_edge_rate(
                "+0%",
                value,
            )
        )


def check_invalid_model_inputs():
    expect_processing_error(
        lambda: resolve_speech_plan(
            None,
            AppSettings(),
        )
    )

    expect_processing_error(
        lambda: resolve_speech_plan(
            create_plan(),
            None,
        )
    )


def run():
    checks = [
        check_locale_profile_resolution,
        check_known_logical_aliases,
        check_direct_profile_key,
        check_und_requires_logical_profile,
        check_unknown_or_mismatched_profile_fails,
        check_unsupported_locale_fails,
        check_missing_anki_profile_fails,
        check_authoritative_schedule_is_preserved,
        check_empty_track_is_preserved,
        check_profile_audio_settings_are_resolved,
        check_edge_rate_parsing,
        check_edge_rate_composition,
        check_invalid_edge_rates,
        check_invalid_segment_multipliers,
        check_invalid_model_inputs,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
