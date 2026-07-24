from __future__ import annotations

from speech_plan import (
    SpeechPlanValidationError,
    parse_speech_plan,
)


RCE_JOB_TYPE = "rce_speech_plan"

RCE_NOTE_TYPE_NAME = "RCE Card"

FRONT_FIELD = "Front"
BACK_FIELD = "Back"
FRONT_SPEECH_PLAN_FIELD = "Front Speech Plan"
BACK_SPEECH_PLAN_FIELD = "Back Speech Plan"
FRONT_AUDIO_FIELD = "Front Audio"
BACK_AUDIO_FIELD = "Back Audio"
PLAYBACK_PLAN_FIELD = "Playback Plan"
BLUEPRINT_FIELD = "Blueprint"
THEME_FIELD = "Theme"
RCE_CARD_ID_FIELD = "RCE Card ID"

RCE_FIELD_NAMES = (
    FRONT_FIELD,
    BACK_FIELD,
    FRONT_SPEECH_PLAN_FIELD,
    BACK_SPEECH_PLAN_FIELD,
    FRONT_AUDIO_FIELD,
    BACK_AUDIO_FIELD,
    PLAYBACK_PLAN_FIELD,
    BLUEPRINT_FIELD,
    THEME_FIELD,
    RCE_CARD_ID_FIELD,
)

RCE_MARKER_FIELDS = (
    FRONT_SPEECH_PLAN_FIELD,
    BACK_SPEECH_PLAN_FIELD,
    PLAYBACK_PLAN_FIELD,
    RCE_CARD_ID_FIELD,
)


class RceContractError(
    ValueError
):
    """Raised when an apparent RCE note violates the RCE Card contract."""


def is_apparent_rce_note(
    note,
):
    """
    Return whether a note contains an RCE-specific contract marker.

    Generic Front, Back, audio, Blueprint, and Theme field names are not
    sufficient on their own because unrelated note types may use them.
    """

    return any(
        field_name in note
        for field_name in RCE_MARKER_FIELDS
    )


def has_complete_rce_contract(
    note,
):
    """Return whether a note contains every required RCE Card field."""

    return not get_missing_rce_fields(
        note
    )


def get_missing_rce_fields(
    note,
):
    """Return required RCE Card fields absent from a note."""

    return [
        field_name
        for field_name in RCE_FIELD_NAMES
        if field_name not in note
    ]


def create_rce_speech_plan_job(
    note,
):
    """Create one validated structured job from a complete RCE Card note."""

    missing_fields = get_missing_rce_fields(
        note
    )

    if missing_fields:
        formatted_fields = "\n".join(
            missing_fields
        )

        raise RceContractError(
            "The apparent RCE Card note is missing the following "
            f"required fields:\n\n{formatted_fields}"
        )

    rce_card_id = note[
        RCE_CARD_ID_FIELD
    ]

    if (
        not isinstance(
            rce_card_id,
            str,
        )
        or not rce_card_id.strip()
    ):
        raise RceContractError(
            "RCE Card ID must be a nonempty string."
        )

    try:
        front_speech_plan = parse_speech_plan(
            note[
                FRONT_SPEECH_PLAN_FIELD
            ],
            "front",
        )

        back_speech_plan = parse_speech_plan(
            note[
                BACK_SPEECH_PLAN_FIELD
            ],
            "back",
        )

    except SpeechPlanValidationError as error:
        raise RceContractError(
            f"Invalid RCE Card speech plan: {error}"
        ) from error

    return {
        "job_type": RCE_JOB_TYPE,
        "rce_card_id": (
            rce_card_id.strip()
        ),
        "speech_plans": {
            "front": front_speech_plan,
            "back": back_speech_plan,
        },
        "audio_fields": {
            "front": FRONT_AUDIO_FIELD,
            "back": BACK_AUDIO_FIELD,
        },
    }
