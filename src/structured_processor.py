from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    Decimal,
    ROUND_HALF_UP,
)
import re

from settings import (
    AppSettings,
    SpeechProfile,
)
from speech_plan import (
    SpeechPlan,
    SpeechPlanSegment,
)


SUPPORTED_LANGUAGE_PROFILES = {
    "fr",
    "en",
    "ja",
}

LOGICAL_PROFILE_ALIASES = {
    "french-primary": "fr",
    "english-primary": "en",
    "japanese-primary": "ja",
}

EDGE_RATE_PATTERN = re.compile(
    r"^([+-])(\d+)%$"
)


class StructuredSpeechProcessingError(
    ValueError
):
    """Raised when an RCE segment cannot be resolved for synthesis."""


@dataclass(frozen=True)
class ResolvedSpeechSegment:
    """One authoritative RCE segment with concrete synthesis settings."""

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
    resolved_profile_key: str
    resolved_profile_language: str
    voice: str
    edge_rate: str
    volume: str
    pitch: str


@dataclass(frozen=True)
class ResolvedSpeechTrack:
    """One validated RCE track with every segment ready for synthesis."""

    schema_version: int
    side: str
    segments: tuple[
        ResolvedSpeechSegment,
        ...,
    ]


def resolve_speech_plan(
    plan: SpeechPlan,
    settings: AppSettings,
) -> ResolvedSpeechTrack:
    """
    Resolve one parsed RCE plan without altering its semantic schedule.

    Text, order, repetitions, and exact pauses pass through unchanged.
    No normalization, splitting, or language detection occurs.
    """

    if not isinstance(
        plan,
        SpeechPlan,
    ):
        raise StructuredSpeechProcessingError(
            "plan must be a validated SpeechPlan."
        )

    if not isinstance(
        settings,
        AppSettings,
    ):
        raise StructuredSpeechProcessingError(
            "settings must be AppSettings."
        )

    resolved_segments = []

    for segment in plan.segments:
        resolved_segments.append(
            resolve_speech_segment(
                segment,
                settings,
            )
        )

    return ResolvedSpeechTrack(
        schema_version=plan.schema_version,
        side=plan.side,
        segments=tuple(
            resolved_segments
        ),
    )


def resolve_speech_segment(
    segment: SpeechPlanSegment,
    settings: AppSettings,
) -> ResolvedSpeechSegment:
    """Resolve one parsed segment to a concrete AnkiTTS profile."""

    if not isinstance(
        segment,
        SpeechPlanSegment,
    ):
        raise StructuredSpeechProcessingError(
            "segment must be a validated SpeechPlanSegment."
        )

    profile_key, speech_profile = resolve_speech_profile(
        language=segment.language,
        voice_profile_id=segment.voice_profile_id,
        settings=settings,
    )

    edge_rate = compose_edge_rate(
        speech_profile.rate,
        segment.speaking_rate,
    )

    return ResolvedSpeechSegment(
        sequence=segment.sequence,
        segment_id=segment.segment_id,
        cue_id=segment.cue_id,
        content_node_id=segment.content_node_id,
        repetition_number=segment.repetition_number,
        repetition_count=segment.repetition_count,
        text=segment.text,
        language=segment.language,
        voice_profile_id=segment.voice_profile_id,
        speaking_rate=segment.speaking_rate,
        pause_before_milliseconds=(
            segment.pause_before_milliseconds
        ),
        pause_after_milliseconds=(
            segment.pause_after_milliseconds
        ),
        resolved_profile_key=profile_key,
        resolved_profile_language=(
            speech_profile.language
        ),
        voice=speech_profile.voice,
        edge_rate=edge_rate,
        volume=speech_profile.volume,
        pitch=speech_profile.pitch,
    )


