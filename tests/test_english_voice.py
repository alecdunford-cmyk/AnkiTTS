"""
Review batch 5 (CA-95): which voice each segment is sent to.

Edge withdrew de-DE-SeraphinaMultilingualNeural, the English content voice of
CA-41, and answers a request naming it in de-DE-TanjaNeural (a German voice
that is not multilingual) without an error. These checks run notes through
the real Edge provider with a fake edge_tts that records the voice, the
language and the route (carrier or plain) of every request.
"""

from __future__ import annotations

from copy import deepcopy
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from earcons import EARCON_VERSION
import providers.edge as edge_module
from providers import registry
from providers.audio import LOUDNESS_VERSION
from providers.edge import (
    EDGE_CARRIERS,
    EDGE_LANGUAGE_VERSION,
    EdgeProvider,
    carrier_for,
)
from rce_contract import create_rce_speech_plan_job
from settings import (
    AppSettings,
    WITHDRAWN_EDGE_VOICES,
)
from speech_plan import VALID_ROLES, parse_speech_plan
from speech_text import (
    ALTERNATIVE_WORDS,
    SPEECH_TEXT_VERSION,
    prepare_for_speech,
)
import structured_audio
from structured_audio import (
    ROLE_VOICE_VERSION,
    STITCH_VERSION,
    process_structured_job,
)
from structured_processor import (
    ALTERNATIVE_AFTER_ROLES,
    resolve_speech_plan,
)
from anki_integration.rce_audio_status import RCE_AUDIO_READY_TAG
from tests.test_anki_integration import (
    FakeBrowser,
    FakeMainWindow,
    FakeNote,
    browser_integration,
)
from tests.test_role_voices import (
    v2_note,
    v2_plan,
    v2_segment,
    with_directories,
)


# Withdrawn from Edge's catalogue (the listing of 2026-11-13): a request that
# names it is spoken by de-DE-TanjaNeural.
WITHDRAWN = "de-DE-SeraphinaMultilingualNeural"

# Alec's live voice settings (addon/meta.json's config, 2026-11-13), the keys
# that choose a provider, a voice or a language, and nothing else.
ALEC_LIVE = {
    "voices": {
        "fr": "fr-FR-VivienneMultilingualNeural",
        "en": WITHDRAWN,
        "ja": "ja-JP-NanamiNeural",
    },
    "provider_chain": [
        "edge",
    ],
    "role_voices": {
        "fr": {
            "content": {
                "provider": "edge",
                "voice": "fr-FR-VivienneMultilingualNeural",
            },
            "label": {
                "provider": "edge",
                "voice": "en-US-BrianMultilingualNeural",
            },
        },
        "en": {
            "content": {
                "provider": "edge",
                "voice": WITHDRAWN,
            },
            "label": {
                "provider": "edge",
                "voice": "en-US-AndrewNeural",
            },
        },
    },
    "speech_profiles": {
        "fr": {
            "voice": "fr-FR-VivienneMultilingualNeural",
        },
        "en": {
            "voice": WITHDRAWN,
        },
        "ja": {
            "voice": "ja-JP-NanamiNeural",
        },
    },
    "settings_version": 2,
}


class RecordingEdgeTts:
    """
    Stands in for the edge_tts package. Records (voice, text, route) for each
    request: "carrier" for the streamed request with word events, "plain" for
    a saved one. It sends no word events, so a carrier request is followed by
    the plain request the provider falls back to; both name the voice.
    """

    def __init__(
        self,
    ):
        self.requests = []
        requests = self.requests

        class Communicate:
            def __init__(
                self,
                text,
                voice,
                **_rest,
            ):
                self.text = text
                self.voice = voice

            async def save(
                self,
                output_file,
            ):
                requests.append(
                    (
                        self.voice,
                        self.text,
                        "plain",
                    )
                )

                Path(
                    output_file
                ).write_bytes(
                    b"audio"
                )

            async def stream(
                self,
            ):
                requests.append(
                    (
                        self.voice,
                        self.text,
                        "carrier",
                    )
                )

                yield {
                    "type": "audio",
                    "data": b"audio",
                }

        self.Communicate = Communicate


