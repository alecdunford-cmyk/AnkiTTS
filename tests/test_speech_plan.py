from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json

from speech_plan import (
    SpeechPlanValidationError,
    parse_speech_plan,
)


DEFAULT_SEGMENTS = object()


def create_segment(
    **overrides,
):
    segment = {
        "sequence": 1,
        "segmentId": "front-headword:repetition:1",
        "cueId": "front-headword",
        "contentNodeId": "entry:faire",
        "repetitionNumber": 1,
        "repetitionCount": 1,
        "text": "faire",
        "language": "fr-FR",
        "voiceProfileId": "",
        "speakingRate": 1.0,
        "pauseBeforeMilliseconds": 0,
        "pauseAfterMilliseconds": 500,
    }

    segment.update(
        overrides
    )

    return segment


def create_plan_data(
    side="front",
    segments=DEFAULT_SEGMENTS,
    **overrides,
):
    if segments is DEFAULT_SEGMENTS:
        segments = [
            create_segment()
        ]

    plan = {
        "schemaVersion": 1,
        "side": side,
        "segments": segments,
    }

    plan.update(
        overrides
    )

    return plan


def serialize(
    plan,
):
    return json.dumps(
        plan,
        ensure_ascii=False,
    )


def expect_error(
    payload,
    expected_side="front",
):
    try:
        parse_speech_plan(
            payload,
            expected_side,
        )

    except SpeechPlanValidationError:
        return

    raise AssertionError(
        "Invalid speech plan was accepted."
    )


def check_valid_front_plan():
    plan = parse_speech_plan(
        serialize(
            create_plan_data()
        ),
        "front",
    )

    assert plan.schema_version == 1
    assert plan.side == "front"
    assert len(plan.segments) == 1

    segment = plan.segments[0]

    assert segment.sequence == 1
    assert segment.segment_id == "front-headword:repetition:1"
    assert segment.cue_id == "front-headword"
    assert segment.content_node_id == "entry:faire"
    assert segment.repetition_number == 1
    assert segment.repetition_count == 1
    assert segment.text == "faire"
    assert segment.language == "fr-FR"
    assert segment.voice_profile_id == ""
    assert segment.speaking_rate == Decimal("1.0")
    assert segment.pause_before_milliseconds == 0
    assert segment.pause_after_milliseconds == 500


def check_valid_back_plan():
    plan = parse_speech_plan(
        serialize(
            create_plan_data(
                side="back",
                segments=[
                    create_segment(
                        segmentId="back-translation:repetition:1",
                        cueId="back-translation",
                        contentNodeId="translation:make",
                        text="to make",
                        language="en-US",
                    )
                ],
            )
        ),
        "back",
    )

    assert plan.side == "back"
    assert plan.segments[0].text == "to make"
    assert plan.segments[0].language == "en-US"


def check_valid_empty_track():
    plan = parse_speech_plan(
        serialize(
            create_plan_data(
                segments=[]
            )
        ),
        "front",
    )

    assert plan.segments == ()


def check_unicode_and_authoritative_text_are_preserved():
    text = "  écouter — 日本語を勉強する  "

    plan = parse_speech_plan(
        serialize(
            create_plan_data(
                segments=[
                    create_segment(
                        text=text,
                        language="ja-JP",
                    )
                ]
            )
        ),
        "front",
    )

    assert plan.segments[0].text == text
    assert plan.segments[0].language == "ja-JP"


def check_empty_profile_and_und_are_preserved():
    plan = parse_speech_plan(
        serialize(
            create_plan_data(
                segments=[
                    create_segment(
                        contentNodeId="",
                        language="und",
                        voiceProfileId="",
                    )
                ]
            )
        ),
        "front",
    )

    segment = plan.segments[0]

    assert segment.content_node_id == ""
    assert segment.language == "und"
    assert segment.voice_profile_id == ""


def check_repetitions_and_decimal_rate():
    plan = parse_speech_plan(
        serialize(
            create_plan_data(
                segments=[
                    create_segment(
                        sequence=1,
                        segmentId="cue:repetition:1",
                        cueId="cue",
                        repetitionNumber=1,
                        repetitionCount=2,
                        speakingRate=1.125,
                    ),
                    create_segment(
                        sequence=2,
                        segmentId="cue:repetition:2",
                        cueId="cue",
                        repetitionNumber=2,
                        repetitionCount=2,
                        speakingRate=1.125,
                    ),
                ]
            )
        ),
        "front",
    )

    assert len(plan.segments) == 2
    assert (
        plan.segments[0].speaking_rate
        == Decimal("1.125")
    )
    assert plan.segments[1].repetition_number == 2


def check_malformed_json():
    expect_error(
        "{not-json"
    )


def check_payload_and_expected_side_types():
    expect_error(
        [],
    )

    expect_error(
        serialize(
            create_plan_data()
        ),
        expected_side="Front",
    )


def check_top_level_must_be_object():
    expect_error(
        "[]"
    )


def check_plan_fields_are_strict():
    missing = create_plan_data()
    del missing[
        "schemaVersion"
    ]

    unexpected = create_plan_data(
        provider="edge"
    )

    expect_error(
        serialize(
            missing
        )
    )

    expect_error(
        serialize(
            unexpected
        )
    )


def check_schema_version():
    for value in (
        2,
        True,
        1.0,
        "1",
    ):
        expect_error(
            serialize(
                create_plan_data(
                    schemaVersion=value
                )
            )
        )


def check_side_validation():
    for value in (
        "source",
        "Front",
        "",
        None,
    ):
        expect_error(
            serialize(
                create_plan_data(
                    side=value
                )
            )
        )

    expect_error(
        serialize(
            create_plan_data(
                side="back"
            )
        ),
        expected_side="front",
    )


