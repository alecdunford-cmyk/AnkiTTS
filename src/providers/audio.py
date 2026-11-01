from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import threading

from ankitts_log import get_logger


MINIMUM_TEMPO = Decimal("0.5")
MAXIMUM_TEMPO = Decimal("2.0")

# stitcher.hide_subprocess_windows patches subprocess.Popen globally, so
# concurrent encodes from synthesis threads take turns.
_encode_lock = threading.Lock()

logger = get_logger(
    "providers.audio"
)


def tempo_from_rate(
    rate: str,
) -> Decimal:
    """
    Turn an Edge-format rate such as +10% into an atempo multiplier.

    The multiplier is bounded to 0.5-2.0 (one atempo stage) and clamped
    with a warning outside that range.
    """

    from structured_processor import parse_edge_rate_multiplier

    multiplier = parse_edge_rate_multiplier(
        rate
    )

    if multiplier < MINIMUM_TEMPO:
        logger.warning(
            "Rate %s is below the atempo bound; clamped to %s.",
            rate,
            MINIMUM_TEMPO,
        )

        return MINIMUM_TEMPO

    if multiplier > MAXIMUM_TEMPO:
        logger.warning(
            "Rate %s is above the atempo bound; clamped to %s.",
            rate,
            MAXIMUM_TEMPO,
        )

        return MAXIMUM_TEMPO

    return multiplier


def encode_mp3(
    source_path: Path,
    output_path: Path,
    tempo: Decimal = Decimal("1"),
) -> None:
    """
    Encode source audio (any ffmpeg-readable format) as the MP3 cache file.

    Writes to a temporary sibling first so a failed encode never leaves a
    truncated cache entry.
    """

    from pydub import AudioSegment
    from stitcher import hide_subprocess_windows

    output_path = Path(
        output_path
    )

    temporary_path = output_path.with_name(
        f".{output_path.name}.encoding.tmp"
    )

    parameters = []

    if tempo != 1:
        parameters = [
            "-filter:a",
            f"atempo={tempo}",
        ]

    try:
        with _encode_lock, hide_subprocess_windows():
            audio = AudioSegment.from_file(
                str(
                    source_path
                )
            )

            audio.export(
                str(
                    temporary_path
                ),
                format="mp3",
                parameters=parameters,
            )

        if (
            not temporary_path.exists()
            or temporary_path.stat().st_size == 0
        ):
            raise OSError(
                "ffmpeg produced no MP3 output."
            )

        temporary_path.replace(
            output_path
        )

    finally:
        if temporary_path.exists():
            temporary_path.unlink()
