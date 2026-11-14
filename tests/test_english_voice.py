"""
Review batch 5 (CA-95): which voice each segment is sent to.

Edge withdrew de-DE-SeraphinaMultilingualNeural, the English content voice of
CA-41, and answers a request naming it in de-DE-TanjaNeural (a German voice
that is not multilingual) without an error. These checks run notes through
the real Edge provider with a fake edge_tts that records the voice, the
language and the route (carrier or plain) of every request.
"""

from __future__ import annotations

from pathlib import Path

import providers.edge as edge_module
from providers import registry
from providers.edge import EdgeProvider
from rce_contract import create_rce_speech_plan_job
from settings import AppSettings
from structured_audio import process_structured_job
from tests.test_role_voices import (
    v2_note,
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


def run():
    checks = [
        check_no_request_names_a_voice_edge_no_longer_offers,
        check_the_generic_path_english_profile_names_an_offered_voice,
        check_the_default_english_content_voice_is_offered,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
