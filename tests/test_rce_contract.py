from __future__ import annotations

from copy import deepcopy
import json

import batch_processor
from batch_processor import process_notes
from note_mapper import (
    create_job_from_note,
    is_processable_note,
    iter_processed_audio_outputs,
    write_audio_fields,
)
from rce_contract import (
    RCE_CARD_ID_FIELD,
    RCE_FIELD_NAMES,
    RCE_JOB_TYPE,
    RceContractError,
    create_rce_speech_plan_job,
    get_missing_rce_fields,
    has_complete_rce_contract,
    is_apparent_rce_note,
)
from settings import AppSettings


def create_segment(
    side,
):
    return {
        "sequence": 1,
        "segmentId": f"{side}-cue:repetition:1",
        "cueId": f"{side}-cue",
        "contentNodeId": f"{side}-content",
        "repetitionNumber": 1,
        "repetitionCount": 1,
        "text": (
            "faire"
            if side == "front"
            else "to make"
        ),
        "language": (
            "fr-FR"
            if side == "front"
            else "en-US"
        ),
        "voiceProfileId": "",
        "speakingRate": 1.0,
        "pauseBeforeMilliseconds": 0,
        "pauseAfterMilliseconds": 500,
    }


def create_speech_plan(
    side,
):
    return json.dumps(
        {
            "schemaVersion": 1,
            "side": side,
            "segments": [
                create_segment(
                    side
                )
            ],
        },
        ensure_ascii=False,
    )


def create_rce_note():
    return {
        "Front": "<b>faire</b>",
        "Back": "to make",
        "Front Speech Plan": (
            create_speech_plan(
                "front"
            )
        ),
        "Back Speech Plan": (
            create_speech_plan(
                "back"
            )
        ),
        "Front Audio": "",
        "Back Audio": "",
        "Playback Plan": (
            '{"schemaVersion":1}'
        ),
        "Blueprint": "deep-entry-study@3",
        "Theme": "rce-study-v1",
        "RCE Card ID": "card-123",
    }


def expect_contract_error(
    note,
):
    try:
        create_rce_speech_plan_job(
            note
        )

    except RceContractError:
        return

    raise AssertionError(
        "Invalid RCE Card contract was accepted."
    )


def check_exact_contract_fields():
    assert RCE_FIELD_NAMES == (
        "Front",
        "Back",
        "Front Speech Plan",
        "Back Speech Plan",
        "Front Audio",
        "Back Audio",
        "Playback Plan",
        "Blueprint",
        "Theme",
        "RCE Card ID",
    )


def check_marker_detection():
    assert is_apparent_rce_note(
        {
            "Front Speech Plan": "{}",
        }
    )

    assert is_apparent_rce_note(
        {
            RCE_CARD_ID_FIELD: "card",
        }
    )

    assert not is_apparent_rce_note(
        {
            "Front": "front",
            "Back": "back",
            "Front Audio": "",
            "Back Audio": "",
            "Theme": "ordinary",
        }
    )


def check_complete_contract_detection():
    note = create_rce_note()

    assert has_complete_rce_contract(
        note
    )

    assert get_missing_rce_fields(
        note
    ) == []

    del note[
        "Back Speech Plan"
    ]

    assert not has_complete_rce_contract(
        note
    )

    assert get_missing_rce_fields(
        note
    ) == [
        "Back Speech Plan",
    ]


def check_structured_job_contract():
    job = create_rce_speech_plan_job(
        create_rce_note()
    )

    assert job[
        "job_type"
    ] == RCE_JOB_TYPE

    assert job[
        "rce_card_id"
    ] == "card-123"

    assert job[
        "speech_plans"
    ][
        "front"
    ].side == "front"

    assert job[
        "speech_plans"
    ][
        "back"
    ].side == "back"

    assert job[
        "audio_fields"
    ] == {
        "front": "Front Audio",
        "back": "Back Audio",
    }


def check_structured_precedence():
    settings = AppSettings()
    note = create_rce_note()

    job = create_job_from_note(
        note,
        settings,
    )

    assert job[
        "job_type"
    ] == RCE_JOB_TYPE
    assert "fields" not in job


def check_structured_compatibility_ignores_generic_mapping():
    settings = AppSettings()
    settings.field_mapping = {
        "question": {
            "text": "Question",
            "audio": "Question Audio",
            "speech_profile": "fr",
        }
    }

    assert is_processable_note(
        create_rce_note(),
        settings,
    )

    assert not is_processable_note(
        {
            "Front": "generic",
            "Back": "note",
        },
        settings,
    )


def check_generic_job_is_unchanged():
    settings = AppSettings()
    note = {
        "Front": "bonjour",
        "Back": "hello",
        "Front Audio": "",
        "Back Audio": "",
    }

    job = create_job_from_note(
        note,
        settings,
    )

    assert job == {
        "fields": {
            "front": {
                "text": "bonjour",
                "speech_profile": "front",
                "enabled": True,
            },
            "back": {
                "text": "hello",
                "speech_profile": "auto",
                "enabled": True,
            },
        }
    }


def check_incomplete_apparent_contract_fails():
    note = create_rce_note()

    del note[
        "Back Speech Plan"
    ]

    expect_contract_error(
        note
    )

    try:
        create_job_from_note(
            note,
            AppSettings(),
        )

    except RceContractError:
        return

    raise AssertionError(
        "Incomplete apparent RCE Card fell back to generic mapping."
    )


