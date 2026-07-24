from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json

import cache
import generator
import stitcher
import structured_audio
from rce_contract import create_rce_speech_plan_job
from settings import AppSettings
from structured_audio import (
    StructuredAudioProcessingError,
    create_structured_track_filename,
    process_structured_job,
)
from structured_processor import resolve_speech_plan


PROVIDER_IDENTITY = {
    "provider": "edge-tts",
    "provider_model": "edge-neural-voices",
    "provider_version": "test-version",
}


def create_segment(
    side,
    **overrides,
):
    segment = {
        "sequence": 1,
        "segmentId": f"{side}-cue:repetition:1",
        "cueId": f"{side}-cue",
        "contentNodeId": f"{side}-content",
        "repetitionNumber": 1,
        "repetitionCount": 1,
        "text": (
            "  faire / agir; (Sport)  "
            if side == "front"
            else "to make"
        ),
        "language": (
            "fr-FR"
            if side == "front"
            else "en-US"
        ),
        "voiceProfileId": "",
        "speakingRate": 1.0,
        "pauseBeforeMilliseconds": 300,
        "pauseAfterMilliseconds": 500,
    }

    segment.update(
        overrides
    )

    return segment


def create_plan(
    side,
    segments=None,
):
    if segments is None:
        segments = [
            create_segment(
                side
            )
        ]

    return json.dumps(
        {
            "schemaVersion": 1,
            "side": side,
            "segments": segments,
        },
        ensure_ascii=False,
    )


def create_note(
    front_segments=None,
    back_segments=None,
):
    if front_segments is None:
        front_segments = [
            create_segment(
                "front"
            )
        ]

    if back_segments is None:
        back_segments = [
            create_segment(
                "back"
            )
        ]

    return {
        "Front": "visual front",
        "Back": "visual back",
        "Front Speech Plan": create_plan(
            "front",
            front_segments,
        ),
        "Back Speech Plan": create_plan(
            "back",
            back_segments,
        ),
        "Front Audio": "",
        "Back Audio": "",
        "Playback Plan": (
            '{"schemaVersion":1}'
        ),
        "Blueprint": "test@1",
        "Theme": "test",
        "RCE Card ID": "rce-card-123",
    }


def expect_audio_error(
    action,
):
    try:
        action()

    except StructuredAudioProcessingError as error:
        return error

    raise AssertionError(
        "Invalid structured audio operation succeeded."
    )


def with_temporary_audio_directories(
    action,
):
    original_cache_dir = cache.CACHE_DIR
    original_output_dir = (
        structured_audio.OUTPUT_DIR
    )

    try:
        with TemporaryDirectory() as directory:
            root = Path(
                directory
            )

            cache.CACHE_DIR = (
                root
                / "cache"
            )

            cache.CACHE_DIR.mkdir(
                parents=True
            )

            structured_audio.OUTPUT_DIR = (
                root
                / "output"
            )

            structured_audio.OUTPUT_DIR.mkdir(
                parents=True
            )

            action(
                root
            )

    finally:
        cache.CACHE_DIR = original_cache_dir
        structured_audio.OUTPUT_DIR = (
            original_output_dir
        )


def check_provider_identity():
    identity = (
        generator.get_edge_provider_identity()
    )

    assert identity[
        "provider"
    ] == "edge-tts"

    assert identity[
        "provider_model"
    ] == "edge-neural-voices"

    assert isinstance(
        identity[
            "provider_version"
        ],
        str,
    )

    assert identity[
        "provider_version"
    ]


def check_structured_cache_identity():
    def check(
        root,
    ):
        base = {
            "provider": "edge-tts",
            "provider_model": "edge-neural-voices",
            "provider_version": "1",
            "text": "faire",
            "language": "fr-FR",
            "profile_key": "fr",
            "voice": "fr-FR-DeniseNeural",
            "rate": "+0%",
            "volume": "+0%",
            "pitch": "+0Hz",
        }

        original = (
            cache.get_structured_audio_path(
                **base
            )
        )

        assert (
            cache.get_structured_audio_path(
                **base
            )
            == original
        )

        for field_name, changed_value in (
            ("provider", "local"),
            ("provider_model", "other"),
            ("provider_version", "2"),
            ("text", "agir"),
            ("language", "fr-CA"),
            ("profile_key", "fr-alt"),
            ("voice", "fr-FR-HenriNeural"),
            ("rate", "+10%"),
            ("volume", "-5%"),
            ("pitch", "+2Hz"),
        ):
            changed = dict(
                base
            )

            changed[
                field_name
            ] = changed_value

            assert (
                cache.get_structured_audio_path(
                    **changed
                )
                != original
            )

        assert original.parent == (
            root
            / "cache"
        )

    with_temporary_audio_directories(
        check
    )


