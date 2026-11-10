"""
The short sounds a schema-version-2 plan can ask for (CA-37 (4)): the original
three, and the three of CA-71 (1) -- a numbered section, a lettered
sub-section and an idiom block's heading, each played before what it marks.

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
    """
    One default tone: a sweep from start_hz to end_hz, or, when notes is given,
    a run of steady notes (hz, milliseconds) joined end to end, each with its
    own soft edges (milliseconds is then their total).
    """

    milliseconds: int
    start_hz: float
    end_hz: float
    tick: bool = False
    notes: tuple[tuple[float, int], ...] = ()
    fade_milliseconds: int = FADE_MILLISECONDS


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
    # CA-71 (1), played BEFORE the thing each marks. Told apart from each other
    # and from the three above by direction, pitch and length (test_earcons).
    #
    # A numbered section: a falling two-note step, A5 then D5, the longest and
    # most definite of the three ("ding-dong").
    "sectionNumber": EarconTone(
        milliseconds=220,
        start_hz=880.0,
        end_hz=587.33,
        notes=(
            (880.0, 110),
            (587.33, 110),
        ),
    ),
    # A lettered sub-section: the lighter sibling, a short rising two-note
    # step, G5 then C6, higher and half as long ("ti-ding").
    "sectionLetter": EarconTone(
        milliseconds=130,
        start_hz=783.99,
        end_hz=1046.5,
        notes=(
            (783.99, 65),
            (1046.5, 65),
        ),
        fade_milliseconds=12,
    ),
    # The heading of an idiom block inside a sense: a low, slow falling glide,
    # A4 down to E4, in the register none of the other five uses.
    "idiomHeading": EarconTone(
        milliseconds=240,
        start_hz=440.0,
        end_hz=329.63,
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

    if tone.notes:
        samples = []

        for (
            hz,
            milliseconds,
        ) in tone.notes:
            samples.extend(
                _tone_samples(
                    EarconTone(
                        milliseconds=milliseconds,
                        start_hz=hz,
                        end_hz=hz,
                        fade_milliseconds=tone.fade_milliseconds,
                    )
                )
            )

        return samples

    frame_count = int(
        EARCON_SAMPLE_RATE
        * tone.milliseconds
        / 1000
    )

    fade_frames = int(
        EARCON_SAMPLE_RATE
        * tone.fade_milliseconds
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
