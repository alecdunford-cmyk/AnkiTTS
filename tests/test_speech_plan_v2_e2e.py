"""
The speech plan v2 fixture from the plan's JSON to the published track, through
the fake Pocket worker: real parsing, resolution, synthesis protocol, loudness
normalisation, earcons, stitching and MP3 export. Only the voice is a stand-in:
each Edge voice is given its own pitch, so the decoded track shows who spoke.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from pydub import AudioSegment
from pydub.generators import Sine

import cache
from providers import registry
from providers.base import (
    Capabilities,
    HealthStatus,
    Provider,
)
from rce_contract import create_rce_speech_plan_job
from settings import AppSettings
from speech_plan import parse_speech_plan
import structured_audio
from tests.test_earcons import (
    dominant_frequency,
    with_earcon_directory,
)
from tests.test_pocket_provider import (
    PROFILE,
    make_clip,
    make_provider,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"

CA41_VOICES = {
    ("fr", "content"): "fr-FR-VivienneMultilingualNeural",
    ("fr", "label"): "en-US-BrianMultilingualNeural",
    ("en", "content"): "de-DE-SeraphinaMultilingualNeural",
    ("en", "label"): "en-US-AndrewNeural",
}

VOICE_HERTZ = {
    "fr-FR-VivienneMultilingualNeural": 200,
    "en-US-BrianMultilingualNeural": 270,
    "de-DE-SeraphinaMultilingualNeural": 340,
    "en-US-AndrewNeural": 460,
    "fr-FR-HenriNeural": 240,
}

EARCON_HERTZ = {
    "sectionBoundary": (
        1100,
        1500,
    ),
    "answerStart": (
        480,
        860,
    ),
    "directionFlip": (
        350,
        440,
    ),
    # CA-71 (1), from the design of each tone as the ruling's stage states it:
    # a falling A5-D5 step (about 730 Hz across its middle), a rising G5-C6
    # step (about 915 Hz), a low A4-E4 glide (about 385 Hz).
    "sectionNumber": (
        640,
        830,
    ),
    "sectionLetter": (
        790,
        1060,
    ),
    "idiomHeading": (
        330,
        440,
    ),
}

EDGE_IDENTITY = {
    "provider": "edge-tts",
    "provider_model": "edge-neural-voices",
    "provider_version": "7.3.1",
    "speech_text_version": "3",
    "loudness_version": "1",
}


def load_fixture(
    name,
):
    with (
        FIXTURES
        / name
    ).open(
        encoding="utf-8",
    ) as fixture_file:
        return json.load(
            fixture_file
        )


def create_note(
    front_plan,
    back_plan,
    card_id="fixture-card",
):
    return {
        "Front": "visual front",
        "Back": "visual back",
        "Front Speech Plan": json.dumps(
            front_plan,
            ensure_ascii=False,
        ),
        "Back Speech Plan": json.dumps(
            back_plan,
            ensure_ascii=False,
        ),
        "Front Audio": "",
        "Back Audio": "",
        "Playback Plan": "{}",
        "Blueprint": "fixture@1",
        "Theme": "fixture",
        "RCE Card ID": card_id,
    }


class WorkerBackedEdge(Provider):
    """
    Stands where Edge stands (the voice comes from the profile and is in the
    key), but makes its audio by asking the fake worker for a tone: its pitch
    says which voice was asked for, its length follows the text. The worker
    path then normalises, and applies a rate by atempo, as for real audio.
    """

    provider_id = "edge"

    def __init__(
        self,
        directory,
    ):
        super().__init__()

        clip = make_clip(
            directory
        )

        self.worker = make_provider(
            directory,
            reference_clips={
                "fr": str(
                    clip
                ),
                "en": str(
                    clip
                ),
            },
        )

        self.calls = []

    def identity(
        self,
        language,
    ):
        return dict(
            EDGE_IDENTITY
        )

    def capabilities(self):
        return Capabilities(
            None,
            True,
            True,
            True,
            False,
            3,
        )

    def voices(
        self,
        language,
    ):
        return []

    def health(
        self,
        language=None,
    ):
        return HealthStatus(
            True,
            "ok",
        )

    def synthesize(
        self,
        text,
        language,
        profile,
        output_path,
    ):
        self.calls.append(
            (
                text,
                language,
                profile.voice,
                profile.rate,
            )
        )

        self.worker.synthesize(
            f"TONEMS:{400 + 25 * len(text)}:{VOICE_HERTZ[profile.voice]}",
            language,
            replace(
                PROFILE,
                language=language,
                rate=profile.rate,
            ),
            output_path,
        )

    def close(self):
        self.worker.close()


class E2E:
    """A temporary cache, output and earcon folder, and a recording stitcher."""

    def __init__(
        self,
        root,
    ):
        self.root = root
        self.edge = WorkerBackedEdge(
            root
        )
        self.stitched = {}

    def run(
        self,
        front_plan,
        back_plan,
        settings=None,
    ):
        return structured_audio.process_structured_job(
            create_rce_speech_plan_job(
                create_note(
                    front_plan,
                    back_plan,
                )
            ),
            settings
            if settings is not None
            else AppSettings(),
        )

    def track(
        self,
        filename,
    ):
        return AudioSegment.from_file(
            str(
                structured_audio.OUTPUT_DIR
                / filename
            )
        )


def with_e2e(
    action,
):
    def directory_action(
        _earcon_directory,
    ):
        original_cache = cache.CACHE_DIR
        original_output = structured_audio.OUTPUT_DIR
        original_stitch = structured_audio.stitch_structured_audio

        with TemporaryDirectory() as directory:
            root = Path(
                directory
            )

            cache.CACHE_DIR = root / "cache"
            cache.CACHE_DIR.mkdir()
            structured_audio.OUTPUT_DIR = root / "output"
            structured_audio.OUTPUT_DIR.mkdir()

            e2e = E2E(
                root
            )

            def recording_stitch(
                segments,
                output_file,
            ):
                timeline = original_stitch(
                    segments,
                    output_file,
                )

                e2e.stitched[
                    Path(
                        output_file
                    ).name
                ] = timeline

                return timeline

            structured_audio.stitch_structured_audio = recording_stitch

            registry.set_override_chain(
                [
                    e2e.edge,
                ]
            )

            try:
                action(
                    e2e
                )

            finally:
                registry.set_override_chain(
                    None
                )

                e2e.edge.close()

                cache.CACHE_DIR = original_cache
                structured_audio.OUTPUT_DIR = original_output
                structured_audio.stitch_structured_audio = original_stitch

    with_earcon_directory(
        directory_action
    )


def timeline_of(
    e2e,
    filename,
):
    return e2e.stitched[
        f".{filename}.pending"
    ]


def primary_language(
    tag,
):
    return tag.split(
        "-"
    )[0]


def expected_voice(
    segment,
):
    return CA41_VOICES[
        (
            primary_language(
                segment.language
            ),
            segment.voice_role,
        )
    ]


def expected_proportional(
    scale,
    tempo,
    speech_milliseconds,
):
    return max(
        tempo.min_pause_ms,
        min(
            tempo.max_pause_ms,
            int(
                (
                    scale
                    * tempo.pause_factor
                    * Decimal(
                        speech_milliseconds
                    )
                ).quantize(
                    Decimal(
                        "1"
                    ),
                    rounding=ROUND_HALF_UP,
                )
            ),
        ),
    )


def within(
    actual,
    expected,
    tolerance=2,
):
    return abs(
        actual
        - expected
    ) <= tolerance


def interior(
    track,
    event,
    margin=45,
):
    return track[
        event[
            "start_ms"
        ]
        + margin : event[
            "start_ms"
        ]
        + event[
            "duration_ms"
        ]
        - margin
    ]


def middle(
    track,
    event,
):
    """The middle half of an event: clear of its edges and the MP3's delay."""

    quarter = event[
        "duration_ms"
    ] // 4

    return track[
        event[
            "start_ms"
        ]
        + quarter : event[
            "start_ms"
        ]
        + event[
            "duration_ms"
        ]
        - quarter
    ]


