from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pydub import AudioSegment
from pydub.generators import Sine

from providers import registry
from rce_contract import create_rce_speech_plan_job
from settings import (
    AppSettings,
    DEFAULT_TEMPO_PROFILES,
    TempoProfile,
)
from speech_plan import (
    PauseSpec,
    parse_speech_plan,
)
from stitcher import (
    TRIM_SAFETY_MARGIN_MS,
    resolve_pause_milliseconds,
    stitch_structured_audio,
)
from structured_audio import process_structured_job
from structured_processor import resolve_speech_plan
from tests.test_role_voices import (
    RecordingEdge,
    v2_note,
    v2_plan,
    v2_segment,
    with_directories,
)


# The design note's table, section 4, in its order: rate, pauseFactor,
# minPauseMs, maxPauseMs, boundaryPauseMs.
NOTE_TABLE = {
    "default": (1.00, 0.35, 250, 1200, 700),
    "deep-entry-study": (1.00, 0.35, 250, 1200, 900),
    "deep-recall": (0.95, 0.45, 300, 1500, 900),
    "sense-map": (1.00, 0.30, 200, 1000, 600),
    "translation-group": (1.00, 0.30, 200, 1000, 600),
    "example": (1.00, 0.30, 200, 1000, 600),
    "sentence": (1.00, 0.30, 200, 1000, 600),
}

DEFAULT_TEMPO = TempoProfile(
    Decimal("1"),
    Decimal("0.35"),
    250,
    1200,
    700,
)


def tone_file(
    path,
    milliseconds,
):
    Sine(440).to_audio_segment(
        duration=milliseconds,
        volume=-20,
    ).set_frame_rate(
        24000
    ).export(
        str(
            path
        ),
        format="mp3",
        bitrate="96k",
    )

    return str(
        path
    )


def check_defaults_are_the_design_notes_table():
    settings = AppSettings()

    settings.validate()

    assert list(
        DEFAULT_TEMPO_PROFILES
    ) == list(
        NOTE_TABLE
    )

    for name, row in NOTE_TABLE.items():
        profile = settings.get_tempo_profile(
            name
        )

        assert (
            float(
                profile.rate
            ),
            float(
                profile.pause_factor
            ),
            profile.min_pause_ms,
            profile.max_pause_ms,
            profile.boundary_pause_ms,
        ) == row


def check_config_json_ships_the_table():
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
            "tempo_profiles"
        ] == DEFAULT_TEMPO_PROFILES


def check_unknown_profile_name_is_default():
    settings = AppSettings()

    assert settings.get_tempo_profile(
        "no-such-preset"
    ) == settings.get_tempo_profile(
        "default"
    )

    track = resolve_speech_plan(
        parse_speech_plan(
            json.dumps(
                dict(
                    json.loads(
                        v2_plan(
                            "back",
                            [
                                v2_segment(
                                    1,
                                    "le phare",
                                    "fr-FR",
                                    "content",
                                )
                            ],
                        )
                    ),
                    tempoProfile="no-such-preset",
                )
            ),
            "back",
        ),
        settings,
    )

    assert track.tempo == settings.get_tempo_profile(
        "default"
    )


def check_table_merges_and_round_trips():
    settings = AppSettings.from_dict(
        {
            "tempo_profiles": {
                "deep-recall": {
                    "rate": 0.9,
                },
                "my-preset": {
                    "boundaryPauseMs": 1500,
                },
            },
        }
    )

    recall = settings.get_tempo_profile(
        "deep-recall"
    )

    assert recall.rate == Decimal(
        "0.9"
    )
    assert recall.pause_factor == Decimal(
        "0.45"
    )

    mine = settings.get_tempo_profile(
        "my-preset"
    )

    assert mine.boundary_pause_ms == 1500
    assert mine.max_pause_ms == 1200

    assert (
        AppSettings.from_dict(
            json.loads(
                json.dumps(
                    asdict(
                        settings
                    )
                )
            )
        ).tempo_profiles
        == settings.tempo_profiles
    )


