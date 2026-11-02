from __future__ import annotations

from decimal import Decimal
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from pydub import AudioSegment
from pydub.generators import Sine

from providers import edge as edge_module
from providers.audio import (
    CALIBRATION_TOLERANCE_LU,
    LOOP_MEASUREMENT_FILTER,
    LOUDNESS_VERSION,
    MAXIMUM_LIMITER_DB,
    TARGET_LUFS,
    TRUE_PEAK_TARGET_DBTP,
    encode_mp3,
    measure_loudness,
    normalise_mp3_in_place,
)
from providers.edge import EdgeProvider
from providers.pocket import PocketProvider
from settings import SpeechProfile


# Every clip below is a generated tone; no speech or card text is involved.

TESTS_DIR = Path(__file__).resolve().parent
FAKE_WORKER = TESTS_DIR / "fake_pocket_worker.py"
PROFILE = SpeechProfile("fr", "fr-FR-DeniseNeural", "+0%", "+0%", "+0Hz")


def tone(milliseconds, peak_dbfs, frequency=440):
    return Sine(frequency).to_audio_segment(
        duration=milliseconds,
        volume=peak_dbfs,
    ).set_frame_rate(24000)


def spiky(milliseconds, body_dbfs, click_dbfs, every=300):
    """A quiet tone with short loud clicks: high peak-to-loudness ratio."""

    clip = tone(milliseconds, body_dbfs)

    for start in range(
        50,
        milliseconds - 10,
        every,
    ):
        clip = clip.overlay(
            tone(3, click_dbfs, 1000),
            position=start,
        )

    return clip


def write_wav(directory, name, clip):
    path = Path(directory) / name

    clip.export(
        str(path),
        format="wav",
    )

    return path


def peak_dbfs(path):
    return AudioSegment.from_file(str(path)).max_dBFS


def loudness_of(path):
    lufs, _ = measure_loudness(path)

    return lufs


def check_quiet_clip_is_brought_to_the_target():
    with TemporaryDirectory() as directory:
        source = write_wav(directory, "quiet.wav", tone(2000, -30))
        output = Path(directory) / "out.mp3"

        result = encode_mp3(source, output)

        assert abs(loudness_of(output) - TARGET_LUFS) <= 1.0
        assert not result.limited and not result.at_limit
        assert not result.skipped
        assert result.gain_db > 10
        assert peak_dbfs(output) < -1.0


def check_loud_clip_is_turned_down():
    with TemporaryDirectory() as directory:
        source = write_wav(directory, "loud.wav", tone(2000, -1))
        output = Path(directory) / "out.mp3"

        result = encode_mp3(source, output)

        assert result.gain_db < 0
        assert abs(loudness_of(output) - TARGET_LUFS) <= 1.0


def check_fake_worker_clip_at_minus_30_comes_out_near_the_target():
    with TemporaryDirectory() as directory:
        clip = Path(directory) / "reference.wav"
        clip.write_bytes(b"RIFF-fake-clip")

        provider = PocketProvider(
            {
                "engine_python": sys.executable,
                "models": {"fr": "french"},
                "reference_clips": {"fr": str(clip)},
                "start_timeout_seconds": 20,
                "request_timeout_seconds": 10,
                "idle_shutdown_seconds": 0,
                "worker_script": str(FAKE_WORKER),
            }
        )

        try:
            output = Path(directory) / "segment.mp3"
            provider.synthesize("QUIET30", "fr", PROFILE, output)

        finally:
            provider.close()

        assert abs(loudness_of(output) - TARGET_LUFS) <= 1.0
        assert peak_dbfs(output) < -1.0


def check_a_200_ms_clip_is_normalised_and_not_clipped():
    with TemporaryDirectory() as directory:
        # Under 400 ms there is no integrated loudness; it is measured looped.
        quiet = write_wav(directory, "short.wav", tone(200, -30))
        output = Path(directory) / "short.mp3"

        result = encode_mp3(quiet, output)

        assert result.looped and not result.skipped
        assert abs(
            measure_loudness(output, LOOP_MEASUREMENT_FILTER)[0] - TARGET_LUFS
        ) <= 1.0
        assert peak_dbfs(output) < -0.5
        assert abs(len(AudioSegment.from_file(str(output))) - 200) <= 60

        loud = write_wav(directory, "short-loud.wav", tone(200, -1))
        loud_output = Path(directory) / "short-loud.mp3"

        encode_mp3(loud, loud_output)

        assert peak_dbfs(loud_output) < -0.5