def check_track_against_plan(
    plan_data,
    filename,
    e2e,
    tempo_name,
):
    """
    Walk the plan and the stitched timeline together, then listen to the MP3:
    each pause, earcon and clip must be where and what the plan says.
    Returns the proportional pauses seen as (milliseconds, clamped to).
    """

    plan = parse_speech_plan(
        json.dumps(
            plan_data
        ),
        plan_data[
            "side"
        ],
    )

    tempo = AppSettings().get_tempo_profile(
        tempo_name
    )

    timeline = list(
        timeline_of(
            e2e,
            filename,
        )
    )

    track = e2e.track(
        filename
    )

    proportional_pauses = []
    position = 0

    def take(
        kind,
    ):
        nonlocal position

        event = timeline[
            position
        ]

        assert event[
            "kind"
        ] == kind, (
            f"event {position}: {event['kind']}, plan wants {kind}"
        )

        position += 1

        return event

    segments = plan.segments

    def is_alternative_of_previous(
        index,
    ):
        """CA-61 (4), restated from the ruling: the oracle for the "or"."""

        if index == 0:
            return False

        previous = segments[
            index - 1
        ]

        segment = segments[
            index
        ]

        return (
            segment.role == "alternative"
            and previous.role
            in (
                "translation",
                "alternative",
            )
            and previous.content_node_id
            == segment.content_node_id
            and primary_language(
                previous.language
            )
            == primary_language(
                segment.language
            )
        )

    def attached_side(
        index,
    ):
        """CA-61 (7): the side of this tag that faces its owner."""

        owner = segments[
            index
        ].attached_to

        if owner is None:
            return None

        owner_index = next(
            position
            for position, candidate in enumerate(
                segments
            )
            if candidate.segment_id == owner
        )

        return (
            "after"
            if index < owner_index
            else "before"
        )

    def check_silent(
        event,
        label,
    ):
        assert interior(
            track,
            event,
            margin=60,
        ).dBFS < -55, f"{label}: pause not silent"

    for index, segment in enumerate(
        segments
    ):
        assert segment.pause_before is None

        side = attached_side(
            index
        )

        if is_alternative_of_previous(
            index
        ):
            tight_before = take(
                "connective_pause_before"
            )

            assert within(
                tight_before[
                    "duration_ms"
                ],
                tempo.tight_pause_ms,
            )

            connective = take(
                "connective"
            )

            assert within(
                dominant_frequency(
                    middle(
                        track,
                        connective,
                    )
                ),
                VOICE_HERTZ[
                    CA41_VOICES[
                        (
                            primary_language(
                                segment.language
                            ),
                            "content",
                        )
                    ]
                ],
                tolerance=12,
            ), f"{segment.segment_id}: the or was not in the content voice"

            tight_after = take(
                "connective_pause_after"
            )

            assert within(
                tight_after[
                    "duration_ms"
                ],
                tempo.tight_pause_ms,
            )

            check_silent(
                tight_before,
                segment.segment_id,
            )

            check_silent(
                tight_after,
                segment.segment_id,
            )

        elif side == "before":
            attached = take(
                "pause_before"
            )

            assert within(
                attached[
                    "duration_ms"
                ],
                tempo.tight_pause_ms,
            ), f"{segment.segment_id}: {attached['duration_ms']}"

            check_silent(
                attached,
                segment.segment_id,
            )

        if segment.earcon_before is not None:
            earcon = take(
                "earcon_before"
            )

            low, high = EARCON_HERTZ[
                segment.earcon_before
            ]

            heard = dominant_frequency(
                middle(
                    track,
                    earcon,
                )
            )

            assert low < heard < high, (
                f"{segment.segment_id}: {segment.earcon_before} heard at "
                f"{heard:.0f} Hz"
            )

            take(
                "earcon_gap"
            )

        speech = take(
            "speech"
        )

        heard = dominant_frequency(
            middle(
                track,
                speech,
            )
        )

        assert within(
            heard,
            VOICE_HERTZ[
                expected_voice(
                    segment
                )
            ],
            tolerance=12,
        ), f"{segment.segment_id}: heard {heard:.0f} Hz"

        assert segment.earcon_after is None

        # The "or" before the next segment sits in place of the pause here.
        if index + 1 < len(
            segments
        ) and is_alternative_of_previous(
            index + 1
        ):
            continue

        kind = segment.pause_after.kind

        if side == "after":
            pause = take(
                "pause_after"
            )

            assert within(
                pause[
                    "duration_ms"
                ],
                tempo.tight_pause_ms,
            ), f"{segment.segment_id}: {pause['duration_ms']}"

            check_silent(
                pause,
                segment.segment_id,
            )

            continue

        if kind == "none":
            continue

        pause = take(
            "pause_after"
        )

        if kind == "fixed":
            assert within(
                pause[
                    "duration_ms"
                ],
                segment.pause_after.milliseconds,
            )

        elif kind == "boundary":
            assert within(
                pause[
                    "duration_ms"
                ],
                tempo.boundary_pause_ms,
            )

        else:
            assert kind == "proportional"

            wanted = expected_proportional(
                segment.pause_after.scale,
                tempo,
                speech[
                    "duration_ms"
                ],
            )

            assert within(
                pause[
                    "duration_ms"
                ],
                wanted,
            ), f"{segment.segment_id}: {pause['duration_ms']} != {wanted}"

            assert (
                tempo.min_pause_ms - 2
                <= pause[
                    "duration_ms"
                ]
                <= tempo.max_pause_ms + 2
            )

            proportional_pauses.append(
                wanted
            )

        # The pause really is silence in the published MP3.
        assert interior(
            track,
            pause,
            margin=60,
        ).dBFS < -55, f"{segment.segment_id}: pause not silent"

    assert position == len(
        timeline
    )

    return proportional_pauses


