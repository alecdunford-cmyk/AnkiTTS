from pathlib import Path
from tempfile import TemporaryDirectory

import generator


def check_no_audio_is_skipped():
    original_generate_audio = (
        generator.generate_audio
    )

    async def raise_no_audio(
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
            b"partial"
        )

        raise generator.NoAudioReceived(
            "No audio received."
        )

    try:
        generator.generate_audio = (
            raise_no_audio
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

    finally:
        generator.generate_audio = (
            original_generate_audio
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
        check_success_is_reported,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")