from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
import math
from pathlib import Path
import subprocess
import threading

from ankitts_log import get_logger


MINIMUM_TEMPO = Decimal("0.5")
MAXIMUM_TEMPO = Decimal("2.0")

# Loudness normalisation (CA-35, CA-36). Every provider's clip is brought to
# one integrated loudness before it is cached. Bump LOUDNESS_VERSION whenever
# a value below changes what is cached; it is part of every provider identity.
LOUDNESS_VERSION = "1"
TARGET_LUFS = -16.0
TRUE_PEAK_TARGET_DBTP = -1.5
LOUDNESS_RANGE_LU = 11

# Pocket's voices have peaks 19 to 22 dB above their loudness, more than the
# 14.5 dB between -16 LUFS and -1.5 dBTP, so a purely linear gain cannot reach
# the target. Where it cannot, a limiter holds the sample peak at this ceiling
# (below the true-peak target: MP3 and inter-sample peaks add up to 1.5 dB).
LIMITER_CEILING_DBFS = -3.0
LIMITER_ATTACK_MS = 5
LIMITER_RELEASE_MS = 50

# The limiter may be asked to cut peaks by at most this much; beyond it the
# clip stays quieter than the target ("limited") rather than being squashed.
MAXIMUM_LIMITER_DB = 12.0
MAXIMUM_GAIN_DB = 30.0
CALIBRATION_TOLERANCE_LU = 0.3
CALIBRATION_ROUNDS = 3

# A clip shorter than 400 ms has no measurable integrated loudness; it is
# measured as if looped. Quieter than this is silence and is left alone.
LOOP_MEASUREMENT_FILTER = (
    "aloop=loop=-1:size=2147483647,atrim=duration=2"
)
SILENCE_FLOOR_LUFS = -69.0

# 96 kbit/s mono. The previous encoder default was about 32 kbit/s. Measured
# signal-to-distortion on real clips climbs steeply to 96k and is flat after
# it (within 1.2 dB of 128k), also for Edge clips, which are decoded and
# re-encoded (CA-36).
MP3_BITRATE = "96k"

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


@dataclass(frozen=True)
class LoudnessResult:
    """What normalisation measured and did to one clip."""

    input_lufs: float | None
    input_true_peak_dbtp: float | None
    gain_db: float
    output_lufs: float | None
    output_true_peak_dbtp: float | None
    limited: bool
    at_limit: bool
    looped: bool
    skipped: bool


def _ffmpeg():
    from pydub import AudioSegment

    return AudioSegment.converter


def _run_ffmpeg(
    arguments,
):
    from stitcher import hide_subprocess_windows

    with hide_subprocess_windows():
        return subprocess.run(
            [
                _ffmpeg(),
                "-hide_banner",
                "-nostats",
                *arguments,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )


def measure_loudness(
    source_path,
    chain="",
):
    """
    Integrated loudness (LUFS) and true peak (dBTP) of the audio after
    `chain`, measured by ffmpeg's loudnorm in analysis mode. Either value may
    be non-finite for silence, and the loudness is -inf under 400 ms.
    """

    result = _run_ffmpeg(
        [
            "-i",
            str(
                source_path
            ),
            "-af",
            (chain + "," if chain else "")
            + f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_TARGET_DBTP}"
            f":LRA={LOUDNESS_RANGE_LU}:print_format=json",
            "-f",
            "null",
            "-",
        ]
    )

    try:
        block = result.stderr[
            result.stderr.rindex(
                "{"
            ) : result.stderr.rindex(
                "}"
            )
            + 1
        ]

        data = json.loads(
            block
        )

        return (
            float(
                data[
                    "input_i"
                ]
            ),
            float(
                data[
                    "input_tp"
                ]
            ),
        )

    except (ValueError, KeyError):
        raise OSError(
            "ffmpeg loudness measurement failed."
        ) from None


def _chain(
    tempo,
    gain_db,
    limiter,
    looped=False,
):
    filters = []

    if looped:
        filters.append(
            LOOP_MEASUREMENT_FILTER
        )

    if tempo != 1:
        filters.append(
            f"atempo={tempo}"
        )

    if gain_db:
        filters.append(
            f"volume={gain_db:.3f}dB"
        )

    if limiter:
        filters.append(
            "alimiter="
            f"limit={10 ** (LIMITER_CEILING_DBFS / 20):.4f}"
            f":attack={LIMITER_ATTACK_MS}:release={LIMITER_RELEASE_MS}"
            ":level=disabled:latency=1"
        )

    return ",".join(
        filters
    )


def _is_measurable(
    lufs,
):
    return math.isfinite(
        lufs
    ) and lufs > SILENCE_FLOOR_LUFS