def through_edge(
    action,
):
    """Run action(fake) with the real Edge provider over a fake edge_tts."""

    fake = RecordingEdgeTts()

    original_tts = edge_module.edge_tts
    original_normalise = edge_module.normalise_mp3_in_place

    edge_module.edge_tts = fake
    edge_module.normalise_mp3_in_place = lambda path: None

    try:
        def inner():
            registry.set_override_chain(
                [
                    EdgeProvider(),
                ]
            )

            action(
                fake
            )

        with_directories(
            inner
        )

    finally:
        edge_module.edge_tts = original_tts
        edge_module.normalise_mp3_in_place = original_normalise


# Invented text. A long and a short segment per language and voice role, and
# an alternative after a translation (which takes the "or," / "ou," clip).
FRONT = [
    v2_segment(1, "la vieille maison au bord de la mer", "fr-FR", "content"),
    v2_segment(2, "le phare", "fr-FR", "content"),
    v2_segment(3, "familier", "fr-FR", "label"),
]

BACK = [
    v2_segment(1, "the old house by the edge of the sea", "en-US", "content"),
    v2_segment(2, "the lighthouse", "en-US", "content"),
    v2_segment(3, "informal", "en-US", "label"),
    v2_segment(
        4,
        "the beacon",
        "en-US",
        "content",
        role="translation",
        contentNodeId="node-pair",
    ),
    v2_segment(
        5,
        "the light",
        "en-US",
        "content",
        role="alternative",
        contentNodeId="node-pair",
    ),
]


def check_no_request_names_a_voice_edge_no_longer_offers():
    def action(
        fake,
    ):
        process_structured_job(
            create_rce_speech_plan_job(
                v2_note(
                    FRONT,
                    BACK,
                )
            ),
            AppSettings.from_dict(
                ALEC_LIVE
            ),
        )

        assert fake.requests

        withdrawn = [
            (text, route)
            for voice, text, route in fake.requests
            if voice == WITHDRAWN
        ]

        assert not withdrawn, (
            f"{len(withdrawn)} of {len(fake.requests)} requests name "
            f"{WITHDRAWN}, which Edge no longer offers (it is spoken by "
            f"de-DE-TanjaNeural): {withdrawn}"
        )

    through_edge(
        action
    )


def check_the_generic_path_english_profile_names_an_offered_voice():
    voice = AppSettings.from_dict(
        ALEC_LIVE
    ).get_speech_profile(
        "en"
    ).voice

    assert voice != WITHDRAWN, voice


def check_the_default_english_content_voice_is_offered():
    voice = AppSettings().get_role_voice(
        "en",
        "content",
    )[
        "voice"
    ]

    assert voice != WITHDRAWN, voice


# Item B: who speaks what, for Alec's live settings and for the defaults (the
# same four voices since CA-97). Every voice here was in Edge's listing of
# 2026-11-13.
EXPECTED_VOICES = {
    ("fr", "content"): "fr-FR-VivienneMultilingualNeural",
    ("fr", "label"): "en-US-BrianMultilingualNeural",
    ("en", "content"): "en-US-AvaMultilingualNeural",
    ("en", "label"): "en-US-AndrewNeural",
}

LANGUAGES = {
    "fr": {
        "tag": "fr-FR",
        "short": "mot {n}",
        "long": "une phrase assez longue pour le rôle numéro {n}",
    },
    "en": {
        "tag": "en-US",
        "short": "word {n}",
        "long": "a sentence long enough for the role number {n}",
    },
}


def both_settings():
    return {
        "Alec's live settings": lambda: AppSettings.from_dict(
            deepcopy(
                ALEC_LIVE
            )
        ),
        "the defaults": AppSettings,
    }


def expected_route(
    text,
    language,
    voice,
):
    """The route for a plan text: decided on the text as it is spoken."""

    return (
        "carrier"
        if carrier_for(
            prepare_for_speech(
                text,
                language,
            ),
            language,
            voice,
        )
        else "plain"
    )


def first_request_for(
    fake,
    text,
    language,
):
    """The first request (voice, route) that speaks this plan text."""

    text = prepare_for_speech(
        text,
        language,
    )

    carried = f"{EDGE_CARRIERS[language]} {text}"

    for voice, requested, route in fake.requests:
        if requested in (
            text,
            carried,
        ):
            return voice, route

    raise AssertionError(
        f"no request spoke {text!r}"
    )