def check_final_filename_identity():
    settings = AppSettings()
    job = create_rce_speech_plan_job(
        create_note()
    )

    track = resolve_speech_plan(
        job[
            "speech_plans"
        ][
            "front"
        ],
        settings,
    )

    first = create_structured_track_filename(
        job[
            "rce_card_id"
        ],
        track,
        PROVIDER_IDENTITY,
    )

    identical = create_structured_track_filename(
        job[
            "rce_card_id"
        ],
        track,
        PROVIDER_IDENTITY,
    )

    assert first == identical
    assert first.startswith(
        "rce_front_"
    )
    assert first.endswith(
        ".mp3"
    )

    changed_provider = dict(
        PROVIDER_IDENTITY
    )

    changed_provider[
        "provider_version"
    ] = "different"

    assert (
        create_structured_track_filename(
            job[
                "rce_card_id"
            ],
            track,
            changed_provider,
        )
        != first
    )

    assert (
        create_structured_track_filename(
            "different-card",
            track,
            PROVIDER_IDENTITY,
        )
        != first
    )

    changed_job = create_rce_speech_plan_job(
        create_note(
            front_segments=[
                create_segment(
                    "front",
                    pauseAfterMilliseconds=650,
                )
            ]
        )
    )

    changed_track = resolve_speech_plan(
        changed_job[
            "speech_plans"
        ][
            "front"
        ],
        settings,
    )

    assert (
        create_structured_track_filename(
            changed_job[
                "rce_card_id"
            ],
            changed_track,
            PROVIDER_IDENTITY,
        )
        != first
    )


def check_repetitions_reuse_cache_and_preserve_schedule():
    original_create_audio = (
        structured_audio.create_audio
    )

    original_stitch = (
        structured_audio.stitch_structured_audio
    )

    original_identity = (
        structured_audio.get_edge_provider_identity
    )

    generated = []
    stitched = []

    def fake_create_audio(
        text,
        voice,
        output_file,
        rate,
        volume,
        pitch,
    ):
        generated.append(
            {
                "text": text,
                "voice": voice,
                "rate": rate,
                "volume": volume,
                "pitch": pitch,
            }
        )

        Path(
            output_file
        ).write_bytes(
            b"segment"
        )

        return True

    def fake_stitch(
        segments,
        output_file,
    ):
        stitched.append(
            deepcopy(
                segments
            )
        )

        Path(
            output_file
        ).write_bytes(
            b"track"
        )

    try:
        structured_audio.create_audio = (
            fake_create_audio
        )

        structured_audio.stitch_structured_audio = (
            fake_stitch
        )

        structured_audio.get_edge_provider_identity = (
            lambda: dict(
                PROVIDER_IDENTITY
            )
        )

        def check(
            root,
        ):
            text = (
                "  faire / agir; (Sport)  "
            )

            job = create_rce_speech_plan_job(
                create_note(
                    front_segments=[
                        create_segment(
                            "front",
                            sequence=1,
                            segmentId="cue:repetition:1",
                            cueId="cue",
                            repetitionNumber=1,
                            repetitionCount=2,
                            text=text,
                            pauseBeforeMilliseconds=650,
                            pauseAfterMilliseconds=600,
                        ),
                        create_segment(
                            "front",
                            sequence=2,
                            segmentId="cue:repetition:2",
                            cueId="cue",
                            repetitionNumber=2,
                            repetitionCount=2,
                            text=text,
                            pauseBeforeMilliseconds=0,
                            pauseAfterMilliseconds=1000,
                        ),
                    ],
                    back_segments=[],
                )
            )

            result = process_structured_job(
                job,
                AppSettings(),
            )

            assert len(
                generated
            ) == 1

            assert generated[0] == {
                "text": text,
                "voice": "fr-FR-DeniseNeural",
                "rate": "+0%",
                "volume": "+0%",
                "pitch": "+0Hz",
            }

            assert result[
                "statistics"
            ] == {
                "generated": 1,
                "cached": 1,
                "skipped": 0,
            }

            assert result[
                "front"
            ].startswith(
                "rce_front_"
            )

            assert result[
                "back"
            ] is None

            assert result[
                "front_processed"
            ] is True

            assert result[
                "back_processed"
            ] is True

            assert result[
                "audio_fields"
            ] == {
                "front": "Front Audio",
                "back": "Back Audio",
            }

            assert len(
                stitched
            ) == 1

            assert [
                (
                    segment[
                        "pause_before_milliseconds"
                    ],
                    segment[
                        "pause_after_milliseconds"
                    ],
                )
                for segment in stitched[0]
            ] == [
                (
                    650,
                    600,
                ),
                (
                    0,
                    1000,
                ),
            ]

            assert (
                root
                / "output"
                / result[
                    "front"
                ]
            ).read_bytes() == b"track"

        with_temporary_audio_directories(
            check
        )

    finally:
        structured_audio.create_audio = (
            original_create_audio
        )

        structured_audio.stitch_structured_audio = (
            original_stitch
        )

        structured_audio.get_edge_provider_identity = (
            original_identity
        )


