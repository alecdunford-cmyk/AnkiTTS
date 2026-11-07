from __future__ import annotations

import asyncio
from importlib.metadata import (
    PackageNotFoundError,
    version,
)
from pathlib import Path
import time

import edge_tts
from edge_tts.exceptions import NoAudioReceived

from providers.base import (
    Capabilities,
    HealthStatus,
    NoAudioProduced,
    Provider,
    ProviderError,
)
from providers.audio import (
    LOUDNESS_VERSION,
    normalise_mp3_in_place,
)
from ankitts_log import get_logger
from speech_text import SPEECH_TEXT_VERSION

logger = get_logger(
    "providers.edge"
)


EDGE_PROVIDER_ID = "edge-tts"
EDGE_PROVIDER_MODEL = "edge-neural-voices"
EDGE_NO_AUDIO_RETRY_DELAYS = (
    1.0,
    2.0,
    4.0,
)
EDGE_NO_AUDIO_MAX_ATTEMPTS = (
    len(
        EDGE_NO_AUDIO_RETRY_DELAYS
    )
    + 1
)


# Language to the engine (CA-55, CA-56). Edge's multilingual voices choose the
# language of a segment from its text, and a bare headword, a short label or a
# word spelled alike in both languages is read as English. The endpoint takes
# no language in SSML (a <lang> element returns no audio; a top-level xml:lang
# changes the audio equally for any locale), so a short segment is spoken after
# a short sentence that is unmistakably in its language, and the sentence is
# cut off again using the word offsets edge-tts returns. Bump
# EDGE_LANGUAGE_VERSION whenever a value below changes what is cached; it is
# part of the Edge identity.
EDGE_LANGUAGE_VERSION = "1"
EDGE_CARRIERS = {
    "fr": "Écoutez bien le mot suivant :",
    "en": "Listen carefully to the following word:",
}
EDGE_MULTILINGUAL_MARKER = "Multilingual"
# Longer segments are recognised correctly on their own, and a carrier would
# only change their first intonation.
EDGE_CARRIER_MAX_WORDS = 4
# The cut falls this long before the first word's reported offset.
EDGE_CARRIER_LEAD_SECONDS = 0.02
EDGE_TICKS_PER_SECOND = 10_000_000


def get_edge_provider_identity():
    """Return the synthesis identity used by cache keys."""

    provider_version = getattr(
        edge_tts,
        "__version__",
        None,
    )

    if provider_version is None:
        try:
            provider_version = version(
                "edge-tts"
            )

        except PackageNotFoundError:
            provider_version = "unknown"

    return {
        "provider": EDGE_PROVIDER_ID,
        "provider_model": EDGE_PROVIDER_MODEL,
        "provider_version": str(
            provider_version
        ),
    }


async def generate_audio(
    text,
    voice,
    output_file,
    rate="+0%",
    volume="+0%",
    pitch="+0Hz",
):
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
    )

    await communicate.save(
        output_file
    )


def create_audio(
    text,
    voice,
    output_file,
    rate="+0%",
    volume="+0%",
    pitch="+0Hz",
):
    """
    Generate one audio file with Edge.

    Retry Edge's explicit no-audio response with bounded backoff.
    Return False only when every attempt produces no playable audio.
    Other exceptions remain visible.
    """

    output_path = Path(
        output_file
    )

    for attempt in range(
        EDGE_NO_AUDIO_MAX_ATTEMPTS
    ):
        try:
            asyncio.run(
                generate_audio(
                    text=text,
                    voice=voice,
                    output_file=str(
                        output_path
                    ),
                    rate=rate,
                    volume=volume,
                    pitch=pitch,
                )
            )

        except NoAudioReceived:
            if output_path.exists():
                output_path.unlink()

            if (
                attempt
                == EDGE_NO_AUDIO_MAX_ATTEMPTS
                - 1
            ):
                return False

            time.sleep(
                EDGE_NO_AUDIO_RETRY_DELAYS[
                    attempt
                ]
            )

            continue

        return True

    return False


