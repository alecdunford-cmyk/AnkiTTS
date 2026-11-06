from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from pydub import AudioSegment
from pydub.generators import Sine

import earcons
from earcons import (
    DEFAULT_TONES,
    EARCON_TARGET_LUFS,
    default_earcon_path,
    ensure_default_earcon,
    measure_earcon_loudness,
    resolve_earcon_path,
)
from providers import registry
from rce_contract import create_rce_speech_plan_job
from settings import (
    AppSettings,
    DEFAULT_EARCONS,
    EARCON_ROLES,
    TempoProfile,
)
from speech_plan import VALID_EARCONS
from stitcher import (
    EARCON_GAP_MS,
    stitch_structured_audio,
)
from structured_audio import process_structured_job
from tests.test_role_voices import (
    RecordingEdge,
    v2_note,
    v2_segment,
    with_directories,
)


TEMPO = TempoProfile(
    Decimal("1"),
    Decimal("0.35"),
    250,
    1200,
    700,
)


def dominant_frequency(
    audio,
):
    """Zero crossings per second over two is a tone's frequency."""

    samples = audio.get_array_of_samples()

    crossings = sum(
        1
        for first, second in zip(
            samples,
            samples[1:],
        )
        if (first < 0) != (second < 0)
    )

    return crossings / 2 / (
        len(
            samples
        )
        / audio.frame_rate
    )


def with_earcon_directory(
    action,
):
    original = os.environ.get(
        "ANKITTS_EARCON_DIR"
    )

    try:
        with TemporaryDirectory() as directory:
            os.environ[
                "ANKITTS_EARCON_DIR"
            ] = directory

            action(
                Path(
                    directory
                )
            )

    finally:
        if original is None:
            os.environ.pop(
                "ANKITTS_EARCON_DIR",
                None,
            )
        else:
            os.environ[
                "ANKITTS_EARCON_DIR"
            ] = original


def check_earcon_names_match_the_plan_schema():
    assert EARCON_ROLES == VALID_EARCONS
    assert set(
        DEFAULT_TONES
    ) == set(
        EARCON_ROLES
    )


def check_default_tones_meet_the_specification():
    def action(
        directory,
    ):
        frequencies = {}

        for role in EARCON_ROLES:
            path = ensure_default_earcon(
                role
            )

            assert path.parent == directory

            audio = AudioSegment.from_file(
                str(
                    path
                )
            )

            # 120 to 250 ms, sine-based, -20 LUFS, unclipped.
            assert 120 <= len(
                audio
            ) <= 250, f"{role}: {len(audio)} ms"

            lufs = measure_earcon_loudness(
                path
            )

            assert abs(
                lufs
                - EARCON_TARGET_LUFS
            ) <= 1.0, f"{role}: {lufs} LUFS"

            assert audio.max_dBFS < -1.0

            frequencies[
                role
            ] = dominant_frequency(
                audio
            )

        # Distinct pitches: the tick above the rising tone above the flip.
        assert (
            frequencies[
                "sectionBoundary"
            ]
            > 1.5
            * frequencies[
                "answerStart"
            ]
        )

        assert (
            frequencies[
                "answerStart"
            ]
            > 1.3
            * frequencies[
                "directionFlip"
            ]
        )

    with_earcon_directory(
        action
    )


def check_answer_start_rises():
    def action(
        _directory,
    ):
        audio = AudioSegment.from_file(
            str(
                ensure_default_earcon(
                    "answerStart"
                )
            )
        )

        middle = len(
            audio
        ) // 2

        assert dominant_frequency(
            audio[
                middle:
            ]
        ) > dominant_frequency(
            audio[
                :middle
            ]
        )

    with_earcon_directory(
        action
    )


def check_defaults_are_generated_only_once():
    def action(
        _directory,
    ):
        generated = []
        original = earcons._generate

        def counting(
            role,
            path,
        ):
            generated.append(
                role
            )

            original(
                role,
                path,
            )

        earcons._generate = counting

        try:
            first = ensure_default_earcon(
                "directionFlip"
            )

            before = first.read_bytes()

            ensure_default_earcon(
                "directionFlip"
            )

            assert generated == [
                "directionFlip",
            ]

            assert first.read_bytes() == before

            first.unlink()

            ensure_default_earcon(
                "directionFlip"
            )

            assert generated == [
                "directionFlip",
                "directionFlip",
            ]

        finally:
            earcons._generate = original

    with_earcon_directory(
        action
    )