def check_valid_empty_card():
    original_identity = (
        structured_audio.get_edge_provider_identity
    )

    try:
        structured_audio.get_edge_provider_identity = (
            lambda: dict(
                PROVIDER_IDENTITY
            )
        )

        def check(
            root,
        ):
            result = process_structured_job(
                create_rce_speech_plan_job(
                    create_note(
                        front_segments=[],
                        back_segments=[],
                    )
                ),
                AppSettings(),
            )

            assert result[
                "front"
            ] is None

            assert result[
                "back"
            ] is None

            assert result[
                "statistics"
            ] == {
                "generated": 0,
                "cached": 0,
                "skipped": 0,
            }

            assert list(
                (
                    root
                    / "output"
                ).iterdir()
            ) == []

        with_temporary_audio_directories(
            check
        )

    finally:
        structured_audio.get_edge_provider_identity = (
            original_identity
        )


def check_synthesis_failure_creates_no_final_track():
    original_create_audio = (
        structured_audio.create_audio
    )

    original_stitch = (
        structured_audio.stitch_structured_audio
    )

    original_identity = (
        structured_audio.get_edge_provider_identity
    )

    calls = []

    def fake_create_audio(
        text,
        voice,
        output_file,
        rate,
        volume,
        pitch,
    ):
        calls.append(
            text
        )

        if len(
            calls
        ) == 1:
            Path(
                output_file
            ).write_bytes(
                b"first"
            )

            return True

        Path(
            output_file
        ).write_bytes(
            b"partial"
        )

        return False

    def forbidden_stitch(
        segments,
        output_file,
    ):
        raise AssertionError(
            "Stitching ran after synthesis failure."
        )

    try:
        structured_audio.create_audio = (
            fake_create_audio
        )

        structured_audio.stitch_structured_audio = (
            forbidden_stitch
        )

        structured_audio.get_edge_provider_identity = (
            lambda: dict(
                PROVIDER_IDENTITY
            )
        )

        def check(
            root,
        ):
            job = create_rce_speech_plan_job(
                create_note(
                    front_segments=[
                        create_segment(
                            "front",
                            sequence=1,
                            segmentId="first",
                            text="first",
                        ),
                        create_segment(
                            "front",
                            sequence=2,
                            segmentId="second",
                            text="second",
                        ),
                    ],
                    back_segments=[],
                )
            )

            error = expect_audio_error(
                lambda: process_structured_job(
                    job,
                    AppSettings(),
                )
            )

            message = str(
                error
            )

            assert (
                "after retries"
                in message
            )
            assert (
                '"rce-card-123"'
                in message
            )
            assert (
                '"second"'
                in message
            )
            assert (
                'text "second"'
                in message
            )
            assert (
                'language "fr-FR"'
                in message
            )
            assert (
                'voice "fr-FR-DeniseNeural"'
                in message
            )
            assert (
                'rate "+0%"'
                in message
            )

            assert list(
                (
                    root
                    / "output"
                ).iterdir()
            ) == []

            assert all(
                path.stat().st_size > 0
                for path in (
                    root
                    / "cache"
                ).iterdir()
            )

            assert len(
                list(
                    (
                        root
                        / "cache"
                    ).iterdir()
                )
            ) == 1

        with_temporary_audio_directories(
            check
        )

    finally:
        structured_audio.create_audio = (
            original_create_audio
        )

        structured_audio.stitch_structured_audio = (
            original_stitch
        )

        structured_audio.get_edge_provider_identity = (
            original_identity
        )


