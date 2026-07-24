from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


SCHEMA_VERSION = 1
VALID_SIDES = {
    "front",
    "back",
}

PLAN_FIELDS = {
    "schemaVersion",
    "side",
    "segments",
}

SEGMENT_FIELDS = {
    "sequence",
    "segmentId",
    "cueId",
    "contentNodeId",
    "repetitionNumber",
    "repetitionCount",
    "text",
    "language",
    "voiceProfileId",
    "speakingRate",
    "pauseBeforeMilliseconds",
    "pauseAfterMilliseconds",
}


class SpeechPlanValidationError(
    ValueError
):
    """Raised when structured speech-plan JSON violates schema version 1."""


@dataclass(frozen=True)
class SpeechPlanSegment:
    """One authoritative synthesis segment from an RCE speech plan."""

    sequence: int
    segment_id: str
    cue_id: str
    content_node_id: str
    repetition_number: int
    repetition_count: int
    text: str
    language: str
    voice_profile_id: str
    speaking_rate: Decimal
    pause_before_milliseconds: int
    pause_after_milliseconds: int


@dataclass(frozen=True)
class SpeechPlan:
    """One validated, ordered side of an RCE speech schedule."""

    schema_version: int
    side: str
    segments: tuple[
        SpeechPlanSegment,
        ...,
    ]


