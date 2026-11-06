from contextlib import contextmanager
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import subprocess

from pydub import AudioSegment
import pydub.utils

from speech_plan import (
    PAUSE_BOUNDARY,
    PAUSE_FIXED,
    PAUSE_PROPORTIONAL,
)

PAUSE_DURATIONS = {
    ";": 325,
    ":": 375,
    ".": 500,
    "!": 550,
    "?": 575,
    "。": 500,
    "！": 550,
    "？": 575,
}

PARENTHETICAL_PAUSE = 250
DEFAULT_PAUSE = 225

# Where the sound has really ended, in audio that is already normalised to
# -16 LUFS (speech near -19 dBFS RMS). -45 dBFS once cut the last syllable of
# unnormalised English (docs/audio-tail-diagnosis-20261101.md, CA-22); -60 dBFS
# was right until loudness normalisation raised Pocket's -80 dBFS tail by up
# to 22 dB, to within 1.5 dB of it (CA-37). -50 dBFS leaves 8 dB above the
# loudest normalised tail floor measured and removes nothing above -59 dBFS.
SILENCE_THRESHOLD_DB = -50
# The stitched track is a further MP3 generation. The pydub default is about
# 32 kbit/s, which overshoots the clips' -3 dBFS peaks to full scale (CA-36).
TRACK_MP3_BITRATE = "96k"
TRAILING_SILENCE_CHUNK_MS = 10
TRIM_SAFETY_MARGIN_MS = 50
MINIMUM_AUDIO_LENGTH_MS = 50
# Between an earcon and the speech it belongs to, so a tone never runs straight
# into a word. An earcon stays next to its speech; the plan's pauses go outside.
EARCON_GAP_MS = 120

@contextmanager
def hide_subprocess_windows():
    """
    Temporarily prevent subprocesses such as FFmpeg and FFprobe
    from opening visible console windows on Windows.
    """

    if not hasattr(
        subprocess,
        "CREATE_NO_WINDOW",
    ):
        yield
        return

    original_subprocess_popen = (
        subprocess.Popen
    )

    original_pydub_popen = (
        pydub.utils.Popen
    )

    def hidden_popen(
        *args,
        **kwargs,
    ):
        existing_flags = kwargs.get(
            "creationflags",
            0,
        )

        kwargs[
            "creationflags"
        ] = (
            existing_flags
            | subprocess.CREATE_NO_WINDOW
        )

        startupinfo = kwargs.get(
            "startupinfo"
        )

        if startupinfo is None:
            startupinfo = (
                subprocess.STARTUPINFO()
            )

        startupinfo.dwFlags |= (
            subprocess.STARTF_USESHOWWINDOW
        )

        startupinfo.wShowWindow = (
            subprocess.SW_HIDE
        )

        kwargs[
            "startupinfo"
        ] = startupinfo

        return original_subprocess_popen(
            *args,
            **kwargs,
        )

    subprocess.Popen = hidden_popen
    pydub.utils.Popen = hidden_popen

    try:
        yield

    finally:
        subprocess.Popen = (
            original_subprocess_popen
        )

        pydub.utils.Popen = (
            original_pydub_popen
        )

def get_pause(segment):
    """Determine pause length from context and final punctuation."""

    if segment["parenthetical"]:
        return PARENTHETICAL_PAUSE

    text = segment["text"].rstrip()

    if not text:
        return DEFAULT_PAUSE

    return PAUSE_DURATIONS.get(
        text[-1],
        DEFAULT_PAUSE,
    )


def trim_trailing_silence(
    audio,
    silence_threshold_db=SILENCE_THRESHOLD_DB,
    chunk_size_ms=TRAILING_SILENCE_CHUNK_MS,
    margin_ms=TRIM_SAFETY_MARGIN_MS,
):
    """
    Remove trailing silence already included in a generated clip.

    This allows AnkiTTS to control the final pause duration instead
    of stacking custom silence on top of the provider's trailing silence.
    The last margin_ms of the original audio after the detected end of
    the sound is kept, so a soft word ending is never clipped.
    """

    trim_position = len(
        audio
    )

    while (
        trim_position > MINIMUM_AUDIO_LENGTH_MS
    ):
        chunk_start = max(
            0,
            trim_position - chunk_size_ms,
        )

        chunk = audio[
            chunk_start:trim_position
        ]

        if (
            chunk.dBFS
            > silence_threshold_db
        ):
            break

        trim_position = chunk_start

    return audio[
        : min(
            len(
                audio
            ),
            trim_position
            + margin_ms,
        )
    ]


def stitch_audio(
    segments,
    output_file,
):
    combined = AudioSegment.empty()

    with hide_subprocess_windows():
        for segment in segments:
            audio = AudioSegment.from_file(
                segment["file"]
            )

            audio = trim_trailing_silence(
                audio
            )

            combined += audio

            combined += AudioSegment.silent(
                duration=get_pause(
                    segment
                )
            )

        Path(
            output_file
        ).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        combined.export(
            output_file,
            format="mp3",
            bitrate=TRACK_MP3_BITRATE,
        )