def check_legacy_config_gets_the_table():
    assert (
        AppSettings.from_dict(
            {
                "voices": {
                    "fr": "fr-FR-DeniseNeural",
                },
            }
        ).tempo_profiles
        == DEFAULT_TEMPO_PROFILES
    )


def check_bad_table_values_are_errors():
    for bad in (
        "fast",
        {
            "x": "fast",
        },
        {
            "x": {
                "rate": 0,
            },
        },
        {
            "x": {
                "rate": "1.0",
            },
        },
        {
            "x": {
                "rate": True,
            },
        },
        {
            "x": {
                "pauseFactor": -1,
            },
        },
        {
            "x": {
                "minPauseMs": -1,
            },
        },
        {
            "x": {
                "maxPauseMs": 1.5,
            },
        },
        {
            "x": {
                "minPauseMs": 900,
                "maxPauseMs": 800,
            },
        },
        {
            "x": {
                "speed": 1,
            },
        },
        {
            " ": {},
        },
    ):
        try:
            AppSettings.from_dict(
                {
                    "tempo_profiles": bad,
                }
            )

        except ValueError:
            continue

        raise AssertionError(
            f"Bad tempo table accepted: {bad!r}"
        )


def check_pause_kinds():
    assert resolve_pause_milliseconds(
        PauseSpec(
            "none"
        ),
        2000,
        DEFAULT_TEMPO,
    ) == 0

    assert resolve_pause_milliseconds(
        PauseSpec(
            "fixed",
            milliseconds=900,
        ),
        2000,
        DEFAULT_TEMPO,
    ) == 900

    # Fixed is exact: the clamp is for proportional pauses only.
    assert resolve_pause_milliseconds(
        PauseSpec(
            "fixed",
            milliseconds=5000,
        ),
        2000,
        DEFAULT_TEMPO,
    ) == 5000

    assert resolve_pause_milliseconds(
        PauseSpec(
            "boundary"
        ),
        2000,
        DEFAULT_TEMPO,
    ) == 700


def check_proportional_formula_and_clamp():
    one = PauseSpec(
        "proportional",
        scale=Decimal(
            "1.0"
        ),
    )

    # clamp(scale x pauseFactor x segmentAudioMs, min, max)
    assert resolve_pause_milliseconds(
        one,
        2000,
        DEFAULT_TEMPO,
    ) == 700

    assert resolve_pause_milliseconds(
        one,
        100,
        DEFAULT_TEMPO,
    ) == 250

    assert resolve_pause_milliseconds(
        one,
        10000,
        DEFAULT_TEMPO,
    ) == 1200

    assert resolve_pause_milliseconds(
        PauseSpec(
            "proportional",
            scale=Decimal(
                "2"
            ),
        ),
        1000,
        DEFAULT_TEMPO,
    ) == 700