def every_role_table():
    """
    One segment per role the plan contract names, voice role, length and
    language, each its own content node (so no neighbour lends anything).
    """

    segments = []
    expected = []
    n = 0

    for language, setup in LANGUAGES.items():
        for role in VALID_ROLES:
            for voice_role in (
                "content",
                "label",
            ):
                for length in (
                    "short",
                    "long",
                ):
                    n += 1

                    text = setup[
                        length
                    ].format(
                        n=n
                    )

                    segments.append(
                        v2_segment(
                            n,
                            text,
                            setup[
                                "tag"
                            ],
                            voice_role,
                            role=role,
                            contentNodeId=f"table-{n}",
                        )
                    )

                    expected.append(
                        (
                            text,
                            language,
                            role,
                            voice_role,
                            length,
                        )
                    )

    return segments, expected


def check_every_role_and_length_gets_its_language_and_voice_role_voice():
    segments, expected = every_role_table()

    for name, make_settings in both_settings().items():
        settings = make_settings()

        track = resolve_speech_plan(
            parse_speech_plan(
                v2_plan(
                    "back",
                    segments,
                ),
                "back",
            ),
            settings,
        )

        for segment, (text, language, role, voice_role, length) in zip(
            track.segments,
            expected,
        ):
            assert (
                segment.text,
                segment.voice,
                segment.voice_provider,
            ) == (
                text,
                EXPECTED_VOICES[
                    (
                        language,
                        voice_role,
                    )
                ],
                "edge",
            ), (name, role, voice_role, length, segment.voice)

        def action(
            fake,
        ):
            process_structured_job(
                create_rce_speech_plan_job(
                    v2_note(
                        segments[:1],
                        segments,
                    )
                ),
                settings,
            )

            for text, language, role, voice_role, length in expected:
                voice = EXPECTED_VOICES[
                    (
                        language,
                        voice_role,
                    )
                ]

                assert first_request_for(
                    fake,
                    text,
                    language,
                ) == (
                    voice,
                    expected_route(
                        text,
                        language,
                        voice,
                    ),
                ), (name, role, voice_role, length)

            assert not [
                voice
                for voice, _text, _route in fake.requests
                if voice in WITHDRAWN_EDGE_VOICES
            ], name

        through_edge(
            action
        )


def check_an_alternative_after_each_predecessor_and_its_neighbours():
    """
    An alternative after each of the six predecessors (CA-64, CA-76, CA-91),
    in each language, short and long: the predecessor, the alternative and
    its "or," / "ou," clip in the content voice of the language; a label
    right after the clip, and one right before the predecessor, in the label
    voice.
    """

    for language, setup in LANGUAGES.items():
        segments = []
        cases = []
        n = 0

        for predecessor in ALTERNATIVE_AFTER_ROLES:
            for length in (
                "short",
                "long",
            ):
                node = f"pair-{language}-{predecessor}-{length}"
                texts = []

                for role, voice_role in (
                    ("label", "label"),
                    (predecessor, "content"),
                    ("alternative", "content"),
                    ("label", "label"),
                ):
                    n += 1

                    text = setup[
                        length
                        if role != "label"
                        else "short"
                    ].format(
                        n=n
                    )

                    texts.append(
                        text
                    )

                    segments.append(
                        v2_segment(
                            n,
                            text,
                            setup[
                                "tag"
                            ],
                            voice_role,
                            role=role,
                            contentNodeId=(
                                node
                                if role != "label"
                                else f"{node}-label-{n}"
                            ),
                        )
                    )

                cases.append(
                    (
                        predecessor,
                        length,
                        texts,
                    )
                )

        content = EXPECTED_VOICES[
            (
                language,
                "content",
            )
        ]

        label = EXPECTED_VOICES[
            (
                language,
                "label",
            )
        ]

        for name, make_settings in both_settings().items():
            settings = make_settings()

            track = resolve_speech_plan(
                parse_speech_plan(
                    v2_plan(
                        "back",
                        segments,
                    ),
                    "back",
                ),
                settings,
            )

            by_text = {
                segment.text: segment
                for segment in track.segments
            }

            for predecessor, length, texts in cases:
                before, owner, alternative, after = (
                    by_text[
                        text
                    ]
                    for text in texts
                )

                assert (
                    before.voice,
                    owner.voice,
                    alternative.voice,
                    after.voice,
                ) == (
                    label,
                    content,
                    content,
                    label,
                ), (name, language, predecessor, length)

                assert owner.connective is None
                assert after.connective is None

                clip = alternative.connective

                assert clip is not None, (name, predecessor, length)

                assert (
                    clip.text,
                    clip.language,
                    clip.voice,
                    clip.voice_role,
                    clip.voice_provider,
                ) == (
                    f"{ALTERNATIVE_WORDS[language]},",
                    language,
                    content,
                    "content",
                    "edge",
                ), (name, predecessor, length)

            def action(
                fake,
            ):
                process_structured_job(
                    create_rce_speech_plan_job(
                        v2_note(
                            segments[:1],
                            segments,
                        )
                    ),
                    settings,
                )

                for predecessor, length, texts in cases:
                    voices = [
                        first_request_for(
                            fake,
                            text,
                            language,
                        )[0]
                        for text in texts
                    ]

                    assert voices == [
                        label,
                        content,
                        content,
                        label,
                    ], (name, language, predecessor, length)

                # One clip per language and voice, asked of the content voice.
                assert first_request_for(
                    fake,
                    f"{ALTERNATIVE_WORDS[language]},",
                    language,
                ) == (
                    content,
                    expected_route(
                        f"{ALTERNATIVE_WORDS[language]},",
                        language,
                        content,
                    ),
                ), name

            through_edge(
                action
            )


