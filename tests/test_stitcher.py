from __future__ import annotations

from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from pydub import AudioSegment
from pydub.generators import Sine

import stitcher
from stitcher import (
    TRIM_SAFETY_MARGIN_MS,
    stitch_structured_audio,
    trim_trailing_silence,
)
from tests.test_pocket_provider import PROFILE, make_provider


def tone(milliseconds, level_dbfs):
    # A sine's RMS is its peak minus 3 dB, so gain the generator accordingly.
    return Sine(440).to_audio_segment(
        duration=milliseconds,
        volume=level_dbfs + 3.0,
    )


def check_trim_keeps_quiet_tail_and_margin():
    body = tone(500, -20)
    quiet = tone(60, -50)
    silence = AudioSegment.silent(duration=400)
    clip = body + quiet + silence

    kept = trim_trailing_silence(clip)

    # The quiet tail is kept whole, then the margin, and no more.
    assert len(kept) == 560 + TRIM_SAFETY_MARGIN_MS
    assert kept[500:560].dBFS > -55

    # The old rule (-45 dBFS, no margin) is the defect this guards against.
    old = trim_trailing_silence(
        clip,
        silence_threshold_db=-45,
        margin_ms=0,
    )

    assert len(old) <= 510


def check_trim_margin_is_bounded_by_the_clip():
    loud_to_the_end = tone(300, -20)

    assert len(trim_trailing_silence(loud_to_the_end)) == 300

    short_tail = tone(300, -20) + AudioSegment.silent(duration=20)

    assert len(trim_trailing_silence(short_tail)) == 320

    long_tail = tone(300, -20) + AudioSegment.silent(duration=500)

    assert len(trim_trailing_silence(long_tail)) == 300 + TRIM_SAFETY_MARGIN_MS

    assert len(trim_trailing_silence(AudioSegment.silent(duration=0))) == 0


def check_quiet_tail_from_the_worker_survives_the_stitched_track():
    if shutil.which("ffmpeg") is None:
        print("(ffmpeg not on PATH; skipped)", end=" ")
        return

    with TemporaryDirectory() as directory:
        provider = make_provider(directory)

        try:
            cache_file = Path(directory) / "segment.mp3"
            provider.synthesize("QUIETTAIL", "fr", PROFILE, cache_file)

        finally:
            provider.close()

        track = Path(directory) / "track.mp3"

        stitch_structured_audio(
            [
                {
                    "file": str(cache_file),
                    "pause_before_milliseconds": 0,
                    "pause_after_milliseconds": 0,
                }
            ],
            track,
        )

        encoded = AudioSegment.from_file(str(cache_file))
        stitched = AudioSegment.from_file(str(track))

        # The worker's WAV is 960 ms: 500 loud, 60 quiet, 400 silent.
        assert abs(len(encoded) - 960) <= 60

        # The last 60 ms of speech is still in the track (not trimmed)...
        assert len(stitched) >= 560 - 15
        assert stitched[500:555].dBFS > -58

        # ...and the 400 ms of silence behind it still is.
        assert len(stitched) <= 560 + TRIM_SAFETY_MARGIN_MS + 60

        # The old threshold would have removed the quiet speech.
        old = trim_trailing_silence(
            encoded,
            silence_threshold_db=-45,
            margin_ms=0,
        )

        assert len(old) < 530
        assert len(stitched) - len(old) >= 40


def check_stitchers_use_the_shared_trim():
    assert stitcher.SILENCE_THRESHOLD_DB == -60
    assert TRIM_SAFETY_MARGIN_MS == 50


def run():
    checks = [
        check_trim_keeps_quiet_tail_and_margin,
        check_trim_margin_is_bounded_by_the_clip,
        check_quiet_tail_from_the_worker_survives_the_stitched_track,
        check_stitchers_use_the_shared_trim,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
