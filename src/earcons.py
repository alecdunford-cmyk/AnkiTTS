"""
The three short sounds a schema-version-2 plan can ask for (CA-37 (4)).

Defaults are generated once into the add-on's user_files, which Anki keeps
across updates, and any of them can be replaced by a file named in settings.
They are mixed in at stitch time and are never part of a segment's cache key.
Tones are computed with the standard library, so Anki's bundled Python needs
nothing new; ffmpeg, already required, measures their loudness.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import struct
import threading
import wave

from ankitts_log import get_logger
from providers.audio import (
    LOOP_MEASUREMENT_FILTER,
    measure_loudness,
)
from settings import EARCON_ROLES


# Bump when a tone below changes; it is in the file name, so the new default is
# generated beside the old one and tracks using it are rebuilt.
EARCON_VERSION = "1"
EARCON_TARGET_LUFS = -20.0
EARCON_SAMPLE_RATE = 24000
MAXIMUM_AMPLITUDE = 0.89
CALIBRATION_ROUNDS = 3
CALIBRATION_TOLERANCE_LU = 0.3
FADE_MILLISECONDS = 15
TICK_ATTACK_MILLISECONDS = 3


@dataclass(frozen=True)
class EarconTone:
    milliseconds: int
    start_hz: float
    end_hz: float
    tick: bool = False


DEFAULT_TONES = {
    # A soft tick at a section boundary: high and quickly decaying.
    "sectionBoundary": EarconTone(
        milliseconds=120,
        start_hz=1320.0,
        end_hz=1320.0,
        tick=True,
    ),
    # A short rising tone before the answer side's content: C5 up to G5.
    "answerStart": EarconTone(
        milliseconds=220,
        start_hz=523.25,
        end_hz=783.99,
    ),
    # A distinct short tone where direction flips: a steady G4, below the rest.
    "directionFlip": EarconTone(
        milliseconds=180,
        start_hz=392.0,
        end_hz=392.0,
    ),
}

logger = get_logger(
    "earcons"
)

_generation_lock = threading.Lock()


def default_earcon_directory() -> Path:
    """
    Return the add-on's user_files/earcons folder, beside the logs.

    ANKITTS_EARCON_DIR overrides the location.
    """

    override = os.environ.get(
        "ANKITTS_EARCON_DIR"
    )

    if override:
        return Path(
            override
        )

    project_root = (
        Path(__file__)
        .resolve()
        .parent
        .parent
    )

    addon_dir = (
        project_root
        / "addon"
        if (
            project_root
            / "addon"
        ).is_dir()
        else project_root
    )

    return (
        addon_dir
        / "user_files"
        / "earcons"
    )


def default_earcon_path(
    role: str,
    directory: Path | None = None,
) -> Path:
    return (
        Path(
            directory
            if directory is not None
            else default_earcon_directory()
        )
        / f"earcon-{role}-v{EARCON_VERSION}.wav"
    )


def _tone_samples(
    tone: EarconTone,
) -> list[float]:
    """One tone at full scale: its sweep under its envelope."""

    frame_count = int(
        EARCON_SAMPLE_RATE
        * tone.milliseconds
        / 1000
    )

    fade_frames = int(
        EARCON_SAMPLE_RATE
        * FADE_MILLISECONDS
        / 1000
    )

    attack_frames = int(
        EARCON_SAMPLE_RATE
        * TICK_ATTACK_MILLISECONDS
        / 1000
    )

    samples = []
    phase = 0.0

    for frame in range(
        frame_count
    ):
        progress = frame / frame_count

        frequency = (
            tone.start_hz
            + (
                tone.end_hz
                - tone.start_hz
            )
            * progress
        )

        phase += (
            2
            * math.pi
            * frequency
            / EARCON_SAMPLE_RATE
        )

        if tone.tick:
            envelope = min(
                1.0,
                frame / attack_frames,
            ) * math.exp(
                -6.0 * progress
            )

        else:
            distance_to_edge = min(
                frame,
                frame_count - 1 - frame,
            )

            envelope = (
                0.5
                - 0.5
                * math.cos(
                    math.pi
                    * min(
                        1.0,
                        distance_to_edge / fade_frames,
                    )
                )
            )

        samples.append(
            envelope
            * math.sin(
                phase
            )
        )

    return samples


def _write_wav(
    path: Path,
    samples: list[float],
    amplitude: float,
) -> None:
    with wave.open(
        str(
            path
        ),
        "wb",
    ) as wav:
        wav.setnchannels(
            1
        )

        wav.setsampwidth(
            2
        )

        wav.setframerate(
            EARCON_SAMPLE_RATE
        )

        wav.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    round(
                        32767
                        * amplitude
                        * sample
                    ),
                )
                for sample in samples
            )
        )


def measure_earcon_loudness(
    path: Path,
) -> float:
    """Integrated loudness of a clip shorter than a BS.1770 block (CA-40)."""

    lufs, _true_peak = measure_loudness(
        path,
        LOOP_MEASUREMENT_FILTER,
    )

    return lufs


def _generate(
    role: str,
    path: Path,
) -> None:
    """Write one default tone, calibrated to EARCON_TARGET_LUFS."""

    samples = _tone_samples(
        DEFAULT_TONES[
            role
        ]
    )

    temporary_path = path.with_name(
        f".{path.stem}.tmp.wav"
    )

    amplitude = 0.25

    try:
        for _attempt in range(
            CALIBRATION_ROUNDS
        ):
            _write_wav(
                temporary_path,
                samples,
                amplitude,
            )

            lufs = measure_earcon_loudness(
                temporary_path
            )

            error = EARCON_TARGET_LUFS - lufs

            if (
                abs(
                    error
                )
                <= CALIBRATION_TOLERANCE_LU
            ):
                break

            amplitude = min(
                MAXIMUM_AMPLITUDE,
                amplitude
                * 10
                ** (
                    error
                    / 20
                ),
            )

        else:
            _write_wav(
                temporary_path,
                samples,
                amplitude,
            )

        temporary_path.replace(
            path
        )

    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    logger.info(
        "Generated the default %s earcon: %s",
        role,
        path.name,
    )


def ensure_default_earcon(
    role: str,
    directory: Path | None = None,
) -> Path:
    """Return a role's default tone, generating it only if it is missing."""

    if role not in DEFAULT_TONES:
        raise ValueError(
            f'Unknown earcon "{role}"; use '
            f"{', '.join(EARCON_ROLES)}."
        )

    path = default_earcon_path(
        role,
        directory,
    )

    with _generation_lock:
        if (
            not path.exists()
            or path.stat().st_size == 0
        ):
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            _generate(
                role,
                path,
            )

    return path


def resolve_earcon_path(
    role: str,
    settings,
    directory: Path | None = None,
) -> Path:
    """
    Return the file for one earcon: the one settings name, else the default.

    A named file that cannot be found falls back to the default with a warning:
    a moved sound file should not stop a card's audio being built.
    """

    configured = settings.earcons.get(
        role,
        "",
    ).strip()

    if configured:
        path = Path(
            configured
        )

        if (
            path.is_file()
            and path.stat().st_size > 0
        ):
            return path

        logger.warning(
            "The %s earcon file was not found (%s); using the default.",
            role,
            configured,
        )

    return ensure_default_earcon(
        role,
        directory,
    )


def file_sha256(
    path: Path,
) -> str:
    return hashlib.sha256(
        Path(
            path
        ).read_bytes()
    ).hexdigest()
