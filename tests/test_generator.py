from pathlib import Path
from tempfile import TemporaryDirectory

import generator


def check_no_audio_is_skipped():
    original_generate_audio = (
        generator.generate_audio
    )
    original_sleep = (
        generator.time.sleep
    )
    attempts = []
    delays = []

    async def raise_no_audio(
        text,
        voice,
        output_file,
        rate="+0%",
        volume="+0%",
        pitch="+0Hz",
    ):
        attempts.append(
            text
        )

        Path(
            output_file
        ).write_bytes(
            b"partial"
        )

        raise generator.NoAudioReceived(
            "No audio received."
        )

    try:
        generator.generate_audio = (
            raise_no_audio
        )
        generator.time.sleep = (
            lambda delay: delays.append(
                delay
            )
        )

        with TemporaryDirectory() as directory:
            output_file = (
                Path(
                    directory
                )
                / "audio.mp3"
            )

            result = generator.create_audio(
                text="!!!???",
                voice="en-US-JennyNeural",
                output_file=output_file,
            )

            assert result is False
            assert not output_file.exists()
            assert len(
                attempts
            ) == (
                generator
                .EDGE_NO_AUDIO_MAX_ATTEMPTS
            )
            assert delays == list(
                generator
                .EDGE_NO_AUDIO_RETRY_DELAYS
            )

    finally:
        generator.generate_audio = (
            original_generate_audio
        )
        generator.time.sleep = (
            original_sleep
        )


def check_transient_no_audio_is_retried():
    original_generate_audio = (
        generator.generate_audio
    )
    original_sleep = (
        generator.time.sleep
    )
    attempts = []
    delays = []

    async def create_after_retry(
        text,
        voice,
        output_file,
        rate="+0%",
        volume="+0%",
        pitch="+0Hz",
    ):
        attempts.append(
            text
        )

        if len(
            attempts
        ) < 3:
            Path(
                output_file
            ).write_bytes(
                b"partial"
            )

            raise generator.NoAudioReceived(
                "No audio received."
            )

        Path(
            output_file
        ).write_bytes(
            b"audio"
        )

    try:
        generator.generate_audio = (
            create_after_retry
        )
        generator.time.sleep = (
            lambda delay: delays.append(
                delay
            )
        )

        with TemporaryDirectory() as directory:
            output_file = (
                Path(
                    directory
                )
                / "audio.mp3"
            )

            result = generator.create_audio(
                text="Hello",
                voice="en-US-JennyNeural",
                output_file=output_file,
            )

            assert result is True
            assert len(
                attempts
            ) == 3
            assert delays == [
                1.0,
                2.0,
            ]
            assert output_file.read_bytes() == b"audio"

    finally:
        generator.generate_audio = (
            original_generate_audio
        )
        generator.time.sleep = (
            original_sleep
        )


def check_success_is_reported():
    original_generate_audio = (
        generator.generate_audio
    )

    async def create_test_audio(
        text,
        voice,
        output_file,
        rate="+0%",
        volume="+0%",
        pitch="+0Hz",
    ):
        Path(
            output_file
        ).write_bytes(
            b"audio"
        )

    try:
        generator.generate_audio = (
            create_test_audio
        )

        with TemporaryDirectory() as directory:
            output_file = (
                Path(
                    directory
                )
                / "audio.mp3"
            )

            result = generator.create_audio(
                text="Hello",
                voice="en-US-JennyNeural",
                output_file=output_file,
            )

            assert result is True
            assert output_file.read_bytes() == b"audio"

    finally:
        generator.generate_audio = (
            original_generate_audio
        )


def run():
    checks = [
        check_no_audio_is_skipped,
        check_transient_no_audio_is_retried,
        check_success_is_reported,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