def check_unknown_role_is_an_error():
    try:
        ensure_default_earcon(
            "ding"
        )

    except ValueError:
        return

    raise AssertionError(
        "An unknown earcon was accepted."
    )


def check_settings_merge_and_validate():
    settings = AppSettings()

    assert settings.earcons == DEFAULT_EARCONS

    partial = AppSettings.from_dict(
        {
            "earcons": {
                "answerStart": "  C:/sounds/up.wav ",
            },
        }
    )

    assert partial.earcons == {
        "sectionBoundary": "",
        "answerStart": "C:/sounds/up.wav",
        "directionFlip": "",
    }

    assert (
        AppSettings.from_dict(
            json.loads(
                json.dumps(
                    asdict(
                        partial
                    )
                )
            )
        ).earcons
        == partial.earcons
    )

    for bad in (
        "up.wav",
        {
            "ding": "up.wav",
        },
        {
            "answerStart": 1,
        },
    ):
        try:
            AppSettings.from_dict(
                {
                    "earcons": bad,
                }
            )

        except ValueError:
            continue

        raise AssertionError(
            f"Bad earcons accepted: {bad!r}"
        )

    with (
        Path(__file__).resolve().parent.parent
        / "addon"
        / "config.json"
    ).open(
        encoding="utf-8",
    ) as config_file:
        assert json.load(
            config_file
        )[
            "earcons"
        ] == DEFAULT_EARCONS


def check_configured_file_wins_and_a_missing_one_falls_back():
    def action(
        directory,
    ):
        replacement = directory / "mine.mp3"

        Sine(600).to_audio_segment(
            duration=200,
            volume=-20,
        ).export(
            str(
                replacement
            ),
            format="mp3",
        )

        assert (
            resolve_earcon_path(
                "answerStart",
                AppSettings.from_dict(
                    {
                        "earcons": {
                            "answerStart": str(
                                replacement
                            ),
                        },
                    }
                ),
            )
            == replacement
        )

        assert (
            resolve_earcon_path(
                "answerStart",
                AppSettings.from_dict(
                    {
                        "earcons": {
                            "answerStart": str(
                                directory
                                / "moved-away.wav"
                            ),
                        },
                    }
                ),
            )
            == default_earcon_path(
                "answerStart"
            )
        )

    with_earcon_directory(
        action
    )


def check_stitcher_places_earcons_around_the_speech():
    def action(
        directory,
    ):
        clip = directory / "clip.mp3"

        Sine(440).to_audio_segment(
            duration=600,
            volume=-20,
        ).set_frame_rate(
            24000
        ).export(
            str(
                clip
            ),
            format="mp3",
            bitrate="96k",
        )

        before_file = ensure_default_earcon(
            "answerStart"
        )

        after_file = ensure_default_earcon(
            "directionFlip"
        )

        track = directory / "track.mp3"

        timeline = stitch_structured_audio(
            [
                {
                    "file": str(
                        clip
                    ),
                    "pause_before_milliseconds": 200,
                    "pause_after_milliseconds": 300,
                    "pause_before": None,
                    "pause_after": None,
                    "tempo": TEMPO,
                    "earcon_before": str(
                        before_file
                    ),
                    "earcon_after": str(
                        after_file
                    ),
                }
            ],
            track,
        )

        assert [
            event[
                "kind"
            ]
            for event in timeline
        ] == [
            "pause_before",
            "earcon_before",
            "earcon_gap",
            "speech",
            "earcon_gap",
            "earcon_after",
            "pause_after",
        ]

        assert abs(
            timeline[2][
                "duration_ms"
            ]
            - EARCON_GAP_MS
        ) <= 2

        stitched = AudioSegment.from_file(
            str(
                track
            )
        )

        # The earcon sounds where the timeline says (with the MP3's delay).
        start = timeline[1][
            "start_ms"
        ]

        assert stitched[
            :start - 20
        ].dBFS < -60

        rising = stitched[
            start
            + 40 : start
            + 200
        ]

        assert rising.dBFS > -40

        assert 480 < dominant_frequency(
            rising
        ) < 860

        flip = timeline[5]

        flipped = stitched[
            flip[
                "start_ms"
            ]
            + 40 : flip[
                "start_ms"
            ]
            + flip[
                "duration_ms"
            ]
        ]

        assert 340 < dominant_frequency(
            flipped
        ) < 440

    with_earcon_directory(
        action
    )