def check_synthesis_exception_removes_partial_cache():
    original_create_audio = (
        structured_audio.create_audio
    )

    original_identity = (
        structured_audio.get_edge_provider_identity
    )

    def failing_create_audio(
        text,
        voice,
        output_file,
        rate,
        volume,
        pitch,
    ):
        Path(
            output_file
        ).write_bytes(
            b"partial"
        )

        raise RuntimeError(
            "provider failed"
        )

    try:
        structured_audio.create_audio = (
            failing_create_audio
        )

        structured_audio.get_edge_provider_identity = (
            lambda: dict(
                PROVIDER_IDENTITY
            )
        )

        def check(
            root,
        ):
            expect_audio_error(
                lambda: process_structured_job(
                    create_rce_speech_plan_job(
                        create_note(
                            back_segments=[]
                        )
                    ),
                    AppSettings(),
                )
            )

            assert list(
                (
                    root
                    / "cache"
                ).iterdir()
            ) == []

            assert list(
                (
                    root
                    / "output"
                ).iterdir()
            ) == []

        with_temporary_audio_directories(
            check
        )

    finally:
        structured_audio.create_audio = (
            original_create_audio
        )

        structured_audio.get_edge_provider_identity = (
            original_identity
        )


def check_stitch_failure_removes_pending_tracks():
    original_create_audio = (
        structured_audio.create_audio
    )

    original_stitch = (
        structured_audio.stitch_structured_audio
    )

    original_identity = (
        structured_audio.get_edge_provider_identity
    )

    def fake_create_audio(
        text,
        voice,
        output_file,
        rate,
        volume,
        pitch,
    ):
        Path(
            output_file
        ).write_bytes(
            b"segment"
        )

        return True

    def failing_stitch(
        segments,
        output_file,
    ):
        Path(
            output_file
        ).write_bytes(
            b"partial track"
        )

        raise RuntimeError(
            "stitch failed"
        )

    try:
        structured_audio.create_audio = (
            fake_create_audio
        )

        structured_audio.stitch_structured_audio = (
            failing_stitch
        )

        structured_audio.get_edge_provider_identity = (
            lambda: dict(
                PROVIDER_IDENTITY
            )
        )

        def check(
            root,
        ):
            expect_audio_error(
                lambda: process_structured_job(
                    create_rce_speech_plan_job(
                        create_note()
                    ),
                    AppSettings(),
                )
            )

            assert list(
                (
                    root
                    / "output"
                ).iterdir()
            ) == []

        with_temporary_audio_directories(
            check
        )

    finally:
        structured_audio.create_audio = (
            original_create_audio
        )

        structured_audio.stitch_structured_audio = (
            original_stitch
        )

        structured_audio.get_edge_provider_identity = (
            original_identity
        )


def check_resolution_failure_precedes_synthesis():
    original_create_audio = (
        structured_audio.create_audio
    )

    called = []

    def forbidden_create_audio(
        *args,
        **kwargs,
    ):
        called.append(
            True
        )

        return True

    try:
        structured_audio.create_audio = (
            forbidden_create_audio
        )

        job = create_rce_speech_plan_job(
            create_note(
                front_segments=[
                    create_segment(
                        "front",
                        voiceProfileId="unknown-profile",
                    )
                ],
                back_segments=[],
            )
        )

        expect_audio_error(
            lambda: process_structured_job(
                job,
                AppSettings(),
            )
        )

        assert called == []

    finally:
        structured_audio.create_audio = (
            original_create_audio
        )


def check_invalid_job_contract():
    for job in (
        None,
        {},
        {
            "job_type": "fields",
        },
        {
            "job_type": "rce_speech_plan",
        },
    ):
        expect_audio_error(
            lambda job=job: process_structured_job(
                job,
                AppSettings(),
            )
        )