def check_fixture_parses_and_follows_section_3():
    fixture = load_fixture(
        "speech_plan_v2.json"
    )

    for name, plan_data in fixture.items():
        if name.startswith(
            "_"
        ):
            continue

        plan = parse_speech_plan(
            json.dumps(
                plan_data
            ),
            plan_data[
                "side"
            ],
        )

        assert plan.tempo_profile == plan.preset.id

        for segment in plan.segments:
            # voiceRole = label for sectionNumber, label and cue; else content.
            assert segment.voice_role == (
                "label"
                if segment.role
                in (
                    "sectionNumber",
                    "label",
                    "cue",
                )
                else "content"
            )

            # After the headword fixed 900; never a v1 pause beside a v2 one.
            if segment.role == "headword":
                assert (
                    segment.pause_after.kind,
                    segment.pause_after.milliseconds,
                ) == (
                    "fixed",
                    900,
                )
            else:
                # "none" is the pause after the owner of a tag that follows it.
                assert segment.pause_after.kind in (
                    "proportional",
                    "boundary",
                    "none",
                )

    backs = (
        fixture[
            "deepStudyBack"
        ],
        fixture[
            "deepRecallBack"
        ],
    )

    for plan_data in backs:
        assert plan_data[
            "segments"
        ][0][
            "earconBefore"
        ] == "answerStart"

    assert [
        segment[
            "text"
        ]
        for segment in fixture[
            "deepStudyBack"
        ][
            "segments"
        ]
        if segment[
            "role"
        ]
        == "headword"
    ] == [
        "le phare",
    ]

    # CA-71 (1): the four numbered sections carry the numbered-section earcon,
    # the one lettered sub-section its own, the one idiom block's heading its
    # own; none of the old section earcon is left in this plan.
    back_earcons = [
        segment.get(
            "earconBefore"
        )
        for segment in fixture[
            "deepStudyBack"
        ][
            "segments"
        ]
    ]

    assert back_earcons.count(
        "sectionNumber"
    ) == 4

    assert back_earcons.count(
        "sectionLetter"
    ) == 1

    assert back_earcons.count(
        "idiomHeading"
    ) == 1

    assert "sectionBoundary" not in back_earcons

    for segment in fixture[
        "deepStudyBack"
    ][
        "segments"
    ]:
        if segment.get(
            "earconBefore"
        ) in (
            "sectionNumber",
            "sectionLetter",
            "idiomHeading",
        ):
            assert "earconAfter" not in segment

            assert segment[
                "role"
            ] == {
                "sectionNumber": "sectionNumber",
                "sectionLetter": "sectionNumber",
                "idiomHeading": "idiomHead",
            }[
                segment[
                    "earconBefore"
                ]
            ]

    # Deep Recall: two pairs, each source then target with a flip between.
    assert [
        (
            segment[
                "pair"
            ][
                "id"
            ],
            segment[
                "pair"
            ][
                "position"
            ],
            segment.get(
                "earconBefore"
            ),
        )
        for segment in fixture[
            "deepRecallBack"
        ][
            "segments"
        ]
    ] == [
        (
            "pair-1",
            "source",
            "answerStart",
        ),
        (
            "pair-1",
            "target",
            "directionFlip",
        ),
        (
            "pair-2",
            "source",
            "sectionBoundary",
        ),
        (
            "pair-2",
            "target",
            "directionFlip",
        ),
    ]

    # Atom fronts: visual order, translation first on Target->Source; no earcons.
    assert [
        segment[
            "role"
        ]
        for segment in fixture[
            "atomFrontTargetToSource"
        ][
            "segments"
        ]
    ] == [
        "translation",
        "cue",
    ]

    assert [
        segment[
            "role"
        ]
        for segment in fixture[
            "atomFrontSourceToTarget"
        ][
            "segments"
        ]
    ] == [
        "headword",
        "cue",
    ]

    for name in (
        "atomFrontSourceToTarget",
        "atomFrontTargetToSource",
    ):
        assert not any(
            "earconBefore" in segment
            or "earconAfter" in segment
            for segment in fixture[
                name
            ][
                "segments"
            ]
        )


