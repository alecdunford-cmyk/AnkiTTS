from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json

from speech_plan import (
    PauseSpec,
    SpeechPlanPair,
    SpeechPlanPreset,
    SpeechPlanValidationError,
    VALID_ROLES,
    parse_speech_plan,
)


def create_segment(
    **overrides,
):
    segment = {
        "sequence": 1,
        "segmentId": "back-gloss:repetition:1",
        "cueId": "back-gloss",
        "contentNodeId": "entry:phare:gloss",
        "repetitionNumber": 1,
        "repetitionCount": 1,
        "text": "the lighthouse",
        "language": "en-US",
        "voiceProfileId": "",
        "speakingRate": 1.0,
        "pauseBeforeMilliseconds": 0,
        "pauseAfterMilliseconds": 0,
        "role": "gloss",
        "voiceRole": "content",
    }

    segment.update(
        overrides
    )

    return segment


def create_plan_data(
    segments=None,
    **overrides,
):
    plan = {
        "schemaVersion": 2,
        "side": "back",
        "preset": {
            "id": "deep-entry-study",
            "version": 11,
        },
        "tempoProfile": "deep-entry-study",
        "segments": (
            [create_segment()]
            if segments is None
            else segments
        ),
    }

    plan.update(
        overrides
    )

    return plan


def parse(
    data,
    side="back",
):
    return parse_speech_plan(
        json.dumps(
            data
        ),
        side,
    )


def expect_error(
    data,
    fragment,
):
    try:
        parse(
            data
        )

    except SpeechPlanValidationError as error:
        assert fragment in str(
            error
        ), f"{fragment!r} not in {error}"

        return

    raise AssertionError(
        f"Invalid v2 plan was accepted (wanted {fragment!r})."
    )


def check_minimal_plan_with_only_v1_pauses_is_valid():
    plan = parse(
        create_plan_data(
            segments=[
                create_segment(
                    pauseAfterMilliseconds=500,
                )
            ]
        )
    )

    assert plan.schema_version == 2
    assert plan.preset == SpeechPlanPreset(
        "deep-entry-study",
        11,
    )
    assert plan.tempo_profile == "deep-entry-study"

    segment = plan.segments[0]

    assert segment.role == "gloss"
    assert segment.voice_role == "content"
    assert segment.pause_before is None
    assert segment.pause_after is None
    assert segment.pause_after_milliseconds == 500
    assert segment.earcon_before is None
    assert segment.earcon_after is None
    assert segment.pair is None
    assert segment.spoken is True


def check_every_optional_field_parses():
    plan = parse(
        create_plan_data(
            segments=[
                create_segment(
                    pauseBefore={
                        "kind": "boundary",
                    },
                    pauseAfter={
                        "kind": "proportional",
                        "scale": 1.5,
                    },
                    earconBefore="sectionBoundary",
                    earconAfter="directionFlip",
                    pair={
                        "id": "pair-1",
                        "position": "source",
                    },
                    spoken=False,
                ),
                create_segment(
                    sequence=2,
                    segmentId="second",
                    pauseBefore={
                        "kind": "none",
                    },
                    pauseAfter={
                        "kind": "fixed",
                        "milliseconds": 900,
                    },
                    earconBefore="answerStart",
                ),
            ]
        )
    )

    first, second = plan.segments

    assert first.pause_before == PauseSpec(
        "boundary"
    )
    assert first.pause_after == PauseSpec(
        "proportional",
        scale=Decimal(
            "1.5"
        ),
    )
    assert first.earcon_before == "sectionBoundary"
    assert first.earcon_after == "directionFlip"
    assert first.pair == SpeechPlanPair(
        "pair-1",
        "source",
    )
    assert first.spoken is False
    assert second.pause_before == PauseSpec(
        "none"
    )
    assert second.pause_after == PauseSpec(
        "fixed",
        milliseconds=900,
    )
    assert second.earcon_before == "answerStart"