def primary_subtag(
    language,
):
    """Return "fr" for "fr", "fr-FR" or "fr_FR"; "" for anything else."""

    if not isinstance(
        language,
        str,
    ):
        return ""

    return (
        language.replace(
            "_",
            "-",
        )
        .split(
            "-"
        )[0]
        .strip()
        .lower()
    )


def spoken_words(
    text,
):
    """The tokens of a text that contain a letter or a digit."""

    return [
        token
        for token in str(
            text
        ).split()
        if any(
            character.isalnum()
            for character in token
        )
    ]


def carrier_for(
    text,
    language,
    voice,
):
    """
    Return the carrier sentence for one segment, or None when it needs none:
    the voice is not multilingual, the language has no carrier, or the text
    is empty or longer than EDGE_CARRIER_MAX_WORDS words.
    """

    carrier = EDGE_CARRIERS.get(
        primary_subtag(
            language
        )
    )

    if (
        carrier is None
        or EDGE_MULTILINGUAL_MARKER
        not in str(
            voice
        )
    ):
        return None

    word_count = len(
        spoken_words(
            text
        )
    )

    if not (
        1
        <= word_count
        <= EDGE_CARRIER_MAX_WORDS
    ):
        return None

    return carrier


def _letters(
    word,
):
    return "".join(
        character
        for character in str(
            word
        ).casefold()
        if character.isalnum()
    )


def target_start_seconds(
    events,
    carrier,
):
    """
    Where the segment's first word begins, from edge-tts's word offsets, or
    None when the events do not look like the carrier followed by a word.
    """

    carrier_words = spoken_words(
        carrier
    )

    if len(
        events
    ) <= len(
        carrier_words
    ):
        return None

    last_carrier_event = events[
        len(
            carrier_words
        )
        - 1
    ]

    if _letters(
        last_carrier_event.get(
            "text",
            "",
        )
    ) != _letters(
        carrier_words[-1]
    ):
        return None

    start = (
        events[
            len(
                carrier_words
            )
        ]["offset"]
        / EDGE_TICKS_PER_SECOND
    )

    if start <= (
        last_carrier_event["offset"]
        / EDGE_TICKS_PER_SECOND
    ):
        return None

    return start


async def generate_audio_with_events(
    text,
    voice,
    output_file,
    rate="+0%",
    volume="+0%",
    pitch="+0Hz",
):
    """Like generate_audio, and return the word boundary events."""

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
        boundary="WordBoundary",
    )

    events = []

    with open(
        output_file,
        "wb",
    ) as audio:
        async for message in communicate.stream():
            if message["type"] == "audio":
                audio.write(
                    message["data"]
                )

            elif message["type"] == "WordBoundary":
                events.append(
                    message
                )

    return events


def cut_leading_audio(
    source_path,
    output_path,
    start_seconds,
):
    """
    Write source_path from start_seconds on as 24 kHz mono PCM (WAV content)
    at output_path. Lossless, so the one MP3 encode that follows is the only
    one this audio gets after Edge's own.
    """

    from providers.audio import (
        _encode_lock,
        _run_ffmpeg,
    )

    with _encode_lock:
        result = _run_ffmpeg(
            [
                "-y",
                "-ss",
                f"{start_seconds:.3f}",
                "-i",
                str(
                    source_path
                ),
                "-ac",
                "1",
                "-ar",
                "24000",
                "-f",
                "wav",
                str(
                    output_path
                ),
            ]
        )

    output_path = Path(
        output_path
    )

    if (
        result.returncode != 0
        or not output_path.exists()
        or output_path.stat().st_size
        <= 2000
    ):
        raise OSError(
            "Cutting the carrier sentence off produced no audio."
        )