def check_deep_study_and_atom_front_end_to_end():
    fixture = load_fixture(
        "speech_plan_v2.json"
    )

    def action(
        e2e,
    ):
        result = e2e.run(
            fixture[
                "atomFrontSourceToTarget"
            ],
            fixture[
                "deepStudyBack"
            ],
        )

        # Four voice identities, each on the language and role that names it.
        voices = {
            call[2]
            for call in e2e.edge.calls
        }

        assert voices == set(
            CA41_VOICES.values()
        ), voices

        plans = {
            segment[
                "text"
            ]: segment
            for segment in (
                fixture[
                    "atomFrontSourceToTarget"
                ][
                    "segments"
                ]
                + fixture[
                    "deepStudyBack"
                ][
                    "segments"
                ]
            )
        }

        by_text = {}

        for text, language, voice, rate in e2e.edge.calls:
            by_text[
                text
            ] = (
                language,
                voice,
                rate,
            )

        for text, segment in plans.items():
            language = primary_language(
                segment[
                    "language"
                ]
            )

            spoken = [
                value
                for key, value in by_text.items()
                if key == text
                or key.startswith(
                    text[
                        :12
                    ]
                )
            ]

            assert spoken, text

            assert spoken[0][:2] == (
                language,
                CA41_VOICES[
                    (
                        language,
                        segment[
                            "voiceRole"
                        ],
                    )
                ],
            ), text

        assert {
            call[3]
            for call in e2e.edge.calls
        } == {
            "+0%",
        }

        pauses = check_track_against_plan(
            fixture[
                "deepStudyBack"
            ],
            result[
                "back"
            ],
            e2e,
            "deep-entry-study",
        )

        # CA-61 (4), (7) on the published back: three alternatives take an
        # "or" (the idiom's, and the new example's two), spoken by one clip
        # synthesised once, each between two tight pauses; the two tags have
        # a tight pause on the side facing their owner.
        tempo = AppSettings().get_tempo_profile(
            "deep-entry-study"
        )

        back_timeline = timeline_of(
            e2e,
            result[
                "back"
            ],
        )

        kinds = [
            event[
                "kind"
            ]
            for event in back_timeline
        ]

        assert kinds.count(
            "connective"
        ) == 3

        assert kinds.count(
            "connective_pause_before"
        ) == 3

        assert kinds.count(
            "connective_pause_after"
        ) == 3

        assert [
            call[0]
            for call in e2e.edge.calls
        ].count(
            "or,"
        ) == 1

        # 27 segments: 27 speech events. The pauses after are 27 less the owner
        # whose pause after is none (1) and the 3 that an "or" replaces; one
        # pause before: the tight pause of the tag that follows its owner.
        assert kinds.count(
            "speech"
        ) == 27

        assert kinds.count(
            "pause_before"
        ) == 1

        assert kinds.count(
            "pause_after"
        ) == 27 - 1 - 3

        # CA-71 (1): one earcon before each of the 4 numbered sections, the
        # lettered sub-section and the idiom heading, plus the answer start.
        assert kinds.count(
            "earcon_before"
        ) == 1 + 4 + 1 + 1

        assert kinds.count(
            "earcon_after"
        ) == 0

        assert tempo.tight_pause_ms == 120

        # The clamp bit at both ends on this fixture: "un" and the long example.

        assert tempo.min_pause_ms in pauses
        assert tempo.max_pause_ms in pauses

        assert any(
            tempo.min_pause_ms
            < pause
            < tempo.max_pause_ms
            for pause in pauses
        )

        check_track_against_plan(
            fixture[
                "atomFrontSourceToTarget"
            ],
            result[
                "front"
            ],
            e2e,
            "sense-map",
        )

        # Running it again costs nothing and publishes the same files.
        generated_before = len(
            e2e.edge.calls
        )

        again = e2e.run(
            fixture[
                "atomFrontSourceToTarget"
            ],
            fixture[
                "deepStudyBack"
            ],
        )

        assert len(
            e2e.edge.calls
        ) == generated_before

        assert again[
            "statistics"
        ][
            "generated"
        ] == 0

        assert (
            again[
                "front"
            ],
            again[
                "back"
            ],
        ) == (
            result[
                "front"
            ],
            result[
                "back"
            ],
        )

    with_e2e(
        action
    )


