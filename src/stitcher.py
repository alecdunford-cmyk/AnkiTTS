from contextlib import contextmanager
from pathlib import Path
import subprocess

from pydub import AudioSegment


@contextmanager
def hide_subprocess_windows():
    """
    Temporarily prevent subprocesses such as FFmpeg from opening
    visible console windows on Windows.
    """
    if not hasattr(subprocess, "CREATE_NO_WINDOW"):
        yield
        return

    original_popen = subprocess.Popen

    def hidden_popen(*args, **kwargs):
        existing_flags = kwargs.get("creationflags", 0)

        kwargs["creationflags"] = (
            existing_flags | subprocess.CREATE_NO_WINDOW
        )

        startupinfo = kwargs.get("startupinfo")

        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()

        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

        kwargs["startupinfo"] = startupinfo

        return original_popen(*args, **kwargs)

    subprocess.Popen = hidden_popen

    try:
        yield
    finally:
        subprocess.Popen = original_popen


def get_pause(segment):
    """
    Determine pause length based on context.
    """

    if segment["parenthetical"]:
        return 350

    if segment["text"].endswith((".", "!", "?")):
        return 700

    return 300


def stitch_audio(segments, output_file):
    combined = AudioSegment.empty()

    with hide_subprocess_windows():
        for segment in segments:
            audio = AudioSegment.from_file(
                segment["file"]
            )

            combined += audio

            combined += AudioSegment.silent(
                duration=get_pause(segment)
            )

        Path(output_file).parent.mkdir(
            parents=True,
            exist_ok=True
        )

        combined.export(
            output_file,
            format="mp3"
        )