def check_all_roles_and_voice_roles_are_accepted():
    for role in VALID_ROLES:
        for voice_role in (
            "content",
            "label",
        ):
            segment = parse(
                create_plan_data(
                    segments=[
                        create_segment(
                            role=role,
                            voiceRole=voice_role,
                        )
                    ]
                )
            ).segments[0]

            assert segment.role == role
            assert segment.voice_role == voice_role


def check_role_and_voice_role_are_validated():
    expect_error(
        create_plan_data(
            segments=[
                create_segment(
                    role="narrator",
                )
            ]
        ),
        "segments[0].role",
    )

    expect_error(
        create_plan_data(
            segments=[
                create_segment(
                    voiceRole="Label",
                )
            ]
        ),
        "segments[0].voiceRole",
    )

    for missing in (
        "role",
        "voiceRole",
    ):
        segment = create_segment()
        del segment[missing]

        expect_error(
            create_plan_data(
                segments=[
                    segment
                ]
            ),
            missing,
        )


def check_unknown_keys_are_rejected():
    expect_error(
        create_plan_data(
            segments=[
                create_segment(
                    voice="fr-FR-DeniseNeural",
                )
            ]
        ),
        "unexpected field",
    )

    expect_error(
        create_plan_data(
            engine="edge",
        ),
        "unexpected field",
    )

    expect_error(
        create_plan_data(
            preset={
                "id": "x",
                "version": 1,
                "extra": 1,
            },
        ),
        "preset",
    )

    expect_error(
        create_plan_data(
            segments=[
                create_segment(
                    pair={
                        "id": "p",
                        "position": "source",
                        "side": "x",
                    },
                )
            ]
        ),
        "pair",
    )


def check_plan_level_fields_are_required_and_typed():
    for missing in (
        "preset",
        "tempoProfile",
    ):
        plan = create_plan_data()
        del plan[missing]

        expect_error(
            plan,
            missing,
        )

    expect_error(
        create_plan_data(
            tempoProfile="",
        ),
        "tempoProfile",
    )

    expect_error(
        create_plan_data(
            preset={
                "id": "",
                "version": 1,
            },
        ),
        "preset.id",
    )

    expect_error(
        create_plan_data(
            preset={
                "id": "x",
                "version": 0,
            },
        ),
        "preset.version",
    )


def check_pause_validation():
    bad_pauses = (
        (
            {},
            "kind",
        ),
        (
            {
                "kind": "long",
            },
            "kind",
        ),
        (
            {
                "kind": "fixed",
            },
            "milliseconds",
        ),
        (
            {
                "kind": "fixed",
                "milliseconds": -1,
            },
            "milliseconds",
        ),
        (
            {
                "kind": "fixed",
                "milliseconds": 1.5,
            },
            "milliseconds",
        ),
        (
            {
                "kind": "proportional",
            },
            "scale",
        ),
        (
            {
                "kind": "proportional",
                "scale": 0,
            },
            "scale",
        ),
        (
            {
                "kind": "proportional",
                "scale": -1,
            },
            "scale",
        ),
        (
            {
                "kind": "proportional",
                "scale": 1.0,
                "milliseconds": 100,
            },
            "unexpected",
        ),
        (
            {
                "kind": "boundary",
                "milliseconds": 100,
            },
            "unexpected",
        ),
        (
            {
                "kind": "none",
                "scale": 1.0,
            },
            "unexpected",
        ),
        (
            "fixed",
            "object",
        ),
    )

    for field_name in (
        "pauseBefore",
        "pauseAfter",
    ):
        for pause, fragment in bad_pauses:
            expect_error(
                create_plan_data(
                    segments=[
                        create_segment(
                            **{
                                field_name: pause,
                            }
                        )
                    ]
                ),
                fragment,
            )


def check_earcon_validation():
    for field_name in (
        "earconBefore",
        "earconAfter",
    ):
        for value in (
            "ding",
            "",
            None,
            1,
        ):
            expect_error(
                create_plan_data(
                    segments=[
                        create_segment(
                            **{
                                field_name: value,
                            }
                        )
                    ]
                ),
                field_name,
            )