def check_deep_recall_and_flipped_atom_end_to_end():
    fixture = load_fixture(
        "speech_plan_v2.json"
    )

    def action(
        e2e,
    ):
        result = e2e.run(
            fixture[
                "atomFrontTargetToSource"
            ],
            fixture[
                "deepRecallBack"
            ],
        )

        # deep-recall's 0.95 reaches the synthesis rate; sense-map's 1.0 too.
        rates = {
            call[0]: call[3]
            for call in e2e.edge.calls
        }

        assert rates[
            "the lighthouse"
        ] == "+0%"

        assert rates[
            "The lighthouse comes on at nightfall."
        ] == "-5%"

        recall_pauses = check_track_against_plan(
            fixture[
                "deepRecallBack"
            ],
            result[
                "back"
            ],
            e2e,
            "deep-recall",
        )

        assert recall_pauses

        check_track_against_plan(
            fixture[
                "atomFrontTargetToSource"
            ],
            result[
                "front"
            ],
            e2e,
            "sense-map",
        )

        # The speech order is the visual order: the translation comes first.
        timeline = timeline_of(
            e2e,
            result[
                "front"
            ],
        )

        track = e2e.track(
            result[
                "front"
            ]
        )

        speech = [
            event
            for event in timeline
            if event[
                "kind"
            ]
            == "speech"
        ]

        assert within(
            dominant_frequency(
                middle(
                    track,
                    speech[0],
                )
            ),
            VOICE_HERTZ[
                CA41_VOICES[
                    (
                        "en",
                        "content",
                    )
                ]
            ],
            tolerance=12,
        )

        assert within(
            dominant_frequency(
                middle(
                    track,
                    speech[1],
                )
            ),
            VOICE_HERTZ[
                CA41_VOICES[
                    (
                        "fr",
                        "label",
                    )
                ]
            ],
            tolerance=12,
        )

    with_e2e(
        action
    )