def create_audio_with_carrier(
    text,
    voice,
    output_file,
    carrier,
    rate="+0%",
    volume="+0%",
    pitch="+0Hz",
):
    """
    Generate one audio file with Edge for a short segment: the text is spoken
    after the carrier sentence, which is cut off again. The file written is
    PCM (WAV content), not MP3; EdgeProvider.synthesize normalises it into an
    MP3 as it does Edge's own file.

    Same retry rule as create_audio. When the word offsets do not look like
    the carrier followed by the text, or the cut fails, the segment is
    generated without a carrier instead.
    """

    output_path = Path(
        output_file
    )

    staged_path = output_path.with_name(
        f".{output_path.name}.carrier"
    )

    def plain():
        return create_audio(
            text=text,
            voice=voice,
            output_file=str(
                output_path
            ),
            rate=rate,
            volume=volume,
            pitch=pitch,
        )

    try:
        for attempt in range(
            EDGE_NO_AUDIO_MAX_ATTEMPTS
        ):
            try:
                events = asyncio.run(
                    generate_audio_with_events(
                        text=f"{carrier} {text}",
                        voice=voice,
                        output_file=str(
                            staged_path
                        ),
                        rate=rate,
                        volume=volume,
                        pitch=pitch,
                    )
                )

            except NoAudioReceived:
                if staged_path.exists():
                    staged_path.unlink()

                if (
                    attempt
                    == EDGE_NO_AUDIO_MAX_ATTEMPTS
                    - 1
                ):
                    return False

                time.sleep(
                    EDGE_NO_AUDIO_RETRY_DELAYS[
                        attempt
                    ]
                )

                continue

            break

        start = target_start_seconds(
            events,
            carrier,
        )

        if start is None:
            logger.warning(
                "Edge word offsets did not match the carrier; "
                "generated without it."
            )

            return plain()

        try:
            cut_leading_audio(
                staged_path,
                output_path,
                max(
                    0.0,
                    start
                    - EDGE_CARRIER_LEAD_SECONDS,
                ),
            )

        except Exception as error:
            logger.warning(
                "Cutting the carrier off failed (%s); "
                "generated without it.",
                error,
            )

            if output_path.exists():
                output_path.unlink()

            return plain()

        return True

    finally:
        if staged_path.exists():
            staged_path.unlink()


class EdgeProvider(Provider):
    """Microsoft Edge Neural voices through edge-tts (free, network)."""

    provider_id = "edge"

    def identity(
        self,
        language,
    ):
        return {
            **get_edge_provider_identity(),
            "speech_text_version": SPEECH_TEXT_VERSION,
            "loudness_version": LOUDNESS_VERSION,
            "edge_language_version": EDGE_LANGUAGE_VERSION,
        }

    def capabilities(self):
        return Capabilities(
            languages=None,
            native_rate=True,
            volume=True,
            pitch=True,
            local=False,
            max_parallel=3,
        )

    def voices(
        self,
        language,
    ):
        from voice_manager import VoiceManager

        return [
            voice.get(
                "ShortName",
                "",
            )
            for voice in VoiceManager().get_voices(
                language
            )
        ]

    def health(
        self,
        language=None,
    ):
        return HealthStatus(
            ok=True,
            detail="edge-tts needs no local configuration.",
        )

    def synthesize(
        self,
        text,
        language,
        profile,
        output_path,
    ):
        try:
            carrier = carrier_for(
                text,
                language,
                profile.voice,
            )

            if carrier is None:
                created = create_audio(
                    text=text,
                    voice=profile.voice,
                    output_file=str(
                        output_path
                    ),
                    rate=profile.rate,
                    volume=profile.volume,
                    pitch=profile.pitch,
                )

            else:
                created = create_audio_with_carrier(
                    text=text,
                    voice=profile.voice,
                    output_file=str(
                        output_path
                    ),
                    carrier=carrier,
                    rate=profile.rate,
                    volume=profile.volume,
                    pitch=profile.pitch,
                )

        except Exception as error:
            raise ProviderError(
                f"{type(error).__name__}: {error}"
            ) from error

        if not created:
            raise NoAudioProduced(
                "Edge returned no audio after retries."
            )

        try:
            normalise_mp3_in_place(
                output_path
            )

        except Exception as error:
            if Path(
                output_path
            ).exists():
                Path(
                    output_path
                ).unlink()

            raise ProviderError(
                f"Normalising Edge audio failed: {error}"
            ) from error
