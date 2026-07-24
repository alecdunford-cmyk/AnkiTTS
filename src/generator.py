import asyncio
from importlib.metadata import (
    PackageNotFoundError,
    version,
)
from pathlib import Path

import edge_tts
from edge_tts.exceptions import NoAudioReceived


EDGE_PROVIDER_ID = "edge-tts"
EDGE_PROVIDER_MODEL = "edge-neural-voices"


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

    Return False when Edge TTS accepts the request but produces
    no playable audio. Other exceptions remain visible.
    """

    output_path = Path(
        output_file
    )

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

        return False

    return True