def resolve_speech_profile(
    language: str,
    voice_profile_id: str,
    settings: AppSettings,
) -> tuple[
    str,
    SpeechProfile,
]:
    """
    Resolve semantic locale and optional logical profile to one profile.

    An unknown nonempty logical ID is an error. The und language tag can
    resolve only through an explicit known logical profile.
    """

    language_profile_key = _language_profile_key(
        language
    )

    if voice_profile_id:
        profile_key = _logical_profile_key(
            voice_profile_id,
            settings,
        )
    else:
        if language_profile_key is None:
            raise StructuredSpeechProcessingError(
                'Language "und" requires a known nonempty '
                "voiceProfileId."
            )

        profile_key = language_profile_key

    speech_profile = settings.get_speech_profile(
        profile_key
    )

    if speech_profile is None:
        raise StructuredSpeechProcessingError(
            "No AnkiTTS speech profile is configured for "
            f'"{profile_key}".'
        )

    profile_language_key = _language_profile_key(
        speech_profile.language
    )

    if profile_language_key is None:
        raise StructuredSpeechProcessingError(
            "The resolved AnkiTTS speech profile has an "
            "undetermined language."
        )

    if (
        language_profile_key is not None
        and language_profile_key
        != profile_language_key
    ):
        raise StructuredSpeechProcessingError(
            "RCE segment language and logical voice profile "
            "refer to different languages."
        )

    return (
        profile_key,
        speech_profile,
    )


def parse_edge_rate_multiplier(
    edge_rate: str,
) -> Decimal:
    """Convert an Edge percentage rate such as +10% to a multiplier."""

    if not isinstance(
        edge_rate,
        str,
    ):
        raise StructuredSpeechProcessingError(
            "Edge speech-profile rate must be a string."
        )

    match = EDGE_RATE_PATTERN.fullmatch(
        edge_rate
    )

    if match is None:
        raise StructuredSpeechProcessingError(
            "Edge speech-profile rate must use a signed whole "
            'percentage such as "+10%" or "-5%".'
        )

    sign, digits = match.groups()
    percentage = Decimal(
        digits
    )

    if sign == "-":
        percentage = -percentage

    multiplier = (
        Decimal("1")
        + percentage
        / Decimal("100")
    )

    if multiplier <= 0:
        raise StructuredSpeechProcessingError(
            "Edge speech-profile rate must remain above -100%."
        )

    return multiplier


def compose_edge_rate(
    profile_rate: str,
    segment_multiplier: Decimal,
) -> str:
    """
    Combine an AnkiTTS base rate with an RCE multiplier.

    Edge accepts a whole signed percentage, so the composed percentage
    uses deterministic half-up rounding.
    """

    if (
        isinstance(
            segment_multiplier,
            bool,
        )
        or not isinstance(
            segment_multiplier,
            Decimal,
        )
        or not segment_multiplier.is_finite()
        or segment_multiplier <= 0
    ):
        raise StructuredSpeechProcessingError(
            "RCE segment speakingRate must be a finite positive "
            "Decimal."
        )

    profile_multiplier = parse_edge_rate_multiplier(
        profile_rate
    )

    effective_multiplier = (
        profile_multiplier
        * segment_multiplier
    )

    effective_percentage = (
        effective_multiplier
        - Decimal("1")
    ) * Decimal(
        "100"
    )

    rounded_percentage = effective_percentage.quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )

    percentage_integer = int(
        rounded_percentage
    )

    return (
        f"{percentage_integer:+d}%"
    )


def _language_profile_key(
    language: str,
) -> str | None:
    if (
        not isinstance(
            language,
            str,
        )
        or not language
    ):
        raise StructuredSpeechProcessingError(
            "Speech language must be a nonempty string."
        )

    primary_language = re.split(
        r"[-_]",
        language,
        maxsplit=1,
    )[0].casefold()

    if primary_language == "und":
        return None

    if (
        primary_language
        not in SUPPORTED_LANGUAGE_PROFILES
    ):
        raise StructuredSpeechProcessingError(
            "No structured AnkiTTS locale mapping exists for "
            f'"{language}".'
        )

    return primary_language


def _logical_profile_key(
    voice_profile_id: str,
    settings: AppSettings,
) -> str:
    direct_profile = settings.get_speech_profile(
        voice_profile_id
    )

    if direct_profile is not None:
        return voice_profile_id

    alias_profile_key = LOGICAL_PROFILE_ALIASES.get(
        voice_profile_id.casefold()
    )

    if alias_profile_key is None:
        raise StructuredSpeechProcessingError(
            "Unknown RCE logical voiceProfileId: "
            f'"{voice_profile_id}".'
        )

    return alias_profile_key
