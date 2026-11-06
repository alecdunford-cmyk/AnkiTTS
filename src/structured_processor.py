from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    Decimal,
    ROUND_HALF_UP,
)
import re

from settings import (
    AppSettings,
    DEFAULT_ROLE_VOICES,
    SpeechProfile,
    TempoProfile,
)
from speech_plan import (
    PauseSpec,
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
    role: str | None = None
    voice_role: str | None = None
    voice_provider: str | None = None
    pause_before: PauseSpec | None = None
    pause_after: PauseSpec | None = None
    earcon_before: str | None = None
    earcon_after: str | None = None
    spoken: bool = True


@dataclass(frozen=True)
class ResolvedSpeechTrack:
    """One validated RCE track with every segment ready for synthesis."""

    schema_version: int
    side: str
    segments: tuple[
        ResolvedSpeechSegment,
        ...,
    ]
    tempo: TempoProfile | None = None

    @property
    def spoken_segments(
        self,
    ) -> tuple[
        ResolvedSpeechSegment,
        ...,
    ]:
        """The segments that produce audio, in plan order."""

        return tuple(
            segment
            for segment in self.segments
            if segment.spoken
        )


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

    tempo = (
        settings.get_tempo_profile(
            plan.tempo_profile
        )
        if plan.tempo_profile is not None
        else None
    )

    resolved_segments = []

    for segment in plan.segments:
        resolved_segments.append(
            resolve_speech_segment(
                segment,
                settings,
                tempo,
            )
        )

    return ResolvedSpeechTrack(
        schema_version=plan.schema_version,
        side=plan.side,
        segments=tuple(
            resolved_segments
        ),
        tempo=tempo,
    )


def resolve_speech_segment(
    segment: SpeechPlanSegment,
    settings: AppSettings,
    tempo: TempoProfile | None = None,
) -> ResolvedSpeechSegment:
    """
    Resolve one parsed segment to a concrete AnkiTTS profile.

    A tempo profile's rate multiplies the segment's speakingRate. The resulting
    rate is a synthesis input, in the key as every rate is; the profile's name
    and its pause numbers are not (P5).
    """

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
        (
            segment.speaking_rate
            * tempo.rate
            if tempo is not None
            else segment.speaking_rate
        ),
    )

    voice, voice_provider = resolve_role_voice(
        segment.voice_role,
        speech_profile,
        settings,
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
        voice=voice,
        edge_rate=edge_rate,
        volume=speech_profile.volume,
        pitch=speech_profile.pitch,
        role=segment.role,
        voice_role=segment.voice_role,
        voice_provider=voice_provider,
        pause_before=segment.pause_before,
        pause_after=segment.pause_after,
        earcon_before=segment.earcon_before,
        earcon_after=segment.earcon_after,
        spoken=segment.spoken,
    )


def resolve_role_voice(
    voice_role: str | None,
    speech_profile: SpeechProfile,
    settings: AppSettings,
) -> tuple[
    str,
    str | None,
]:
    """
    Return (Edge voice, preferred provider id) for one segment's voice role.

    A segment with no voice role (schema version 1) keeps its speech
    profile's voice and the plain chain, so its cache key cannot change (P3).
    A language with no slot for the role also keeps the speech profile's voice.

    Pocket and Fish use their own configured voice, so a slot on one of them
    has no Edge voice of its own; the role's default is what Edge would speak
    if the chain ever falls through to it.
    """

    if voice_role is None:
        return (
            speech_profile.voice,
            None,
        )

    language_key = _language_profile_key(
        speech_profile.language
    )

    slot = settings.get_role_voice(
        language_key,
        voice_role,
    )

    if slot is None:
        return (
            speech_profile.voice,
            None,
        )

    if slot[
        "provider"
    ] == "edge":
        return (
            slot[
                "voice"
            ],
            "edge",
        )

    default_slot = DEFAULT_ROLE_VOICES.get(
        language_key,
        {},
    ).get(
        voice_role
    )

    return (
        (
            default_slot[
                "voice"
            ]
            if default_slot is not None
            else speech_profile.voice
        ),
        slot[
            "provider"
        ],
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