def resolve_pause_milliseconds(
    spec,
    speech_milliseconds,
    tempo,
):
    """
    How long one schema-version-2 pause is (P4). Only here is it known how long
    the segment's audio is, so the plan says what kind of pause and this says
    how long:

      none          0
      fixed         the plan's milliseconds, exactly
      boundary      the tempo profile's section pause
      proportional  scale x pauseFactor x this segment's speech, clamped to
                    the tempo profile's minimum and maximum
    """

    if spec.kind == PAUSE_FIXED:
        return spec.milliseconds

    if spec.kind == PAUSE_BOUNDARY:
        return tempo.boundary_pause_ms

    if spec.kind == PAUSE_PROPORTIONAL:
        proportional = int(
            (
                spec.scale
                * tempo.pause_factor
                * Decimal(
                    speech_milliseconds
                )
            ).quantize(
                Decimal(
                    "1"
                ),
                rounding=ROUND_HALF_UP,
            )
        )

        return max(
            tempo.min_pause_ms,
            min(
                tempo.max_pause_ms,
                proportional,
            ),
        )

    return 0


def _segment_pause(
    segment,
    position,
    audio,
):
    """A segment's pause: its plan's kind if it has one, else exact (v1)."""

    spec = segment.get(
        f"pause_{position}"
    )

    if spec is None:
        return segment[
            f"pause_{position}_milliseconds"
        ]

    return resolve_pause_milliseconds(
        spec,
        len(
            audio
        ),
        segment[
            "tempo"
        ],
    )


def stitch_structured_audio(
    segments,
    output_file,
):
    """
    Stitch authoritative segments with their surrounding pauses.

    Unlike generic stitching, this path never infers silence from text.
    Export is published atomically only after the complete track succeeds.

    A schema-version-2 segment is laid out as: pause before, earcon before,
    speech, earcon after, pause after.

    Returns the timeline of the version 2 segments: one {"kind", "start_ms",
    "duration_ms"} per pause, earcon and clip, in order, measured before MP3
    encoding. A version 1 segment (no "tempo") is stitched exactly as it always
    was and adds nothing to it.
    """

    output_path = Path(
        output_file
    )

    temporary_path = output_path.with_name(
        f".{output_path.name}.tmp"
    )

    if temporary_path.exists():
        temporary_path.unlink()

    combined = AudioSegment.empty()
    timeline = []

    def append(
        kind,
        audio,
        recorded,
    ):
        nonlocal combined

        if not recorded:
            combined += audio
            return

        start = len(
            combined
        )

        combined += audio

        timeline.append(
            {
                "kind": kind,
                "start_ms": start,
                "duration_ms": (
                    len(
                        combined
                    )
                    - start
                ),
            }
        )

    try:
        with hide_subprocess_windows():
            for segment in segments:
                recorded = "tempo" in segment

                # The pause before is computed from this segment's own audio
                # (P4), so the clip is decoded first.
                audio = AudioSegment.from_file(
                    segment[
                        "file"
                    ]
                )

                audio = trim_trailing_silence(
                    audio
                )

                pause_before = _segment_pause(
                    segment,
                    "before",
                    audio,
                )

                pause_after = _segment_pause(
                    segment,
                    "after",
                    audio,
                )

                if pause_before:
                    append(
                        "pause_before",
                        AudioSegment.silent(
                            duration=pause_before
                        ),
                        recorded,
                    )

                earcon_before = segment.get(
                    "earcon_before"
                )

                if earcon_before:
                    append(
                        "earcon_before",
                        AudioSegment.from_file(
                            earcon_before
                        ),
                        recorded,
                    )

                    append(
                        "earcon_gap",
                        AudioSegment.silent(
                            duration=EARCON_GAP_MS
                        ),
                        recorded,
                    )

                append(
                    "speech",
                    audio,
                    recorded,
                )

                earcon_after = segment.get(
                    "earcon_after"
                )

                if earcon_after:
                    append(
                        "earcon_gap",
                        AudioSegment.silent(
                            duration=EARCON_GAP_MS
                        ),
                        recorded,
                    )

                    append(
                        "earcon_after",
                        AudioSegment.from_file(
                            earcon_after
                        ),
                        recorded,
                    )

                if pause_after:
                    append(
                        "pause_after",
                        AudioSegment.silent(
                            duration=pause_after
                        ),
                        recorded,
                    )

            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            combined.export(
                temporary_path,
                format="mp3",
                bitrate=TRACK_MP3_BITRATE,
            )

        temporary_path.replace(
            output_path
        )

    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()

        raise

    return timeline
