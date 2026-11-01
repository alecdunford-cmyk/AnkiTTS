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
from speech_text import SPEECH_TEXT_VERSION


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

        except Exception as error:
            raise ProviderError(
                f"{type(error).__name__}: {error}"
            ) from error

        if not created:
            raise NoAudioProduced(
                "Edge returned no audio after retries."
            )
