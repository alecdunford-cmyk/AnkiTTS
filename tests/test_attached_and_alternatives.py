"""
CA-61 (4) and (7): the pause between a tag and its owner, and the spoken "or"
between the translation alternatives of an example.

The resolver decides who is attached to whom and who takes an "or"; the
stitcher lays the pauses out; the segment cache holds the "or" once. Every
string here is invented for these tests.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from pydub import AudioSegment
from pydub.generators import Sine

from providers import registry
from rce_contract import create_rce_speech_plan_job
from settings import (
    DEFAULT_TEMPO_PROFILES,
    DEFAULT_TIGHT_PAUSE_MS,
    AppSettings,
    TempoProfile,
)
from speech_plan import (
    PauseSpec,
    parse_speech_plan,
)
from stitcher import stitch_structured_audio
import structured_audio
from structured_audio import (
    create_structured_track_filename,
    process_structured_job,
)
from structured_processor import (
    ROLE_CONNECTIVE,
    resolve_speech_plan,
)
from tests.test_role_voices import (
    CA41,
    RecordingEdge,
    v2_note,
    v2_plan,
    v2_segment,
    with_directories,
)


TIGHT = 120


def tone_file(
    path,
    milliseconds,
    hertz=440,
):
    Sine(hertz).to_audio_segment(
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


def example(
    texts_and_roles,
    language="en-US",
    node="node-example",
    start=1,
    **common,
):
    """A run of content segments of one example node, in order."""

    return [
        v2_segment(
            start + index,
            text,
            language,
            "content",
            role=role,
            contentNodeId=node,
            **common,
        )
        for index, (text, role) in enumerate(
            texts_and_roles
        )
    ]


def resolved(
    segments,
    settings=None,
):
    return resolve_speech_plan(
        parse_speech_plan(
            v2_plan(
                "back",
                segments,
            ),
            "back",
        ),
        settings or AppSettings(),
    )


def connectives(
    track,
):
    """Per segment: the text of its connective, or None."""

    return [
        None
        if segment.connective is None
        else segment.connective.text
        for segment in track.segments
    ]


def within(
    actual,
    expected,
    tolerance=2,
):
    return abs(
        actual
        - expected
    ) <= tolerance


def kinds(
    timeline,
):
    return [
        event[
            "kind"
        ]
        for event in timeline
    ]


def check_tight_pause_is_a_tempo_profile_field_defaulting_to_120():
    assert DEFAULT_TIGHT_PAUSE_MS == 120

    settings = AppSettings()

    settings.validate()

    for name, row in DEFAULT_TEMPO_PROFILES.items():
        assert row[
            "tightPauseMs"
        ] == 120, name

        assert settings.get_tempo_profile(
            name
        ).tight_pause_ms == 120

    # A saved table from before the field existed still resolves it, and a
    # row may set its own.
    legacy = {
        "tempo_profiles": {
            "default": {
                "rate": 1.0,
                "pauseFactor": 0.35,
                "minPauseMs": 250,
                "maxPauseMs": 1200,
                "boundaryPauseMs": 700,
            },
            "mine": {
                "tightPauseMs": 300,
            },
        }
    }

    loaded = AppSettings.from_dict(
        legacy
    )

    loaded.validate()

    assert loaded.get_tempo_profile(
        "default"
    ).tight_pause_ms == 120

    assert loaded.get_tempo_profile(
        "mine"
    ).tight_pause_ms == 300

    for bad in (
        -1,
        1.5,
        "120",
        True,
    ):
        try:
            AppSettings.from_dict(
                {
                    "tempo_profiles": {
                        "default": {
                            "tightPauseMs": bad,
                        },
                    }
                }
            )

        except ValueError as error:
            assert "tightPauseMs" in str(
                error
            )

        else:
            raise AssertionError(
                f"tightPauseMs {bad!r} was accepted."
            )


def check_attached_side_follows_the_tags_place_before_or_after_its_owner():
    track = resolved(
        [
            v2_segment(
                1,
                "ancien",
                "fr-FR",
                "label",
                segmentId="tag-before",
                attachedTo="owner",
            ),
            v2_segment(
                2,
                "a vessel",
                "en-US",
                "content",
                segmentId="owner",
            ),
            v2_segment(
                3,
                "informal",
                "en-US",
                "label",
                segmentId="tag-after",
                attachedTo="owner",
            ),
            v2_segment(
                4,
                "plain",
                "en-US",
                "content",
                segmentId="plain",
            ),
        ]
    )

    assert [
        (
            segment.attached_to,
            segment.attached_side,
        )
        for segment in track.segments
    ] == [
        (
            "owner",
            "after",
        ),
        (
            None,
            None,
        ),
        (
            "owner",
            "before",
        ),
        (
            None,
            None,
        ),
    ]


def check_a_tag_next_to_an_unspoken_owner_keeps_the_plans_pauses():
    track = resolved(
        [
            v2_segment(
                1,
                "ancien",
                "fr-FR",
                "label",
                segmentId="tag",
                attachedTo="owner",
            ),
            v2_segment(
                2,
                "voir ailleurs",
                "fr-FR",
                "content",
                segmentId="owner",
                spoken=False,
            ),
        ]
    )

    assert track.segments[
        0
    ].attached_side is None

    assert [
        segment.segment_id
        for segment in track.spoken_segments
    ] == [
        "tag",
    ]


def stitch_two(
    root,
    first,
    second,
):
    first_clip = tone_file(
        root / "first.mp3",
        800,
    )

    second_clip = tone_file(
        root / "second.mp3",
        900,
        hertz=660,
    )

    tempo = TempoProfile(
        Decimal("1"),
        Decimal("0.35"),
        250,
        1200,
        900,
        TIGHT,
    )

    return stitch_structured_audio(
        [
            dict(
                {
                    "file": first_clip,
                    "pause_before_milliseconds": 0,
                    "pause_after_milliseconds": 0,
                    "pause_before": None,
                    "pause_after": None,
                    "tempo": tempo,
                },
                **first,
            ),
            dict(
                {
                    "file": second_clip,
                    "pause_before_milliseconds": 0,
                    "pause_after_milliseconds": 0,
                    "pause_before": None,
                    "pause_after": None,
                    "tempo": tempo,
                },
                **second,
            ),
        ],
        root / "track.mp3",
    )


def check_a_tag_before_its_owner_is_tight_after_and_the_owner_keeps_its_edge():
    with TemporaryDirectory() as directory:
        timeline = stitch_two(
            Path(
                directory
            ),
            {
                "attached_side": "after",
                "pause_before": PauseSpec(
                    "boundary"
                ),
                "pause_after": PauseSpec(
                    "fixed",
                    milliseconds=1500,
                ),
            },
            {
                "pause_after": PauseSpec(
                    "boundary"
                ),
            },
        )

    assert kinds(
        timeline
    ) == [
        "pause_before",
        "speech",
        "pause_after",
        "speech",
        "pause_after",
    ]

    # The tag's outer edge (before) is the plan's; the side facing the owner
    # is the tight pause whatever the plan said (1500); the owner's edge is
    # the plan's boundary.
    assert within(
        timeline[0][
            "duration_ms"
        ],
        900,
    )

    assert within(
        timeline[2][
            "duration_ms"
        ],
        TIGHT,
    )

    assert within(
        timeline[4][
            "duration_ms"
        ],
        900,
    )


def check_a_tag_after_its_owner_is_tight_before():
    with TemporaryDirectory() as directory:
        timeline = stitch_two(
            Path(
                directory
            ),
            {
                "pause_after": PauseSpec(
                    "none"
                ),
            },
            {
                "attached_side": "before",
                "pause_before": PauseSpec(
                    "fixed",
                    milliseconds=2000,
                ),
                "pause_after": PauseSpec(
                    "boundary"
                ),
            },
        )

    # The owner's pause after is "none": no event. The tag's pause before,
    # 2000 in the plan, is the tight pause; its pause after is the plan's.
    assert kinds(
        timeline
    ) == [
        "speech",
        "pause_before",
        "speech",
        "pause_after",
    ]

    assert within(
        timeline[1][
            "duration_ms"
        ],
        TIGHT,
    )

    assert within(
        timeline[3][
            "duration_ms"
        ],
        900,
    )


def check_the_tight_pause_follows_the_tempo_profile():
    with TemporaryDirectory() as directory:
        root = Path(
            directory
        )

        clip = tone_file(
            root / "clip.mp3",
            700,
        )

        for tight in (
            0,
            300,
        ):
            timeline = stitch_structured_audio(
                [
                    {
                        "file": clip,
                        "pause_before_milliseconds": 0,
                        "pause_after_milliseconds": 0,
                        "pause_before": None,
                        "pause_after": PauseSpec(
                            "boundary"
                        ),
                        "attached_side": "after",
                        "tempo": TempoProfile(
                            Decimal("1"),
                            Decimal("0.35"),
                            250,
                            1200,
                            900,
                            tight,
                        ),
                    }
                ],
                root / f"track-{tight}.mp3",
            )

            if tight == 0:
                assert kinds(
                    timeline
                ) == [
                    "speech",
                ]

            else:
                assert kinds(
                    timeline
                ) == [
                    "speech",
                    "pause_after",
                ]

                assert within(
                    timeline[1][
                        "duration_ms"
                    ],
                    tight,
                )


def check_two_alternatives_after_a_translation_each_take_an_or():
    track = resolved(
        example(
            [
                ("Il lève la lampe.", "exampleSource"),
                ("He raises the lamp.", "translation"),
                ("He lifts the lamp.", "alternative"),
                ("He holds the lamp up.", "alternative"),
            ]
        )
    )

    # The first line is French and not a translation; nothing precedes the
    # translation; each alternative follows a translation or an alternative.
    assert connectives(
        track
    ) == [
        None,
        None,
        "or,",
        "or,",
    ]

    clip = track.segments[
        2
    ].connective

    # The "or" is a segment of its own in the content voice of its language,
    # at the profile's rate, and does not depend on the alternative.
    assert (
        clip.role,
        clip.voice_role,
        clip.language,
        clip.voice,
        clip.edge_rate,
    ) == (
        ROLE_CONNECTIVE,
        "content",
        "en",
        CA41[
            (
                "en",
                "content",
            )
        ],
        "+0%",
    )

    # Both alternatives share one clip: the same segment to synthesise, but
    # for the ids that only name it.
    other = track.segments[
        3
    ].connective

    assert (
        clip.text,
        clip.language,
        clip.voice,
        clip.edge_rate,
        clip.role,
        clip.voice_role,
        clip.voice_provider,
    ) == (
        other.text,
        other.language,
        other.voice,
        other.edge_rate,
        other.role,
        other.voice_role,
        other.voice_provider,
    )


def check_the_or_follows_the_language_of_the_alternatives():
    track = resolved(
        [
            v2_segment(
                1,
                "Il lève la lampe.",
                "fr-FR",
                "content",
                role="translation",
                contentNodeId="node-fr",
            ),
            v2_segment(
                2,
                "Il soulève la lampe.",
                "fr-FR",
                "content",
                role="alternative",
                contentNodeId="node-fr",
            ),
            v2_segment(
                3,
                "Il tient la lampe.",
                "fr",
                "content",
                role="alternative",
                contentNodeId="node-fr",
            ),
        ]
    )

    assert connectives(
        track
    ) == [
        None,
        "ou,",
        "ou,",
    ]

    clip = track.segments[
        1
    ].connective

    assert (
        clip.language,
        clip.voice,
    ) == (
        "fr",
        CA41[
            (
                "fr",
                "content",
            )
        ],
    )

    # "fr-FR" and "fr" are one language: the same clip to synthesise.
    other = track.segments[
        2
    ].connective

    assert (
        clip.text,
        clip.language,
        clip.voice,
        clip.edge_rate,
    ) == (
        other.text,
        other.language,
        other.voice,
        other.edge_rate,
    )


def check_a_gloss_list_and_other_neighbours_take_no_or():
    # A sense's gloss alternatives keep their small pauses with no "or".
    gloss_list = resolved(
        example(
            [
                ("a beacon", "gloss"),
                ("a signal", "gloss"),
                ("a light", "gloss"),
            ],
            node="node-gloss",
        )
    )

    assert connectives(
        gloss_list
    ) == [
        None,
        None,
        None,
    ]

    # An alternative that follows something else, or another node, or another
    # language, or that is not the first reading of itself, or that has no
    # node, or in a language with no wording.
    others = resolved(
        [
            v2_segment(
                1,
                "Il lève la lampe.",
                "fr-FR",
                "content",
                role="exampleSource",
                contentNodeId="node-a",
            ),
            v2_segment(
                2,
                "He lifts the lamp.",
                "en-US",
                "content",
                role="alternative",
                contentNodeId="node-a",
            ),
            v2_segment(
                3,
                "He raises the lamp.",
                "en-US",
                "content",
                role="translation",
                contentNodeId="node-a",
            ),
            v2_segment(
                4,
                "He holds the lamp.",
                "en-US",
                "content",
                role="alternative",
                contentNodeId="node-b",
            ),
            v2_segment(
                5,
                "Il lève la lampe encore.",
                "fr-FR",
                "content",
                role="alternative",
                contentNodeId="node-b",
            ),
            v2_segment(
                6,
                "He grips the lamp.",
                "en-US",
                "content",
                role="alternative",
                contentNodeId="",
            ),
            v2_segment(
                7,
                "He lifts the lamp up.",
                "en-US",
                "content",
                role="alternative",
                contentNodeId="",
            ),
            v2_segment(
                8,
                "彼はランプを上げる。",
                "ja-JP",
                "content",
                role="translation",
                contentNodeId="node-ja",
            ),
            v2_segment(
                9,
                "彼はランプを持つ。",
                "ja-JP",
                "content",
                role="alternative",
                contentNodeId="node-ja",
            ),
        ]
    )

    assert connectives(
        others
    ) == [
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    ]

    # A repeated alternative is the same alternative again, not another one.
    repeated = resolved(
        [
            v2_segment(
                1,
                "He raises the lamp.",
                "en-US",
                "content",
                role="translation",
                contentNodeId="node-r",
            ),
            v2_segment(
                2,
                "He lifts the lamp.",
                "en-US",
                "content",
                role="alternative",
                contentNodeId="node-r",
                repetitionNumber=1,
                repetitionCount=2,
            ),
            v2_segment(
                3,
                "He lifts the lamp.",
                "en-US",
                "content",
                role="alternative",
                contentNodeId="node-r",
                repetitionNumber=2,
                repetitionCount=2,
            ),
        ]
    )

    assert connectives(
        repeated
    ) == [
        None,
        "or,",
        None,
    ]

    # Never spoken segments are not between anything.
    skipping = resolved(
        [
            v2_segment(
                1,
                "He raises the lamp.",
                "en-US",
                "content",
                role="translation",
                contentNodeId="node-s",
            ),
            v2_segment(
                2,
                "voir ailleurs",
                "fr-FR",
                "content",
                role="other",
                contentNodeId="node-x",
                spoken=False,
            ),
            v2_segment(
                3,
                "He lifts the lamp.",
                "en-US",
                "content",
                role="alternative",
                contentNodeId="node-s",
            ),
        ]
    )

    assert connectives(
        skipping
    ) == [
        None,
        None,
        "or,",
    ]


def check_a_version_1_track_resolves_without_relations():
    settings = AppSettings()

    plan = {
        "schemaVersion": 1,
        "side": "back",
        "segments": [
            {
                "sequence": 1,
                "segmentId": "a",
                "cueId": "a",
                "contentNodeId": "node",
                "repetitionNumber": 1,
                "repetitionCount": 1,
                "text": "He lifts the lamp.",
                "language": "en-US",
                "voiceProfileId": "",
                "speakingRate": 1.0,
                "pauseBeforeMilliseconds": 0,
                "pauseAfterMilliseconds": 0,
            }
        ],
    }

    import json

    track = resolve_speech_plan(
        parse_speech_plan(
            json.dumps(
                plan
            ),
            "back",
        ),
        settings,
    )

    assert track.tempo is None

    assert (
        track.segments[
            0
        ].attached_side,
        track.segments[
            0
        ].connective,
    ) == (
        None,
        None,
    )


def check_the_or_is_laid_out_between_two_tight_pauses_in_place_of_the_gap():
    with TemporaryDirectory() as directory:
        root = Path(
            directory
        )

        first = tone_file(
            root / "first.mp3",
            800,
        )

        second = tone_file(
            root / "second.mp3",
            900,
            hertz=660,
        )

        connective = tone_file(
            root / "or.mp3",
            300,
            hertz=880,
        )

        tempo = TempoProfile(
            Decimal("1"),
            Decimal("0.35"),
            250,
            1200,
            900,
            TIGHT,
        )

        track = root / "track.mp3"

        timeline = stitch_structured_audio(
            [
                {
                    "file": first,
                    "pause_before_milliseconds": 0,
                    "pause_after_milliseconds": 0,
                    "pause_before": None,
                    "pause_after": PauseSpec(
                        "fixed",
                        milliseconds=700,
                    ),
                    "tempo": tempo,
                },
                {
                    "file": second,
                    "pause_before_milliseconds": 0,
                    "pause_after_milliseconds": 0,
                    "pause_before": PauseSpec(
                        "fixed",
                        milliseconds=500,
                    ),
                    "pause_after": PauseSpec(
                        "boundary"
                    ),
                    "connective_file": connective,
                    "tempo": tempo,
                },
            ],
            track,
        )

        # The 700 ms after the first and the 500 ms before the second are
        # replaced by tight, "or", tight; the second's own edge stays.
        assert kinds(
            timeline
        ) == [
            "speech",
            "connective_pause_before",
            "connective",
            "connective_pause_after",
            "speech",
            "pause_after",
        ]

        assert within(
            timeline[1][
                "duration_ms"
            ],
            TIGHT,
        )

        assert within(
            timeline[3][
                "duration_ms"
            ],
            TIGHT,
        )

        assert 250 < timeline[
            2
        ][
            "duration_ms"
        ] < 450

        assert within(
            timeline[5][
                "duration_ms"
            ],
            900,
        )

        # The published MP3 has the same length as the timeline.
        assert abs(
            len(
                AudioSegment.from_file(
                    str(
                        track
                    )
                )
            )
            - sum(
                event[
                    "duration_ms"
                ]
                for event in timeline
            )
        ) <= 60


def check_a_version_1_segment_is_stitched_as_it_always_was():
    with TemporaryDirectory() as directory:
        root = Path(
            directory
        )

        clip = tone_file(
            root / "clip.mp3",
            600,
        )

        timeline = stitch_structured_audio(
            [
                {
                    "file": clip,
                    "pause_before_milliseconds": 100,
                    "pause_after_milliseconds": 400,
                },
                {
                    "file": clip,
                    "pause_before_milliseconds": 200,
                    "pause_after_milliseconds": 0,
                },
            ],
            root / "track.mp3",
        )

        # No tempo: nothing recorded, no attached side or "or" read.
        assert timeline == []


def counted(
    edge,
    text,
):
    return [
        call
        for call in edge.calls
        if call[0] == text
    ]


def check_the_or_is_one_cached_clip_per_language_and_voice():
    def action():
        edge = RecordingEdge()

        registry.set_override_chain(
            [
                edge,
            ]
        )

        english = example(
            [
                ("He raises the lamp.", "translation"),
                ("He lifts the lamp.", "alternative"),
                ("He holds the lamp up.", "alternative"),
            ],
            node="node-en",
        )

        french = [
            v2_segment(
                4,
                "Il lève la lampe.",
                "fr-FR",
                "content",
                role="translation",
                contentNodeId="node-fr",
            ),
            v2_segment(
                5,
                "Il soulève la lampe.",
                "fr-FR",
                "content",
                role="alternative",
                contentNodeId="node-fr",
            ),
            v2_segment(
                6,
                "Il tient la lampe.",
                "fr-FR",
                "content",
                role="alternative",
                contentNodeId="node-fr",
            ),
        ]

        job = create_rce_speech_plan_job(
            v2_note(
                [
                    english[
                        0
                    ],
                ],
                english + french,
            )
        )

        first = process_structured_job(
            job,
            AppSettings(),
        )

        # Four alternatives, two languages, two clips: one "or," in the
        # English content voice and one "ou," in the French.
        assert len(
            counted(
                edge,
                "or,",
            )
        ) == 1

        assert len(
            counted(
                edge,
                "ou,",
            )
        ) == 1

        voices = {
            call[0]: call[2].voice
            for call in edge.calls
            if call[0] in (
                "or,",
                "ou,",
            )
        }

        assert voices == {
            "or,": CA41[
                (
                    "en",
                    "content",
                )
            ],
            "ou,": CA41[
                (
                    "fr",
                    "content",
                )
            ],
        }

        # 11 clips are placed: 1 on the front, 6 on the back, 4 "or"s. Eight
        # differ (the front's line is the back's first; the "or"s are two).
        assert first[
            "statistics"
        ] == {
            "generated": 8,
            "cached": 3,
            "skipped": 0,
        }

        # Running the card again synthesises nothing and publishes the same
        # tracks.
        edge.calls.clear()

        again = process_structured_job(
            job,
            AppSettings(),
        )

        assert edge.calls == []

        assert again[
            "statistics"
        ][
            "generated"
        ] == 0

        assert again[
            "back"
        ] == first[
            "back"
        ]

        # Another card with an alternative reuses the cached clip.
        other = create_rce_speech_plan_job(
            v2_note(
                [
                    english[
                        0
                    ],
                ],
                example(
                    [
                        ("She raises the flag.", "translation"),
                        ("She lifts the flag.", "alternative"),
                    ],
                    node="node-other",
                ),
            )
        )

        process_structured_job(
            other,
            AppSettings(),
        )

        assert len(
            counted(
                edge,
                "or,",
            )
        ) == 0

    with_directories(
        action
    )


def check_attached_and_alternatives_move_the_track_and_never_the_segments():
    def action():
        edge = RecordingEdge()

        registry.set_override_chain(
            [
                edge,
            ]
        )

        def back(
            attached,
            alternative_role,
        ):
            return [
                v2_segment(
                    1,
                    "ancien",
                    "fr-FR",
                    "label",
                    segmentId="tag",
                    **(
                        {
                            "attachedTo": "owner",
                        }
                        if attached
                        else {}
                    ),
                ),
                v2_segment(
                    2,
                    "He raises the lamp.",
                    "en-US",
                    "content",
                    role="translation",
                    segmentId="owner",
                    contentNodeId="node-t",
                ),
                v2_segment(
                    3,
                    "He lifts the lamp.",
                    "en-US",
                    "content",
                    role=alternative_role,
                    contentNodeId="node-t",
                ),
            ]

        def run(
            attached,
            alternative_role,
            settings=None,
        ):
            return process_structured_job(
                create_rce_speech_plan_job(
                    v2_note(
                        back(
                            attached,
                            alternative_role,
                        )[:2],
                        back(
                            attached,
                            alternative_role,
                        ),
                    )
                ),
                settings or AppSettings(),
            )

        baseline = run(
            True,
            "alternative",
        )

        assert len(
            counted(
                edge,
                "or,",
            )
        ) == 1

        calls = len(
            edge.calls
        )

        # No attachment: the same audio, a different track.
        unattached = run(
            False,
            "alternative",
        )

        assert unattached[
            "back"
        ] != baseline[
            "back"
        ]

        # No "or" (the same text as a gloss): the same audio but for the
        # alternative's role in its key, a different track.
        gloss = run(
            True,
            "gloss",
        )

        assert gloss[
            "back"
        ] != baseline[
            "back"
        ]

        # The segments' audio is not keyed on any of it: only the gloss
        # (a new role) was synthesised again, once.
        assert len(
            edge.calls
        ) == calls + 1

        # A tempo profile with another tight pause rebuilds the track from the
        # cached audio, and synthesises nothing.
        edge.calls.clear()

        retimed = run(
            True,
            "alternative",
            AppSettings.from_dict(
                {
                    "tempo_profiles": {
                        "deep-entry-study": {
                            "tightPauseMs": 250,
                        },
                    },
                }
            ),
        )

        assert edge.calls == []

        assert retimed[
            "back"
        ] != baseline[
            "back"
        ]

        assert retimed[
            "statistics"
        ][
            "generated"
        ] == 0

    with_directories(
        action
    )


def check_the_track_name_changes_only_with_what_is_stitched():
    # The tag's owner is part of the name through the side only: a tag that
    # keeps its side keeps the name, whoever it qualifies.
    def name(
        owner_id,
    ):
        track = resolved(
            [
                v2_segment(
                    1,
                    "ancien",
                    "fr-FR",
                    "label",
                    segmentId="tag",
                    attachedTo=owner_id,
                ),
                v2_segment(
                    2,
                    "a vessel",
                    "en-US",
                    "content",
                    segmentId="owner-a",
                ),
                v2_segment(
                    3,
                    "a boat",
                    "en-US",
                    "content",
                    segmentId="owner-b",
                ),
            ]
        )

        identity = {
            "provider": "edge-tts",
            "provider_model": "m",
            "provider_version": "1",
        }

        return create_structured_track_filename(
            "card",
            track,
            identity,
        )

    assert name(
        "owner-a"
    ) == name(
        "owner-b"
    )

    assert structured_audio.STITCH_VERSION == "2"


def run():
    checks = [
        check_tight_pause_is_a_tempo_profile_field_defaulting_to_120,
        check_attached_side_follows_the_tags_place_before_or_after_its_owner,
        check_a_tag_next_to_an_unspoken_owner_keeps_the_plans_pauses,
        check_a_tag_before_its_owner_is_tight_after_and_the_owner_keeps_its_edge,
        check_a_tag_after_its_owner_is_tight_before,
        check_the_tight_pause_follows_the_tempo_profile,
        check_two_alternatives_after_a_translation_each_take_an_or,
        check_the_or_follows_the_language_of_the_alternatives,
        check_a_gloss_list_and_other_neighbours_take_no_or,
        check_a_version_1_track_resolves_without_relations,
        check_the_or_is_laid_out_between_two_tight_pauses_in_place_of_the_gap,
        check_a_version_1_segment_is_stitched_as_it_always_was,
        check_the_or_is_one_cached_clip_per_language_and_voice,
        check_attached_and_alternatives_move_the_track_and_never_the_segments,
        check_the_track_name_changes_only_with_what_is_stitched,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