def check_a_withdrawn_voice_is_replaced_wherever_it_is_stored():
    # Each place a voice is stored, alone, and a voice that is not withdrawn
    # is kept as it is.
    for data, read in (
        (
            {
                "voices": {
                    "en": WITHDRAWN,
                },
            },
            lambda settings: settings.get_speech_profile(
                "en"
            ).voice,
        ),
        (
            {
                "speech_profiles": {
                    "en": {
                        "voice": WITHDRAWN,
                    },
                },
            },
            lambda settings: settings.get_speech_profile(
                "en"
            ).voice,
        ),
        (
            {
                "role_voices": {
                    "fr": {
                        "label": {
                            "provider": "edge",
                            "voice": WITHDRAWN,
                        },
                    },
                },
            },
            lambda settings: settings.get_role_voice(
                "fr",
                "label",
            )[
                "voice"
            ],
        ),
    ):
        settings = AppSettings.from_dict(
            data
        )

        assert read(
            settings
        ) == "en-US-AvaMultilingualNeural", data

        assert WITHDRAWN not in repr(
            settings
        ), data

    kept = AppSettings.from_dict(
        {
            "role_voices": {
                "en": {
                    "content": {
                        "provider": "edge",
                        "voice": "en-US-EmmaMultilingualNeural",
                    },
                },
            },
        }
    )

    assert kept.get_role_voice(
        "en",
        "content",
    )[
        "voice"
    ] == "en-US-EmmaMultilingualNeural"

    assert WITHDRAWN_EDGE_VOICES == {
        WITHDRAWN: "en-US-AvaMultilingualNeural",
    }


def check_the_log_names_the_voice_of_each_segment():
    records = []

    class Keep(
        logging.Handler
    ):
        def emit(
            self,
            record,
        ):
            records.append(
                record.getMessage()
            )

    handler = Keep()
    logger = logging.getLogger(
        "ankitts.generator"
    )
    logger.addHandler(
        handler
    )

    try:
        def action(
            _fake,
        ):
            process_structured_job(
                create_rce_speech_plan_job(
                    v2_note(
                        FRONT,
                        BACK,
                    )
                ),
                AppSettings.from_dict(
                    deepcopy(
                        ALEC_LIVE
                    )
                ),
            )

        through_edge(
            action
        )

    finally:
        logger.removeHandler(
            handler
        )

    synthesized = [
        record
        for record in records
        if " synthesized " in record
    ]

    assert synthesized

    for voice in EXPECTED_VOICES.values():
        assert any(
            f" with {voice} " in record
            for record in synthesized
        ), voice

    assert not any(
        WITHDRAWN in record
        for record in synthesized
    )


# Item C: what refills, and how a card whose audio is published gets new audio.
def old_settings():
    """What batch 4 resolved Alec's live settings to: Seraphina, unreplaced."""

    settings = AppSettings.from_dict(
        deepcopy(
            ALEC_LIVE
        )
    )

    settings.role_voices[
        "en"
    ][
        "content"
    ][
        "voice"
    ] = WITHDRAWN

    return settings