def check_changed_voice_regenerates_that_role_only_end_to_end():
    fixture = load_fixture(
        "speech_plan_v2.json"
    )

    def action(
        e2e,
    ):
        first = e2e.run(
            fixture[
                "atomFrontSourceToTarget"
            ],
            fixture[
                "deepStudyBack"
            ],
        )

        e2e.edge.calls.clear()

        changed = e2e.run(
            fixture[
                "atomFrontSourceToTarget"
            ],
            fixture[
                "deepStudyBack"
            ],
            AppSettings.from_dict(
                {
                    "role_voices": {
                        "fr": {
                            "label": {
                                "provider": "edge",
                                "voice": "fr-FR-HenriNeural",
                            },
                        },
                    },
                }
            ),
        )

        # The French label segments: un, deux, trois, quatre, familier, figuré
        # and the lettered sub-section's letter. Nothing else: not the "or"
        # (English content voice), not the English label "informal".
        assert sorted(
            call[0]
            for call in e2e.edge.calls
        ) == [
            "bé",
            "deux",
            "familier",
            "figuré",
            "quatre",
            "trois",
            "un",
        ]

        assert {
            call[2]
            for call in e2e.edge.calls
        } == {
            "fr-FR-HenriNeural",
        }

        # 29 segments (2 on the front, 27 on the back) and 3 spoken "or"s: 32
        # clips placed, 7 of them regenerated.
        assert changed[
            "statistics"
        ] == {
            "generated": 7,
            "cached": 25,
            "skipped": 0,
        }

        # The front has no French label: the same track. The back: a new one.
        assert changed[
            "front"
        ] == first[
            "front"
        ]

        assert changed[
            "back"
        ] != first[
            "back"
        ]

    with_e2e(
        action
    )