def check_invalid_card_id():
    for value in (
        "",
        "   ",
        None,
        1,
    ):
        note = create_rce_note()
        note[
            "RCE Card ID"
        ] = value

        expect_contract_error(
            note
        )


def check_invalid_speech_plans():
    invalid_front = create_rce_note()
    invalid_front[
        "Front Speech Plan"
    ] = "{not-json"

    wrong_back_side = create_rce_note()
    wrong_back_side[
        "Back Speech Plan"
    ] = create_speech_plan(
        "front"
    )

    expect_contract_error(
        invalid_front
    )

    expect_contract_error(
        wrong_back_side
    )


def check_note_is_not_mutated():
    note = create_rce_note()
    original = deepcopy(
        note
    )

    create_rce_speech_plan_job(
        note
    )

    assert note == original


def check_batch_structured_dispatch():
    job = create_rce_speech_plan_job(
        create_rce_note()
    )

    original_processor = (
        batch_processor.process_structured_job
    )

    calls = []

    def fake_process_structured_job(
        received_job,
        settings,
    ):
        calls.append(
            (
                received_job,
                settings,
            )
        )

        return {
            "job_type": RCE_JOB_TYPE,
            "rce_card_id": "card-123",
            "audio_fields": {
                "front": "Front Audio",
                "back": "Back Audio",
            },
            "front": "front.mp3",
            "front_processed": True,
            "back": "back.mp3",
            "back_processed": True,
            "statistics": {
                "generated": 2,
                "cached": 0,
                "skipped": 0,
            },
        }

    try:
        batch_processor.process_structured_job = (
            fake_process_structured_job
        )

        settings = AppSettings()

        result = process_notes(
            [
                job
            ],
            settings,
        )

        assert calls == [
            (
                job,
                settings,
            )
        ]

        assert result[
            "processed"
        ] == 1

        assert result[
            "statistics"
        ] == {
            "generated": 2,
            "cached": 0,
            "skipped": 0,
        }

        assert result[
            "results"
        ][0][
            "job_type"
        ] == RCE_JOB_TYPE

    finally:
        batch_processor.process_structured_job = (
            original_processor
        )


def check_structured_audio_publication():
    settings = AppSettings()
    settings.field_mapping = {
        "question": {
            "text": "Question",
            "audio": "Question Audio",
            "speech_profile": "fr",
        }
    }

    note = create_rce_note()

    audio_files = {
        "job_type": RCE_JOB_TYPE,
        "audio_fields": {
            "front": "Front Audio",
            "back": "Back Audio",
        },
        "front": "rce-front.mp3",
        "front_processed": True,
        "back": None,
        "back_processed": True,
    }

    outputs = list(
        iter_processed_audio_outputs(
            audio_files,
            settings,
        )
    )

    assert outputs == [
        (
            "front",
            "Front Audio",
            "rce-front.mp3",
        ),
        (
            "back",
            "Back Audio",
            None,
        ),
    ]

    write_audio_fields(
        note,
        audio_files,
        settings,
    )

    assert note[
        "Front Audio"
    ] == "[sound:rce-front.mp3]"

    assert note[
        "Back Audio"
    ] == ""


def check_generic_audio_publication_is_unchanged():
    settings = AppSettings()
    settings.field_mapping = {
        "question": {
            "text": "Question",
            "audio": "Question Audio",
            "speech_profile": "fr",
        },
        "answer": {
            "text": "Answer",
            "audio": "Answer Audio",
            "speech_profile": "en",
        },
    }

    note = {
        "Question": "bonjour",
        "Question Audio": "",
        "Answer": "hello",
        "Answer Audio": "[sound:existing.mp3]",
    }

    audio_files = {
        "question": "question.mp3",
        "question_processed": True,
        "answer": None,
        "answer_processed": False,
    }

    write_audio_fields(
        note,
        audio_files,
        settings,
    )

    assert note[
        "Question Audio"
    ] == "[sound:question.mp3]"

    assert note[
        "Answer Audio"
    ] == "[sound:existing.mp3]"


def check_generic_batch_dispatch_is_unchanged():
    result = process_notes(
        [
            {
                "fields": {
                    "front": {
                        "text": "bonjour",
                        "speech_profile": "front",
                        "enabled": False,
                    }
                }
            }
        ],
        AppSettings(),
    )

    assert result[
        "processed"
    ] == 1

    assert result[
        "results"
    ][0][
        "front"
    ] is None

    assert result[
        "results"
    ][0][
        "front_processed"
    ] is False


def run():
    checks = [
        check_exact_contract_fields,
        check_marker_detection,
        check_complete_contract_detection,
        check_structured_job_contract,
        check_structured_precedence,
        check_structured_compatibility_ignores_generic_mapping,
        check_generic_job_is_unchanged,
        check_incomplete_apparent_contract_fails,
        check_invalid_card_id,
        check_invalid_speech_plans,
        check_note_is_not_mutated,
        check_batch_structured_dispatch,
        check_structured_audio_publication,
        check_generic_audio_publication_is_unchanged,
        check_generic_batch_dispatch_is_unchanged,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
