import asyncio
from importlib.metadata import (
    PackageNotFoundError,
    version,
)
from pathlib import Path
import time

import edge_tts
from edge_tts.exceptions import NoAudioReceived


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
    """Return the synthesis identity used by structured cache keys."""

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
    Generate one audio file.

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