def plan_normalisation(
    source_path,
    tempo=Decimal("1"),
):
    """
    Decide the gain that brings a clip to TARGET_LUFS. Returns
    (chain, LoudnessResult): `chain` is the ffmpeg filter chain to encode with.

    Where a linear gain keeps the true peak under TRUE_PEAK_TARGET_DBTP that is
    all that is applied. Where it would not, a limiter holds the peaks at
    LIMITER_CEILING_DBFS and the gain is calibrated against a measurement of
    the limited audio, so the result is the target and never a clipped sample.
    If the limiter would have to cut more than MAXIMUM_LIMITER_DB, the clip
    stays quieter than the target and is reported as `at_limit`.
    """

    looped = False

    input_lufs, input_peak = measure_loudness(
        source_path,
        _chain(
            tempo,
            0,
            False,
        ),
    )

    if not _is_measurable(
        input_lufs
    ):
        looped = True

        input_lufs, input_peak = measure_loudness(
            source_path,
            _chain(
                tempo,
                0,
                False,
                True,
            ),
        )

    if not _is_measurable(
        input_lufs
    ):
        return _chain(
            tempo,
            0,
            False,
        ), LoudnessResult(
            None,
            None,
            0.0,
            None,
            None,
            False,
            False,
            looped,
            True,
        )

    wanted = max(
        -MAXIMUM_GAIN_DB,
        min(
            MAXIMUM_GAIN_DB,
            TARGET_LUFS - input_lufs,
        ),
    )

    if wanted <= TRUE_PEAK_TARGET_DBTP - input_peak:
        return _chain(
            tempo,
            wanted,
            False,
        ), LoudnessResult(
            input_lufs,
            input_peak,
            wanted,
            input_lufs + wanted,
            input_peak + wanted,
            False,
            False,
            looped,
            False,
        )

    ceiling_gain = (
        LIMITER_CEILING_DBFS
        - input_peak
        + MAXIMUM_LIMITER_DB
    )

    gain = min(
        wanted,
        ceiling_gain,
    )

    for attempt in range(
        CALIBRATION_ROUNDS
    ):
        output_lufs, output_peak = measure_loudness(
            source_path,
            _chain(
                tempo,
                gain,
                True,
                looped,
            ),
        )

        error = TARGET_LUFS - output_lufs

        if (
            abs(
                error
            )
            <= CALIBRATION_TOLERANCE_LU
            or attempt == CALIBRATION_ROUNDS - 1
        ):
            break

        corrected = min(
            gain + error,
            ceiling_gain,
        )

        if abs(
            corrected - gain
        ) < 0.05:
            break

        gain = corrected

    return _chain(
        tempo,
        gain,
        True,
    ), LoudnessResult(
        input_lufs,
        input_peak,
        gain,
        output_lufs,
        output_peak,
        True,
        output_lufs < TARGET_LUFS - 2 * CALIBRATION_TOLERANCE_LU,
        looped,
        False,
    )


def _describe(
    result,
):
    if result.skipped:
        return "Loudness: clip is silent or unmeasurable; left as it is."

    return (
        "Loudness: in %.1f LUFS %.1f dBTP, gain %+.1f dB%s, "
        "out %.1f LUFS %.1f dBTP%s%s"
        % (
            result.input_lufs,
            result.input_true_peak_dbtp,
            result.gain_db,
            " with limiter" if result.limited else "",
            result.output_lufs,
            result.output_true_peak_dbtp,
            " (at the peak limit, below target)" if result.at_limit else "",
            " (short clip, measured looped)" if result.looped else "",
        )
    )


def encode_mp3(
    source_path: Path,
    output_path: Path,
    tempo: Decimal = Decimal("1"),
) -> LoudnessResult:
    """
    Encode source audio (any ffmpeg-readable format) as the MP3 cache file,
    at tempo `tempo` and normalised to TARGET_LUFS (see plan_normalisation).

    Writes to a temporary sibling first so a failed encode never leaves a
    truncated cache entry. Returns what normalisation measured and did.
    """

    output_path = Path(
        output_path
    )

    temporary_path = output_path.with_name(
        f".{output_path.name}.encoding.tmp"
    )

    try:
        with _encode_lock:
            chain, result = plan_normalisation(
                source_path,
                tempo,
            )

            encoded = _run_ffmpeg(
                [
                    "-y",
                    "-i",
                    str(
                        source_path
                    ),
                    *(
                        [
                            "-af",
                            chain,
                        ]
                        if chain
                        else []
                    ),
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    MP3_BITRATE,
                    "-f",
                    "mp3",
                    str(
                        temporary_path
                    ),
                ]
            )

        if (
            encoded.returncode != 0
            or not temporary_path.exists()
            or temporary_path.stat().st_size == 0
        ):
            raise OSError(
                "ffmpeg produced no MP3 output."
            )

        temporary_path.replace(
            output_path
        )

        logger.info(
            _describe(
                result
            )
        )

        return result

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def normalise_mp3_in_place(
    path: Path,
) -> LoudnessResult:
    """
    Normalise an MP3 a provider has already written (Edge writes its own
    file): decode, normalise, re-encode, and replace it atomically.
    """

    path = Path(
        path
    )

    staged_path = path.with_name(
        f".{path.name}.normalising"
    )

    try:
        result = encode_mp3(
            path,
            staged_path,
        )

        staged_path.replace(
            path
        )

        return result

    finally:
        if staged_path.exists():
            staged_path.unlink()