def check_stitched_pauses_come_from_the_trimmed_speech():
    with TemporaryDirectory() as directory:
        root = Path(
            directory
        )

        clip = root / "clip.mp3"

        # 2 s of speech then 800 ms of silence, as Edge clips end.
        (
            Sine(440).to_audio_segment(
                duration=2000,
                volume=-20,
            )
            + AudioSegment.silent(
                duration=800,
            )
        ).set_frame_rate(
            24000
        ).export(
            str(
                clip
            ),
            format="mp3",
            bitrate="96k",
        )

        track = root / "track.mp3"

        timeline = stitch_structured_audio(
            [
                {
                    "file": str(
                        clip
                    ),
                    "pause_before_milliseconds": 0,
                    "pause_after_milliseconds": 0,
                    "pause_before": PauseSpec(
                        "boundary"
                    ),
                    "pause_after": PauseSpec(
                        "proportional",
                        scale=Decimal(
                            "1.0"
                        ),
                    ),
                    "tempo": DEFAULT_TEMPO,
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
            "speech",
            "pause_after",
        ]

        before, speech, after = timeline

        assert abs(
            before[
                "duration_ms"
            ]
            - 700
        ) <= 2

        # The trailing silence is trimmed before the duration is measured:
        # 2000 ms, plus the margin and the MP3's padding, not 2800 ms.
        assert speech[
            "duration_ms"
        ] < 2000 + TRIM_SAFETY_MARGIN_MS + 120

        assert abs(
            after[
                "duration_ms"
            ]
            - round(
                0.35
                * speech[
                    "duration_ms"
                ]
            )
        ) <= 2

        assert abs(
            len(
                AudioSegment.from_file(
                    str(
                        track
                    )
                )
            )
            - (
                before[
                    "duration_ms"
                ]
                + speech[
                    "duration_ms"
                ]
                + after[
                    "duration_ms"
                ]
            )
        ) <= 60


def check_absent_pause_uses_the_v1_milliseconds():
    with TemporaryDirectory() as directory:
        root = Path(
            directory
        )

        timeline = stitch_structured_audio(
            [
                {
                    "file": tone_file(
                        root / "clip.mp3",
                        500,
                    ),
                    "pause_before_milliseconds": 120,
                    "pause_after_milliseconds": 340,
                    "pause_before": None,
                    "pause_after": PauseSpec(
                        "none"
                    ),
                    "tempo": DEFAULT_TEMPO,
                }
            ],
            root / "track.mp3",
        )

        # pauseBefore absent: the v1 field. pauseAfter present: it wins.
        assert [
            event[
                "kind"
            ]
            for event in timeline
        ] == [
            "pause_before",
            "speech",
        ]

        assert abs(
            timeline[0][
                "duration_ms"
            ]
            - 120
        ) <= 2


def check_v1_stitch_input_keeps_exact_pauses():
    with TemporaryDirectory() as directory:
        root = Path(
            directory
        )

        track = root / "track.mp3"

        timeline = stitch_structured_audio(
            [
                {
                    "file": tone_file(
                        root / "clip.mp3",
                        500,
                    ),
                    "pause_before_milliseconds": 300,
                    "pause_after_milliseconds": 900,
                }
            ],
            track,
        )

        assert timeline == []

        stitched = AudioSegment.from_file(
            str(
                track
            )
        )

        assert abs(
            len(
                stitched
            )
            - (
                300
                + 500
                + 900
            )
        ) <= 120

        assert stitched[
            :250
        ].dBFS < -60

        assert stitched[
            350:750
        ].dBFS > -30


def plan_job(
    segments,
):
    return create_rce_speech_plan_job(
        v2_note(
            segments,
            [],
        )
    )


def recall_segments():
    return [
        v2_segment(
            1,
            "le phare",
            "fr-FR",
            "content",
            pauseAfter={
                "kind": "proportional",
                "scale": 1.0,
            },
        ),
    ]


def recall_job():
    note = v2_note(
        recall_segments(),
        [],
    )

    plan = json.loads(
        note[
            "Front Speech Plan"
        ]
    )

    plan[
        "tempoProfile"
    ] = "deep-recall"

    note[
        "Front Speech Plan"
    ] = json.dumps(
        plan
    )

    return create_rce_speech_plan_job(
        note
    )


def check_tempo_rate_composes_into_the_synthesis_rate():
    def action():
        edge = RecordingEdge()

        registry.set_override_chain(
            [
                edge,
            ]
        )

        process_structured_job(
            recall_job(),
            AppSettings(),
        )

        # deep-recall 0.95 x speakingRate 1.0.
        assert edge.calls[0][2].rate == "-5%"

        edge.calls.clear()

        process_structured_job(
            plan_job(
                recall_segments()
            ),
            AppSettings(),
        )

        # deep-entry-study 1.0: a different rate, so different audio.
        assert edge.calls[0][2].rate == "+0%"

    with_directories(
        action
    )


def check_same_rate_profiles_share_their_audio():
    def action():
        edge = RecordingEdge()

        registry.set_override_chain(
            [
                edge,
            ]
        )

        first = process_structured_job(
            plan_job(
                recall_segments()
            ),
            AppSettings(),
        )

        note = v2_note(
            recall_segments(),
            [],
        )

        plan = json.loads(
            note[
                "Front Speech Plan"
            ]
        )

        plan[
            "tempoProfile"
        ] = "sense-map"

        note[
            "Front Speech Plan"
        ] = json.dumps(
            plan
        )

        second = process_structured_job(
            create_rce_speech_plan_job(
                note
            ),
            AppSettings(),
        )

        # The profile's name and pause numbers are not in the segment key
        # (P5), so the same audio is reused and only the track differs.
        assert second[
            "statistics"
        ][
            "generated"
        ] == 0

        assert second[
            "front"
        ] != first[
            "front"
        ]

    with_directories(
        action
    )


def check_table_edit_rebuilds_the_track_from_cached_audio():
    def action():
        edge = RecordingEdge()

        registry.set_override_chain(
            [
                edge,
            ]
        )

        job = plan_job(
            recall_segments()
        )

        first = process_structured_job(
            job,
            AppSettings(),
        )

        second = process_structured_job(
            job,
            AppSettings.from_dict(
                {
                    "tempo_profiles": {
                        "deep-entry-study": {
                            "pauseFactor": 0.5,
                        },
                    },
                }
            ),
        )

        assert second[
            "statistics"
        ][
            "generated"
        ] == 0

        assert second[
            "front"
        ] != first[
            "front"
        ]

        third = process_structured_job(
            job,
            AppSettings.from_dict(
                {
                    "tempo_profiles": {
                        "deep-entry-study": {
                            "rate": 0.9,
                        },
                    },
                }
            ),
        )

        # A rate is synthesis: the audio regenerates.
        assert third[
            "statistics"
        ][
            "generated"
        ] == 1

    with_directories(
        action
    )


def check_pause_change_in_the_plan_keeps_the_audio():
    def action():
        edge = RecordingEdge()

        registry.set_override_chain(
            [
                edge,
            ]
        )

        first = process_structured_job(
            plan_job(
                recall_segments()
            ),
            AppSettings(),
        )

        segments = recall_segments()

        segments[0][
            "pauseAfter"
        ] = {
            "kind": "boundary",
        }

        second = process_structured_job(
            plan_job(
                segments
            ),
            AppSettings(),
        )

        assert second[
            "statistics"
        ][
            "generated"
        ] == 0

        assert second[
            "front"
        ] != first[
            "front"
        ]

    with_directories(
        action
    )


def check_unspoken_segment_makes_no_audio_and_changes_nothing():
    def action():
        edge = RecordingEdge()

        registry.set_override_chain(
            [
                edge,
            ]
        )

        spoken_only = process_structured_job(
            plan_job(
                recall_segments()
            ),
            AppSettings(),
        )

        edge.calls.clear()

        with_silent = process_structured_job(
            plan_job(
                recall_segments()
                + [
                    v2_segment(
                        2,
                        "breadcrumb",
                        "en-US",
                        "label",
                        spoken=False,
                        earconBefore="sectionBoundary",
                        pauseAfter={
                            "kind": "fixed",
                            "milliseconds": 900,
                        },
                    ),
                ]
            ),
            AppSettings(),
        )

        assert edge.calls == []

        assert with_silent[
            "front"
        ] == spoken_only[
            "front"
        ]

        nothing = process_structured_job(
            plan_job(
                [
                    v2_segment(
                        1,
                        "breadcrumb",
                        "en-US",
                        "label",
                        spoken=False,
                    ),
                ]
            ),
            AppSettings(),
        )

        assert nothing[
            "front"
        ] is None

    with_directories(
        action
    )


def run():
    checks = [
        check_defaults_are_the_design_notes_table,
        check_config_json_ships_the_table,
        check_unknown_profile_name_is_default,
        check_table_merges_and_round_trips,
        check_legacy_config_gets_the_table,
        check_bad_table_values_are_errors,
        check_pause_kinds,
        check_proportional_formula_and_clamp,
        check_stitched_pauses_come_from_the_trimmed_speech,
        check_absent_pause_uses_the_v1_milliseconds,
        check_v1_stitch_input_keeps_exact_pauses,
        check_tempo_rate_composes_into_the_synthesis_rate,
        check_same_rate_profiles_share_their_audio,
        check_table_edit_rebuilds_the_track_from_cached_audio,
        check_pause_change_in_the_plan_keeps_the_audio,
        check_unspoken_segment_makes_no_audio_and_changes_nothing,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