# The v1 fixture's identity as it was before schema version 2 existed: recorded
# at f9a9eb6 by running this fixture on that commit (P3). If one of these moves,
# every v1 card in every collection would refill.
V1_GOLDEN_TRACKS = {
    "front": "rce_front_61ba8513992ba3a8816333e0.mp3",
    "back": "rce_back_984392ee4b02bd59f18f2d8e.mp3",
}

V1_GOLDEN_CACHE = [
    "524b13d7ed7d3d907d85407ea9cfab6b904221a2aca43c5798a8f3530549e632.mp3",
    "b0fb928202a6e3cf3091abbcdabd51b9582c41aa7163a84c4e38aa1fbbe10168.mp3",
    "c5736f5b513f6489c6de1133dd03e2879e13295e29420a7a2e17da56961e4cc2.mp3",
    "faeb5c8b86ffaf7316f76ec516a90491b312767b0c25f408efcbf5cb48c4e6f0.mp3",
]


class ToneEdge(WorkerBackedEdge):
    """The same identity as the golden run, with audio made without a worker."""

    def __init__(self):
        Provider.__init__(
            self
        )

        self.calls = []

    def synthesize(
        self,
        text,
        language,
        profile,
        output_path,
    ):
        self.calls.append(
            (
                text,
                language,
                profile.voice,
                profile.rate,
            )
        )

        Sine(440).to_audio_segment(
            duration=300
            + 10
            * len(
                text
            ),
            volume=-20,
        ).set_frame_rate(
            24000
        ).export(
            str(
                output_path
            ),
            format="mp3",
            bitrate="96k",
        )

    def close(self):
        pass


