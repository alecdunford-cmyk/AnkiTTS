from contextlib import contextmanager
from pathlib import Path
import subprocess

from pydub import AudioSegment
import pydub.utils

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

SILENCE_THRESHOLD_DB = -45
TRAILING_SILENCE_CHUNK_MS = 10
MINIMUM_AUDIO_LENGTH_MS = 50

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
):
    """
    Remove trailing silence already included in a generated clip.

    This allows AnkiTTS to control the final pause duration instead
    of stacking custom silence on top of Edge TTS trailing silence.
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
        :trim_position
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
        )


def stitch_structured_audio(
    segments,
    output_file,
):
    """
    Stitch authoritative segments with exact surrounding pauses.

    Unlike generic stitching, this path never infers silence from text.
    Export is published atomically only after the complete track succeeds.
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

    try:
        with hide_subprocess_windows():
            for segment in segments:
                pause_before = segment[
                    "pause_before_milliseconds"
                ]

                pause_after = segment[
                    "pause_after_milliseconds"
                ]

                if pause_before:
                    combined += AudioSegment.silent(
                        duration=pause_before
                    )

                audio = AudioSegment.from_file(
                    segment[
                        "file"
                    ]
                )

                audio = trim_trailing_silence(
                    audio
                )

                combined += audio

                if pause_after:
                    combined += AudioSegment.silent(
                        duration=pause_after
                    )

            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            combined.export(
                temporary_path,
                format="mp3",
            )

        temporary_path.replace(
            output_path
        )

    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()

        raise