def check_pair_position_present_iff_id():
    for pair, fragment in (
        (
            {
                "id": "pair-1",
            },
            "position",
        ),
        (
            {
                "position": "source",
            },
            "id",
        ),
        (
            {
                "id": "",
                "position": "source",
            },
            "pair.id",
        ),
        (
            {
                "id": "pair-1",
                "position": "middle",
            },
            "pair.position",
        ),
        (
            "pair-1",
            "object",
        ),
    ):
        expect_error(
            create_plan_data(
                segments=[
                    create_segment(
                        pair=pair,
                    )
                ]
            ),
            fragment,
        )


def check_spoken_must_be_boolean():
    expect_error(
        create_plan_data(
            segments=[
                create_segment(
                    spoken="false",
                )
            ]
        ),
        "spoken",
    )


def check_v1_rules_still_apply_inside_v2():
    # All twelve v1 fields stay required (P3: v2 removes none of them).
    segment = create_segment()
    del segment["pauseAfterMilliseconds"]

    expect_error(
        create_plan_data(
            segments=[
                segment
            ]
        ),
        "pauseAfterMilliseconds",
    )

    expect_error(
        create_plan_data(
            segments=[
                create_segment(
                    sequence=2,
                )
            ]
        ),
        "sequence",
    )

    expect_error(
        create_plan_data(
            segments=[
                create_segment(),
                create_segment(
                    sequence=2,
                ),
            ]
        ),
        "duplicates",
    )

    expect_error(
        create_plan_data(
            side="front",
        ),
        "side mismatch",
    )


def check_v2_fields_are_rejected_in_a_v1_plan():
    for extra in (
        {
            "role": "gloss",
        },
        {
            "voiceRole": "content",
        },
        {
            "pauseAfter": {
                "kind": "none",
            },
        },
        {
            "earconBefore": "answerStart",
        },
    ):
        segment = {
            key: value
            for key, value in create_segment().items()
            if key
            not in (
                "role",
                "voiceRole",
            )
        }

        segment.update(
            extra
        )

        expect_error(
            {
                "schemaVersion": 1,
                "side": "back",
                "segments": [
                    segment
                ],
            },
            "unexpected field",
        )

    plan = create_plan_data(
        schemaVersion=1,
    )

    plan["segments"] = [
        {
            key: value
            for key, value in deepcopy(
                create_segment()
            ).items()
            if key
            not in (
                "role",
                "voiceRole",
            )
        }
    ]

    expect_error(
        plan,
        "unexpected field",
    )


def check_v1_plan_parses_to_v1_defaults():
    plan = parse(
        {
            "schemaVersion": 1,
            "side": "back",
            "segments": [
                {
                    key: value
                    for key, value in create_segment().items()
                    if key
                    not in (
                        "role",
                        "voiceRole",
                    )
                }
            ],
        }
    )

    assert plan.schema_version == 1
    assert plan.preset is None
    assert plan.tempo_profile is None

    segment = plan.segments[0]

    assert segment.role is None
    assert segment.voice_role is None
    assert segment.spoken is True


def check_other_schema_versions_stay_unsupported():
    for version in (
        0,
        3,
        True,
        2.0,
        "2",
    ):
        expect_error(
            create_plan_data(
                schemaVersion=version,
            ),
            "",
        )


def run():
    checks = [
        check_minimal_plan_with_only_v1_pauses_is_valid,
        check_every_optional_field_parses,
        check_all_roles_and_voice_roles_are_accepted,
        check_role_and_voice_role_are_validated,
        check_unknown_keys_are_rejected,
        check_plan_level_fields_are_required_and_typed,
        check_pause_validation,
        check_earcon_validation,
        check_pair_position_present_iff_id,
        check_spoken_must_be_boolean,
        check_v1_rules_still_apply_inside_v2,
        check_v2_fields_are_rejected_in_a_v1_plan,
        check_v1_plan_parses_to_v1_defaults,
        check_other_schema_versions_stay_unsupported,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