def check_peaky_clip_reaches_the_target_without_clipping():
    with TemporaryDirectory() as directory:
        # Loudness -40ish LUFS with clicks 14 dB above the body: a linear gain
        # to -16 LUFS would put the clicks well over full scale.
        source = write_wav(directory, "peaky.wav", spiky(2400, -36, -22))
        output = Path(directory) / "peaky.mp3"

        result = encode_mp3(source, output)

        assert result.limited
        assert result.input_true_peak_dbtp + result.gain_db > TRUE_PEAK_TARGET_DBTP
        assert peak_dbfs(output) < -0.5

        if not result.at_limit:
            assert abs(loudness_of(output) - TARGET_LUFS) <= 1.0


def check_unreachable_target_is_reported_and_never_clips():
    with TemporaryDirectory() as directory:
        source = write_wav(directory, "extreme.wav", spiky(2400, -50, -8))
        output = Path(directory) / "extreme.mp3"

        result = encode_mp3(source, output)

        assert result.limited and result.at_limit
        assert result.output_lufs < TARGET_LUFS - 2 * CALIBRATION_TOLERANCE_LU
        assert peak_dbfs(output) < -0.5
        # The limiter was never asked for more than its stated bound.
        ceiling_excess = (
            result.input_true_peak_dbtp + result.gain_db
        ) - TRUE_PEAK_TARGET_DBTP
        assert ceiling_excess <= MAXIMUM_LIMITER_DB + abs(
            TRUE_PEAK_TARGET_DBTP
        ) + 0.1


def check_silence_is_left_alone():
    with TemporaryDirectory() as directory:
        source = write_wav(
            directory,
            "silence.wav",
            AudioSegment.silent(duration=1000, frame_rate=24000),
        )
        output = Path(directory) / "silence.mp3"

        result = encode_mp3(source, output)

        assert result.skipped and result.gain_db == 0
        assert output.exists() and output.stat().st_size > 0
        assert peak_dbfs(output) < -60 or AudioSegment.from_file(str(output)).rms == 0


def check_tempo_and_normalisation_combine():
    with TemporaryDirectory() as directory:
        source = write_wav(directory, "tempo.wav", tone(2000, -30))
        output = Path(directory) / "tempo.mp3"

        encode_mp3(source, output, Decimal("2.0"))

        assert abs(len(AudioSegment.from_file(str(output))) - 1000) <= 80
        assert abs(loudness_of(output) - TARGET_LUFS) <= 1.0


def check_existing_mp3_is_normalised_in_place():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "edge.mp3"

        tone(1500, -30).export(
            str(path),
            format="mp3",
        )

        before = path.read_bytes()

        normalise_mp3_in_place(path)

        assert path.read_bytes() != before
        assert abs(loudness_of(path) - TARGET_LUFS) <= 1.0
        assert sorted(item.name for item in Path(directory).iterdir()) == [
            "edge.mp3"
        ]


def check_edge_provider_normalises_what_edge_wrote():
    original = edge_module.create_audio

    def fake_edge(text, voice, output_file, rate="+0%", volume="+0%", pitch="+0Hz"):
        tone(1500, -30).export(
            output_file,
            format="mp3",
        )

        return True

    edge_module.create_audio = fake_edge

    try:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "edge.mp3"

            EdgeProvider().synthesize("bonjour", "fr", PROFILE, output)

            assert abs(loudness_of(output) - TARGET_LUFS) <= 1.0

    finally:
        edge_module.create_audio = original


def check_failed_normalisation_leaves_no_edge_file():
    original = edge_module.create_audio

    def corrupt_edge(text, voice, output_file, rate="+0%", volume="+0%", pitch="+0Hz"):
        Path(output_file).write_bytes(b"not an mp3 at all")

        return True

    edge_module.create_audio = corrupt_edge

    try:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "edge.mp3"

            try:
                EdgeProvider().synthesize("bonjour", "fr", PROFILE, output)

            except Exception as error:
                assert "Normalising Edge audio failed" in str(error)

            else:
                raise AssertionError("A corrupt Edge file was cached.")

            assert not output.exists()
            assert list(Path(directory).iterdir()) == []

    finally:
        edge_module.create_audio = original


def check_loudness_version_is_a_nonempty_string():
    assert isinstance(LOUDNESS_VERSION, str) and LOUDNESS_VERSION
    assert math.isclose(TARGET_LUFS, -16.0)


def run():
    checks = [
        check_quiet_clip_is_brought_to_the_target,
        check_loud_clip_is_turned_down,
        check_fake_worker_clip_at_minus_30_comes_out_near_the_target,
        check_a_200_ms_clip_is_normalised_and_not_clipped,
        check_peaky_clip_reaches_the_target_without_clipping,
        check_unreachable_target_is_reported_and_never_clips,
        check_silence_is_left_alone,
        check_tempo_and_normalisation_combine,
        check_existing_mp3_is_normalised_in_place,
        check_edge_provider_normalises_what_edge_wrote,
        check_failed_normalisation_leaves_no_edge_file,
        check_loudness_version_is_a_nonempty_string,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