def check_exact_pause_stitching_and_atomic_export():
    original_audio_segment = (
        stitcher.AudioSegment
    )

    original_trim = (
        stitcher.trim_trailing_silence
    )

    exported_events = []

    class FakeAudio:
        def __init__(
            self,
            events=None,
        ):
            self.events = list(
                events
                or []
            )

        def __iadd__(
            self,
            other,
        ):
            self.events.extend(
                other.events
            )

            return self

        def export(
            self,
            output_file,
            format,
        ):
            exported_events.extend(
                self.events
            )

            Path(
                output_file
            ).write_bytes(
                b"mp3"
            )

    class FakeAudioSegment:
        @staticmethod
        def empty():
            return FakeAudio()

        @staticmethod
        def silent(
            duration,
        ):
            return FakeAudio(
                [
                    (
                        "silence",
                        duration,
                    )
                ]
            )

        @staticmethod
        def from_file(
            path,
        ):
            return FakeAudio(
                [
                    (
                        "audio",
                        path,
                    )
                ]
            )

    try:
        stitcher.AudioSegment = (
            FakeAudioSegment
        )

        stitcher.trim_trailing_silence = (
            lambda audio: audio
        )

        with TemporaryDirectory() as directory:
            output_file = (
                Path(
                    directory
                )
                / "track.mp3"
            )

            stitcher.stitch_structured_audio(
                [
                    {
                        "file": "first.mp3",
                        "pause_before_milliseconds": 300,
                        "pause_after_milliseconds": 500,
                    },
                    {
                        "file": "second.mp3",
                        "pause_before_milliseconds": 650,
                        "pause_after_milliseconds": 0,
                    },
                ],
                output_file,
            )

            assert exported_events == [
                (
                    "silence",
                    300,
                ),
                (
                    "audio",
                    "first.mp3",
                ),
                (
                    "silence",
                    500,
                ),
                (
                    "silence",
                    650,
                ),
                (
                    "audio",
                    "second.mp3",
                ),
            ]

            assert output_file.read_bytes() == b"mp3"

            assert not (
                Path(
                    directory
                )
                / ".track.mp3.tmp"
            ).exists()

    finally:
        stitcher.AudioSegment = (
            original_audio_segment
        )

        stitcher.trim_trailing_silence = (
            original_trim
        )


def check_failed_stitch_export_is_not_published():
    original_audio_segment = (
        stitcher.AudioSegment
    )

    original_trim = (
        stitcher.trim_trailing_silence
    )

    class FailingAudio:
        def __iadd__(
            self,
            other,
        ):
            return self

        def export(
            self,
            output_file,
            format,
        ):
            Path(
                output_file
            ).write_bytes(
                b"partial"
            )

            raise RuntimeError(
                "export failed"
            )

    class FakeAudioSegment:
        @staticmethod
        def empty():
            return FailingAudio()

        @staticmethod
        def silent(
            duration,
        ):
            return FailingAudio()

        @staticmethod
        def from_file(
            path,
        ):
            return FailingAudio()

    try:
        stitcher.AudioSegment = (
            FakeAudioSegment
        )

        stitcher.trim_trailing_silence = (
            lambda audio: audio
        )

        with TemporaryDirectory() as directory:
            output_file = (
                Path(
                    directory
                )
                / "track.mp3"
            )

            try:
                stitcher.stitch_structured_audio(
                    [
                        {
                            "file": "segment.mp3",
                            "pause_before_milliseconds": 0,
                            "pause_after_milliseconds": 500,
                        }
                    ],
                    output_file,
                )

            except RuntimeError:
                pass
            else:
                raise AssertionError(
                    "Failed structured export succeeded."
                )

            assert not output_file.exists()

            assert not (
                Path(
                    directory
                )
                / ".track.mp3.tmp"
            ).exists()

    finally:
        stitcher.AudioSegment = (
            original_audio_segment
        )

        stitcher.trim_trailing_silence = (
            original_trim
        )


def run():
    checks = [
        check_provider_identity,
        check_structured_cache_identity,
        check_final_filename_identity,
        check_repetitions_reuse_cache_and_preserve_schedule,
        check_valid_empty_card,
        check_synthesis_failure_creates_no_final_track,
        check_synthesis_exception_removes_partial_cache,
        check_stitch_failure_removes_pending_tracks,
        check_resolution_failure_precedes_synthesis,
        check_invalid_job_contract,
        check_exact_pause_stitching_and_atomic_export,
        check_failed_stitch_export_is_not_published,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