def run_v1_fixture(
    settings,
    action,
):
    fixture = load_fixture(
        "speech_plan_v1.json"
    )

    original_cache = cache.CACHE_DIR
    original_output = structured_audio.OUTPUT_DIR

    edge = ToneEdge()

    with TemporaryDirectory() as directory:
        root = Path(
            directory
        )

        cache.CACHE_DIR = root / "cache"
        cache.CACHE_DIR.mkdir()
        structured_audio.OUTPUT_DIR = root / "output"
        structured_audio.OUTPUT_DIR.mkdir()

        registry.set_override_chain(
            [
                edge,
            ]
        )

        try:
            note = create_note(
                fixture[
                    "front"
                ],
                fixture[
                    "back"
                ],
                card_id="golden-card",
            )

            result = structured_audio.process_structured_job(
                create_rce_speech_plan_job(
                    note
                ),
                settings,
            )

            action(
                result,
                edge,
            )

        finally:
            registry.set_override_chain(
                None
            )

            cache.CACHE_DIR = original_cache
            structured_audio.OUTPUT_DIR = original_output


def check_v1_fixture_keys_are_byte_identical():
    def action(
        result,
        edge,
    ):
        assert result[
            "front"
        ] == V1_GOLDEN_TRACKS[
            "front"
        ]

        assert result[
            "back"
        ] == V1_GOLDEN_TRACKS[
            "back"
        ]

        assert sorted(
            path.name
            for path in cache.CACHE_DIR.iterdir()
        ) == V1_GOLDEN_CACHE

        # The speech profiles' voices, not CA-41's.
        assert {
            call[2]
            for call in edge.calls
        } == {
            "fr-FR-DeniseNeural",
            "en-US-JennyNeural",
        }

    run_v1_fixture(
        AppSettings.from_dict(
            {
                "voices": {
                    "fr": "fr-FR-DeniseNeural",
                    "en": "en-US-JennyNeural",
                },
                "provider_chain": [
                    "edge",
                ],
            }
        ),
        action,
    )


def check_v1_fixture_is_deaf_to_every_new_setting():
    def action(
        result,
        edge,
    ):
        assert (
            result[
                "front"
            ],
            result[
                "back"
            ],
        ) == (
            V1_GOLDEN_TRACKS[
                "front"
            ],
            V1_GOLDEN_TRACKS[
                "back"
            ],
        )

        assert sorted(
            path.name
            for path in cache.CACHE_DIR.iterdir()
        ) == V1_GOLDEN_CACHE

    run_v1_fixture(
        AppSettings.from_dict(
            {
                "voices": {
                    "fr": "fr-FR-DeniseNeural",
                    "en": "en-US-JennyNeural",
                },
                "provider_chain": [
                    "edge",
                ],
                "role_voices": {
                    "fr": {
                        "content": {
                            "provider": "edge",
                            "voice": "fr-FR-HenriNeural",
                        },
                    },
                },
                "tempo_profiles": {
                    "default": {
                        "rate": 0.8,
                        "boundaryPauseMs": 1,
                        "tightPauseMs": 1,
                    },
                },
                "earcons": {
                    "answerStart": "C:/nowhere.wav",
                },
            }
        ),
        action,
    )


def check_fixtures_hold_no_dictionary_text():
    # A guard on the containment rule: fixtures are invented, and say so.
    for name in (
        "speech_plan_v1.json",
        "speech_plan_v2.json",
    ):
        assert (
            "Invented"
            in load_fixture(
                name
            )[
                "_comment"
            ]
        )


def run():
    if shutil.which(
        "ffmpeg"
    ) is None:
        print(
            "    (ffmpeg not on PATH; end-to-end checks skipped)"
        )

        return

    checks = [
        check_fixture_parses_and_follows_section_3,
        check_deep_study_and_atom_front_end_to_end,
        check_deep_recall_and_flipped_atom_end_to_end,
        check_changed_voice_regenerates_that_role_only_end_to_end,
        check_v1_fixture_keys_are_byte_identical,
        check_v1_fixture_is_deaf_to_every_new_setting,
        check_fixtures_hold_no_dictionary_text,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