def check_segments_must_be_array():
    for value in (
        {},
        "segments",
        None,
    ):
        expect_error(
            serialize(
                create_plan_data(
                    segments=value
                )
            )
        )


def check_segment_fields_are_strict():
    missing = create_segment()
    del missing[
        "cueId"
    ]

    unexpected = create_segment(
        provider="edge"
    )

    expect_error(
        serialize(
            create_plan_data(
                segments=[
                    missing
                ]
            )
        )
    )

    expect_error(
        serialize(
            create_plan_data(
                segments=[
                    unexpected
                ]
            )
        )
    )


def check_identifiers():
    invalid_values = (
        ("segmentId", ""),
        ("segmentId", "   "),
        ("segmentId", None),
        ("cueId", ""),
        ("cueId", "   "),
        ("cueId", None),
    )

    for field_name, value in invalid_values:
        expect_error(
            serialize(
                create_plan_data(
                    segments=[
                        create_segment(
                            **{
                                field_name: value,
                            }
                        )
                    ]
                )
            )
        )


def check_duplicate_segment_id():
    expect_error(
        serialize(
            create_plan_data(
                segments=[
                    create_segment(
                        sequence=1,
                        segmentId="duplicate",
                    ),
                    create_segment(
                        sequence=2,
                        segmentId="duplicate",
                    ),
                ]
            )
        )
    )


def check_required_text_and_language():
    for field_name in (
        "text",
        "language",
    ):
        for value in (
            "",
            "   ",
            None,
        ):
            expect_error(
                serialize(
                    create_plan_data(
                        segments=[
                            create_segment(
                                **{
                                    field_name: value,
                                }
                            )
                        ]
                    )
                )
            )


def check_optional_string_types():
    for field_name in (
        "contentNodeId",
        "voiceProfileId",
    ):
        for value in (
            None,
            1,
            True,
        ):
            expect_error(
                serialize(
                    create_plan_data(
                        segments=[
                            create_segment(
                                **{
                                    field_name: value,
                                }
                            )
                        ]
                    )
                )
            )


def check_speaking_rate():
    for value in (
        0,
        -1,
        True,
        "1.0",
        None,
        float(
            "nan"
        ),
        float(
            "inf"
        ),
    ):
        expect_error(
            serialize(
                create_plan_data(
                    segments=[
                        create_segment(
                            speakingRate=value
                        )
                    ]
                )
            )
        )


def check_pause_values():
    fields = (
        "pauseBeforeMilliseconds",
        "pauseAfterMilliseconds",
    )

    for field_name in fields:
        for value in (
            -1,
            1.5,
            True,
            "100",
        ):
            expect_error(
                serialize(
                    create_plan_data(
                        segments=[
                            create_segment(
                                **{
                                    field_name: value,
                                }
                            )
                        ]
                    )
                )
            )


def check_repetition_values():
    invalid_values = (
        ("repetitionNumber", 0),
        ("repetitionNumber", -1),
        ("repetitionNumber", 1.5),
        ("repetitionNumber", True),
        ("repetitionCount", 0),
        ("repetitionCount", -1),
        ("repetitionCount", 1.5),
        ("repetitionCount", True),
    )

    for field_name, value in invalid_values:
        expect_error(
            serialize(
                create_plan_data(
                    segments=[
                        create_segment(
                            **{
                                field_name: value,
                            }
                        )
                    ]
                )
            )
        )

    expect_error(
        serialize(
            create_plan_data(
                segments=[
                    create_segment(
                        repetitionNumber=2,
                        repetitionCount=1,
                    )
                ]
            )
        )
    )


def check_sequence_values():
    for value in (
        0,
        -1,
        1.5,
        True,
        "1",
    ):
        expect_error(
            serialize(
                create_plan_data(
                    segments=[
                        create_segment(
                            sequence=value
                        )
                    ]
                )
            )
        )


def check_sequence_is_contiguous():
    expect_error(
        serialize(
            create_plan_data(
                segments=[
                    create_segment(
                        sequence=1,
                        segmentId="first",
                    ),
                    create_segment(
                        sequence=3,
                        segmentId="third",
                    ),
                ]
            )
        )
    )


def check_duplicate_json_properties():
    payload = serialize(
        create_plan_data(
            segments=[]
        )
    )

    payload = payload.replace(
        '"schemaVersion": 1',
        '"schemaVersion": 1, "schemaVersion": 1',
    )

    expect_error(
        payload
    )


def check_input_is_not_mutated():
    source = create_plan_data()
    original = deepcopy(
        source
    )

    parse_speech_plan(
        serialize(
            source
        ),
        "front",
    )

    assert source == original


def run():
    checks = [
        check_valid_front_plan,
        check_valid_back_plan,
        check_valid_empty_track,
        check_unicode_and_authoritative_text_are_preserved,
        check_empty_profile_and_und_are_preserved,
        check_repetitions_and_decimal_rate,
        check_malformed_json,
        check_payload_and_expected_side_types,
        check_top_level_must_be_object,
        check_plan_fields_are_strict,
        check_schema_version,
        check_side_validation,
        check_segments_must_be_array,
        check_segment_fields_are_strict,
        check_identifiers,
        check_duplicate_segment_id,
        check_required_text_and_language,
        check_optional_string_types,
        check_speaking_rate,
        check_pause_values,
        check_repetition_values,
        check_sequence_values,
        check_sequence_is_contiguous,
        check_duplicate_json_properties,
        check_input_is_not_mutated,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