def check_only_the_withdrawn_voice_clips_refill():
    def action(
        fake,
    ):
        job = create_rce_speech_plan_job(
            v2_note(
                FRONT,
                BACK,
            )
        )

        before = process_structured_job(
            job,
            old_settings(),
        )

        assert any(
            voice == WITHDRAWN
            for voice, _text, _route in fake.requests
        )

        fake.requests.clear()

        after = process_structured_job(
            job,
            AppSettings.from_dict(
                deepcopy(
                    ALEC_LIVE
                )
            ),
        )

        # The old key is never matched again: the English content segments
        # (two long and short, the alternative pair) and the English "or,"
        # clip are made again, in the replacement; nothing else is.
        assert after[
            "statistics"
        ] == {
            "generated": 5,
            "cached": 4,
            "skipped": 0,
        }, after[
            "statistics"
        ]

        assert {
            voice
            for voice, _text, _route in fake.requests
        } == {
            "en-US-AvaMultilingualNeural",
        }

        # The French side is the same track; the English side is a new one.
        assert after[
            "front"
        ] == before[
            "front"
        ]

        assert after[
            "back"
        ] != before[
            "back"
        ]

        # No version moved (a voice is already in every key).
        assert (
            SPEECH_TEXT_VERSION,
            STITCH_VERSION,
            EDGE_LANGUAGE_VERSION,
            ROLE_VOICE_VERSION,
            LOUDNESS_VERSION,
            EARCON_VERSION,
        ) == (
            "5",
            "2",
            "1",
            "1",
            "1",
            "1",
        )

    through_edge(
        action
    )


def check_a_ready_card_gets_new_audio_from_the_browse_command():
    """
    A note tagged ready keeps its audio and is never picked up again by
    itself; the Browse window's "Generate AnkiTTS Audio for Selected Notes"
    makes its audio again, with no re-export: the English side gets a new
    track in the replacement voice, the French side keeps its track, the note
    stays ready, and the old file stays in the media folder until Anki's
    Check Media removes it.
    """

    original_output = browser_integration.OUTPUT_DIR
    original_info = browser_integration.showInfo
    original_warning = browser_integration.showWarning

    def action(
        fake,
    ):
        fields = v2_note(
            FRONT,
            BACK,
        )

        before = process_structured_job(
            create_rce_speech_plan_job(
                fields
            ),
            old_settings(),
        )

        fake.requests.clear()

        with TemporaryDirectory() as directory:
            media = Path(
                directory
            )

            for side in (
                "front",
                "back",
            ):
                (
                    media
                    / before[
                        side
                    ]
                ).write_bytes(
                    b"published"
                )

            note = FakeNote(
                7,
                dict(
                    fields,
                    **{
                        "Front Audio": f"[sound:{before['front']}]",
                        "Back Audio": f"[sound:{before['back']}]",
                    },
                ),
            )

            note.tags = [
                RCE_AUDIO_READY_TAG,
            ]

            mw = FakeMainWindow(
                [
                    note,
                ],
                media,
                deepcopy(
                    ALEC_LIVE
                ),
            )

            information = []

            browser_integration.OUTPUT_DIR = (
                structured_audio.OUTPUT_DIR
            )
            browser_integration.showInfo = information.append
            browser_integration.showWarning = information.append

            browser_integration.process_selected_notes(
                FakeBrowser(
                    [
                        7,
                    ]
                ),
                mw,
                "AnkiTTS",
            )

            assert note[
                "Front Audio"
            ] == f"[sound:{before['front']}]"

            assert note[
                "Back Audio"
            ] != f"[sound:{before['back']}]"

            new_back = note[
                "Back Audio"
            ][
                len(
                    "[sound:"
                ) : -1
            ]

            assert (
                media
                / new_back
            ).exists()

            assert (
                media
                / before[
                    "back"
                ]
            ).exists()

            assert note.tags == [
                RCE_AUDIO_READY_TAG,
            ]

            assert {
                voice
                for voice, _text, _route in fake.requests
            } == {
                "en-US-AvaMultilingualNeural",
            }

            assert len(
                information
            ) == 1

    try:
        through_edge(
            action
        )

    finally:
        browser_integration.OUTPUT_DIR = original_output
        browser_integration.showInfo = original_info
        browser_integration.showWarning = original_warning


def run():
    checks = [
        check_no_request_names_a_voice_edge_no_longer_offers,
        check_the_generic_path_english_profile_names_an_offered_voice,
        check_the_default_english_content_voice_is_offered,
        check_every_role_and_length_gets_its_language_and_voice_role_voice,
        check_an_alternative_after_each_predecessor_and_its_neighbours,
        check_a_withdrawn_voice_is_replaced_wherever_it_is_stored,
        check_the_log_names_the_voice_of_each_segment,
        check_only_the_withdrawn_voice_clips_refill,
        check_a_ready_card_gets_new_audio_from_the_browse_command,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