def check_earcons_stay_out_of_segment_keys_and_in_the_track_identity():
    def directory_action(
        directory,
    ):
        def action():
            edge = RecordingEdge()

            registry.set_override_chain(
                [
                    edge,
                ]
            )

            def job(
                **earcon,
            ):
                return create_rce_speech_plan_job(
                    v2_note(
                        [
                            v2_segment(
                                1,
                                "le phare",
                                "fr-FR",
                                "content",
                                **earcon,
                            ),
                        ],
                        [],
                    )
                )

            plain = process_structured_job(
                job(),
                AppSettings(),
            )

            assert plain[
                "statistics"
            ][
                "generated"
            ] == 1

            with_earcon = process_structured_job(
                job(
                    earconBefore="answerStart",
                ),
                AppSettings(),
            )

            # The same audio serves both; only the track changes.
            assert with_earcon[
                "statistics"
            ] == {
                "generated": 0,
                "cached": 1,
                "skipped": 0,
            }

            assert with_earcon[
                "front"
            ] != plain[
                "front"
            ]

            replacement = directory / "mine.wav"

            shutil.copy(
                ensure_default_earcon(
                    "directionFlip"
                ),
                replacement,
            )

            replaced = process_structured_job(
                job(
                    earconBefore="answerStart",
                ),
                AppSettings.from_dict(
                    {
                        "earcons": {
                            "answerStart": str(
                                replacement
                            ),
                        },
                    }
                ),
            )

            assert replaced[
                "statistics"
            ][
                "generated"
            ] == 0

            assert replaced[
                "front"
            ] != with_earcon[
                "front"
            ]

            # A different earcon in an unrelated slot changes nothing here.
            unrelated = process_structured_job(
                job(
                    earconBefore="answerStart",
                ),
                AppSettings.from_dict(
                    {
                        "earcons": {
                            "sectionBoundary": str(
                                replacement
                            ),
                        },
                    }
                ),
            )

            assert unrelated[
                "front"
            ] == with_earcon[
                "front"
            ]

        with_directories(
            action
        )

    with_earcon_directory(
        directory_action
    )


def check_v1_plans_never_generate_earcons():
    def directory_action(
        directory,
    ):
        def action():
            registry.set_override_chain(
                [
                    RecordingEdge(),
                ]
            )

            segment = {
                key: value
                for key, value in v2_segment(
                    1,
                    "le phare",
                    "fr-FR",
                    "content",
                ).items()
                if key
                not in (
                    "role",
                    "voiceRole",
                )
            }

            note = v2_note(
                [],
                [],
            )

            note[
                "Front Speech Plan"
            ] = json.dumps(
                {
                    "schemaVersion": 1,
                    "side": "front",
                    "segments": [
                        segment,
                    ],
                }
            )

            process_structured_job(
                create_rce_speech_plan_job(
                    note
                ),
                AppSettings(),
            )

            assert list(
                directory.iterdir()
            ) == []

        with_directories(
            action
        )

    with_earcon_directory(
        directory_action
    )


def run():
    checks = [
        check_earcon_names_match_the_plan_schema,
        check_default_tones_meet_the_specification,
        check_answer_start_rises,
        check_defaults_are_generated_only_once,
        check_unknown_role_is_an_error,
        check_settings_merge_and_validate,
        check_configured_file_wins_and_a_missing_one_falls_back,
        check_stitcher_places_earcons_around_the_speech,
        check_earcons_stay_out_of_segment_keys_and_in_the_track_identity,
        check_v1_plans_never_generate_earcons,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