def parse_speech_plan(
    payload: str,
    expected_side: str,
) -> SpeechPlan:
    """
    Parse and validate one RCE schema-version-1 speech plan.

    Parsing is deliberately independent of Anki, TTS providers,
    language detection, text normalization, and audio processing.
    """

    if not isinstance(
        payload,
        str,
    ):
        raise SpeechPlanValidationError(
            "Speech-plan JSON must be a string."
        )

    _validate_side(
        expected_side,
        "expected_side",
    )

    try:
        data = json.loads(
            payload,
            parse_float=Decimal,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )

    except (
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise SpeechPlanValidationError(
            f"Invalid speech-plan JSON: {error}"
        ) from error

    plan_data = _require_object(
        data,
        "speech plan",
    )

    _require_exact_fields(
        plan_data,
        PLAN_FIELDS,
        "speech plan",
    )

    schema_version = _require_integer(
        plan_data["schemaVersion"],
        "schemaVersion",
    )

    if schema_version != SCHEMA_VERSION:
        raise SpeechPlanValidationError(
            "Unsupported speech-plan schemaVersion: "
            f"{schema_version}."
        )

    side = plan_data["side"]

    _validate_side(
        side,
        "side",
    )

    if side != expected_side:
        raise SpeechPlanValidationError(
            "Speech-plan side mismatch: "
            f'expected "{expected_side}", received "{side}".'
        )

    segment_data = plan_data[
        "segments"
    ]

    if not isinstance(
        segment_data,
        list,
    ):
        raise SpeechPlanValidationError(
            "segments must be an array."
        )

    segments = []
    segment_ids = set()

    for index, raw_segment in enumerate(
        segment_data
    ):
        path = f"segments[{index}]"

        segment = _parse_segment(
            raw_segment,
            path,
        )

        expected_sequence = index + 1

        if (
            segment.sequence
            != expected_sequence
        ):
            raise SpeechPlanValidationError(
                f"{path}.sequence must be "
                f"{expected_sequence}."
            )

        if segment.segment_id in segment_ids:
            raise SpeechPlanValidationError(
                f'{path}.segmentId duplicates "'
                f'{segment.segment_id}".'
            )

        segment_ids.add(
            segment.segment_id
        )

        segments.append(
            segment
        )

    return SpeechPlan(
        schema_version=schema_version,
        side=side,
        segments=tuple(
            segments
        ),
    )


def _parse_segment(
    value: Any,
    path: str,
) -> SpeechPlanSegment:
    segment = _require_object(
        value,
        path,
    )

    _require_exact_fields(
        segment,
        SEGMENT_FIELDS,
        path,
    )

    sequence = _require_positive_integer(
        segment["sequence"],
        f"{path}.sequence",
    )

    segment_id = _require_nonempty_string(
        segment["segmentId"],
        f"{path}.segmentId",
    )

    cue_id = _require_nonempty_string(
        segment["cueId"],
        f"{path}.cueId",
    )

    content_node_id = _require_string(
        segment["contentNodeId"],
        f"{path}.contentNodeId",
    )

    repetition_number = _require_positive_integer(
        segment["repetitionNumber"],
        f"{path}.repetitionNumber",
    )

    repetition_count = _require_positive_integer(
        segment["repetitionCount"],
        f"{path}.repetitionCount",
    )

    if (
        repetition_number
        > repetition_count
    ):
        raise SpeechPlanValidationError(
            f"{path}.repetitionNumber cannot exceed "
            "repetitionCount."
        )

    text = _require_nonempty_string(
        segment["text"],
        f"{path}.text",
    )

    language = _require_nonempty_string(
        segment["language"],
        f"{path}.language",
    )

    voice_profile_id = _require_string(
        segment["voiceProfileId"],
        f"{path}.voiceProfileId",
    )

    speaking_rate = _require_positive_decimal(
        segment["speakingRate"],
        f"{path}.speakingRate",
    )

    pause_before = _require_nonnegative_integer(
        segment["pauseBeforeMilliseconds"],
        f"{path}.pauseBeforeMilliseconds",
    )

    pause_after = _require_nonnegative_integer(
        segment["pauseAfterMilliseconds"],
        f"{path}.pauseAfterMilliseconds",
    )

    return SpeechPlanSegment(
        sequence=sequence,
        segment_id=segment_id,
        cue_id=cue_id,
        content_node_id=content_node_id,
        repetition_number=repetition_number,
        repetition_count=repetition_count,
        text=text,
        language=language,
        voice_profile_id=voice_profile_id,
        speaking_rate=speaking_rate,
        pause_before_milliseconds=pause_before,
        pause_after_milliseconds=pause_after,
    )


def _require_object(
    value: Any,
    path: str,
) -> dict[str, Any]:
    if not isinstance(
        value,
        dict,
    ):
        raise SpeechPlanValidationError(
            f"{path} must be an object."
        )

    return value


def _require_exact_fields(
    value: dict[str, Any],
    expected_fields: set[str],
    path: str,
) -> None:
    actual_fields = set(
        value
    )

    missing_fields = sorted(
        expected_fields
        - actual_fields
    )

    if missing_fields:
        raise SpeechPlanValidationError(
            f"{path} is missing required field(s): "
            f"{', '.join(missing_fields)}."
        )

    unexpected_fields = sorted(
        actual_fields
        - expected_fields
    )

    if unexpected_fields:
        raise SpeechPlanValidationError(
            f"{path} contains unexpected field(s): "
            f"{', '.join(unexpected_fields)}."
        )


def _validate_side(
    value: Any,
    path: str,
) -> None:
    if (
        not isinstance(
            value,
            str,
        )
        or value not in VALID_SIDES
    ):
        raise SpeechPlanValidationError(
            f'{path} must be "front" or "back".'
        )


def _require_string(
    value: Any,
    path: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise SpeechPlanValidationError(
            f"{path} must be a string."
        )

    return value


def _require_nonempty_string(
    value: Any,
    path: str,
) -> str:
    value = _require_string(
        value,
        path,
    )

    if not value.strip():
        raise SpeechPlanValidationError(
            f"{path} must be nonempty."
        )

    return value


def _require_integer(
    value: Any,
    path: str,
) -> int:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
    ):
        raise SpeechPlanValidationError(
            f"{path} must be an integer."
        )

    return value


def _require_positive_integer(
    value: Any,
    path: str,
) -> int:
    value = _require_integer(
        value,
        path,
    )

    if value < 1:
        raise SpeechPlanValidationError(
            f"{path} must be positive."
        )

    return value


def _require_nonnegative_integer(
    value: Any,
    path: str,
) -> int:
    value = _require_integer(
        value,
        path,
    )

    if value < 0:
        raise SpeechPlanValidationError(
            f"{path} cannot be negative."
        )

    return value


def _require_positive_decimal(
    value: Any,
    path: str,
) -> Decimal:
    if isinstance(
        value,
        bool,
    ):
        raise SpeechPlanValidationError(
            f"{path} must be numeric."
        )

    if isinstance(
        value,
        int,
    ):
        decimal_value = Decimal(
            value
        )
    elif isinstance(
        value,
        Decimal,
    ):
        decimal_value = value
    else:
        raise SpeechPlanValidationError(
            f"{path} must be numeric."
        )

    if (
        not decimal_value.is_finite()
        or decimal_value <= 0
    ):
        raise SpeechPlanValidationError(
            f"{path} must be finite and positive."
        )

    return decimal_value


def _reject_json_constant(
    value: str,
) -> None:
    raise ValueError(
        f"Non-finite JSON number is not permitted: {value}."
    )


def _reject_duplicate_keys(
    pairs,
):
    result = {}

    for key, value in pairs:
        if key in result:
            raise ValueError(
                f'Duplicate JSON property: "{key}".'
            )

        result[key] = value

    return result
