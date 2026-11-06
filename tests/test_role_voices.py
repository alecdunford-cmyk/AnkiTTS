from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import cache
from providers import registry
from rce_contract import create_rce_speech_plan_job
from settings import (
    AppSettings,
    DEFAULT_ROLE_VOICES,
    SettingsManager,
    read_addon_config,
)
from speech_plan import parse_speech_plan
import structured_audio
from structured_audio import (
    _chain_for_segment,
    process_structured_job,
)
from structured_processor import resolve_speech_plan
from tests.provider_fakes import FakeProvider
from voice_manager import (
    profile_voice_choices,
    role_voice_choices,
)


CA41 = {
    ("fr", "content"): "fr-FR-VivienneMultilingualNeural",
    ("fr", "label"): "en-US-BrianMultilingualNeural",
    ("en", "content"): "de-DE-SeraphinaMultilingualNeural",
    ("en", "label"): "en-US-AndrewNeural",
}


def v2_segment(
    sequence,
    text,
    language,
    voice_role,
    role=None,
    **overrides,
):
    segment = {
        "sequence": sequence,
        "segmentId": f"segment-{sequence}",
        "cueId": f"cue-{sequence}",
        "contentNodeId": f"node-{sequence}",
        "repetitionNumber": 1,
        "repetitionCount": 1,
        "text": text,
        "language": language,
        "voiceProfileId": "",
        "speakingRate": 1.0,
        "pauseBeforeMilliseconds": 0,
        "pauseAfterMilliseconds": 0,
        "role": role
        or (
            "label"
            if voice_role == "label"
            else "gloss"
        ),
        "voiceRole": voice_role,
    }

    segment.update(
        overrides
    )

    return segment


def v2_plan(
    side,
    segments,
):
    return json.dumps(
        {
            "schemaVersion": 2,
            "side": side,
            "preset": {
                "id": "deep-entry-study",
                "version": 11,
            },
            "tempoProfile": "deep-entry-study",
            "segments": [
                dict(
                    segment,
                    sequence=index + 1,
                )
                for index, segment in enumerate(
                    segments
                )
            ],
        },
        ensure_ascii=False,
    )


FOUR_VOICES = [
    v2_segment(
        1,
        "le phare",
        "fr-FR",
        "content",
    ),
    v2_segment(
        2,
        "familier",
        "fr-FR",
        "label",
    ),
    v2_segment(
        3,
        "the lighthouse",
        "en-US",
        "content",
    ),
    v2_segment(
        4,
        "informal",
        "en-US",
        "label",
    ),
]


def resolve(
    segments,
    settings,
):
    return resolve_speech_plan(
        parse_speech_plan(
            v2_plan(
                "back",
                segments,
            ),
            "back",
        ),
        settings,
    )


def v2_note(
    front,
    back,
):
    return {
        "Front": "f",
        "Back": "b",
        "Front Speech Plan": v2_plan(
            "front",
            front,
        ),
        "Back Speech Plan": v2_plan(
            "back",
            back,
        ),
        "Front Audio": "",
        "Back Audio": "",
        "Playback Plan": "{}",
        "Blueprint": "t@1",
        "Theme": "t",
        "RCE Card ID": "role-card",
    }


class RecordingEdge(FakeProvider):
    """An Edge stand-in: the voice comes from the profile and splits the key."""

    def __init__(
        self,
        provider_id="edge",
    ):
        super().__init__(
            provider_id,
            native_rate=True,
            volume=True,
            pitch=True,
            own_voice=False,
        )


def with_directories(
    action,
):
    original_cache = cache.CACHE_DIR
    original_output = structured_audio.OUTPUT_DIR
    original_stitch = structured_audio.stitch_structured_audio

    def fake_stitch(
        segments,
        output_file,
    ):
        Path(
            output_file
        ).write_bytes(
            b"track"
        )

    try:
        with TemporaryDirectory() as directory:
            root = Path(
                directory
            )

            cache.CACHE_DIR = root / "cache"
            cache.CACHE_DIR.mkdir()
            structured_audio.OUTPUT_DIR = root / "output"
            structured_audio.OUTPUT_DIR.mkdir()
            structured_audio.stitch_structured_audio = fake_stitch

            action()

    finally:
        cache.CACHE_DIR = original_cache
        structured_audio.OUTPUT_DIR = original_output
        structured_audio.stitch_structured_audio = original_stitch
        registry.set_override_chain(
            None
        )


def check_defaults_are_ca41():
    settings = AppSettings()

    settings.validate()

    for (language, voice_role), voice in CA41.items():
        assert settings.get_role_voice(
            language,
            voice_role,
        ) == {
            "provider": "edge",
            "voice": voice,
        }

    assert settings.get_role_voice(
        "ja",
        "content",
    ) is None


def check_config_json_ships_the_defaults():
    with (
        Path(__file__).resolve().parent.parent
        / "addon"
        / "config.json"
    ).open(
        encoding="utf-8",
    ) as config_file:
        config = json.load(
            config_file
        )

    assert config[
        "role_voices"
    ] == DEFAULT_ROLE_VOICES


def check_legacy_config_migrates_without_touching_legacy_keys():
    # What Alec's meta.json holds today: old voices, no role_voices.
    legacy = {
        "voices": {
            "fr": "fr-FR-DeniseNeural",
            "en": "en-US-JennyNeural",
        },
        "speech_profiles": {
            "fr": {
                "voice": "fr-FR-DeniseNeural",
            },
        },
    }

    settings = AppSettings.from_dict(
        legacy
    )

    assert settings.voices[
        "fr"
    ] == "fr-FR-DeniseNeural"

    assert settings.get_speech_profile(
        "fr"
    ).voice == "fr-FR-DeniseNeural"

    assert settings.role_voices == DEFAULT_ROLE_VOICES


def check_partial_role_voices_merge_slot_by_slot():
    settings = AppSettings.from_dict(
        {
            "role_voices": {
                "fr": {
                    "label": {
                        "voice": "fr-FR-HenriNeural",
                    },
                },
                "de": {
                    "content": {
                        "provider": "edge",
                        "voice": "de-DE-KatjaNeural",
                    },
                },
            },
        }
    )

    assert settings.get_role_voice(
        "fr",
        "label",
    ) == {
        "provider": "edge",
        "voice": "fr-FR-HenriNeural",
    }

    assert settings.get_role_voice(
        "fr",
        "content",
    )[
        "voice"
    ] == CA41[
        (
            "fr",
            "content",
        )
    ]

    assert settings.get_role_voice(
        "de",
        "content",
    )[
        "voice"
    ] == "de-DE-KatjaNeural"


def check_malformed_role_voices_are_errors():
    for bad in (
        "edge",
        {
            "fr": "edge",
        },
        {
            "fr": {
                "narrator": {
                    "voice": "x",
                },
            },
        },
        {
            "fr": {
                "label": "x",
            },
        },
        {
            "fr": {
                "label": {
                    "provider": "elevenlabs",
                    "voice": "x",
                },
            },
        },
        {
            "fr": {
                "label": {
                    "provider": "edge",
                    "voice": " ",
                },
            },
        },
        {
            "fr": {
                "label": {
                    "provider": "edge",
                    "voice": 3,
                },
            },
        },
    ):
        try:
            AppSettings.from_dict(
                {
                    "role_voices": bad,
                }
            )

        except ValueError:
            continue

        raise AssertionError(
            f"Malformed role_voices accepted: {bad!r}"
        )


def check_round_trip_through_asdict():
    settings = AppSettings.from_dict(
        {
            "role_voices": {
                "en": {
                    "label": {
                        "provider": "pocket",
                        "voice": "",
                    },
                },
            },
        }
    )

    assert (
        AppSettings.from_dict(
            json.loads(
                json.dumps(
                    asdict(
                        settings
                    )
                )
            )
        ).role_voices
        == settings.role_voices
    )


def check_settings_json_shape_keeps_loading():
    # SettingsManager reads a developer file with only legacy keys.
    with TemporaryDirectory() as directory:
        path = Path(
            directory
        ) / "settings.json"

        path.write_text(
            json.dumps(
                {
                    "front_language": "fr",
                    "voices": {
                        "fr": "fr-FR-DeniseNeural",
                    },
                }
            ),
            encoding="utf-8",
        )

        before = path.read_bytes()

        settings = SettingsManager(
            path
        ).load()

        assert settings.voices[
            "fr"
        ] == "fr-FR-DeniseNeural"

        assert settings.role_voices == DEFAULT_ROLE_VOICES

        # Loading never rewrites the file.
        assert path.read_bytes() == before


def check_addon_overlay_without_role_voices_uses_defaults():
    with TemporaryDirectory() as directory:
        addon_dir = Path(
            directory
        )

        (addon_dir / "config.json").write_text(
            json.dumps(
                {
                    "role_voices": DEFAULT_ROLE_VOICES,
                }
            ),
            encoding="utf-8",
        )

        (addon_dir / "meta.json").write_text(
            json.dumps(
                {
                    "config": {
                        "voices": {
                            "fr": "fr-FR-DeniseNeural",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        assert (
            AppSettings.from_dict(
                read_addon_config(
                    addon_dir
                )
            ).role_voices
            == DEFAULT_ROLE_VOICES
        )


def check_roles_resolve_to_the_four_voices():
    track = resolve(
        FOUR_VOICES,
        AppSettings(),
    )

    assert [
        (
            segment.voice_role,
            segment.voice,
            segment.voice_provider,
        )
        for segment in track.segments
    ] == [
        (
            "content",
            CA41[("fr", "content")],
            "edge",
        ),
        (
            "label",
            CA41[("fr", "label")],
            "edge",
        ),
        (
            "content",
            CA41[("en", "content")],
            "edge",
        ),
        (
            "label",
            CA41[("en", "label")],
            "edge",
        ),
    ]

    # The profile still supplies language, rate, volume and pitch.
    assert [
        segment.resolved_profile_language
        for segment in track.segments
    ] == [
        "fr",
        "fr",
        "en",
        "en",
    ]


def check_v1_segments_keep_the_speech_profile_voice():
    plan = parse_speech_plan(
        json.dumps(
            {
                "schemaVersion": 1,
                "side": "back",
                "segments": [
                    {
                        key: value
                        for key, value in FOUR_VOICES[0].items()
                        if key
                        not in (
                            "role",
                            "voiceRole",
                        )
                    }
                ],
            }
        ),
        "back",
    )

    segment = resolve_speech_plan(
        plan,
        AppSettings.from_dict(
            {
                "voices": {
                    "fr": "fr-FR-DeniseNeural",
                },
            }
        ),
    ).segments[0]

    assert segment.voice == "fr-FR-DeniseNeural"
    assert segment.voice_role is None
    assert segment.voice_provider is None


def check_language_without_slot_keeps_its_profile_voice():
    segment = resolve(
        [
            v2_segment(
                1,
                "灯台",
                "ja-JP",
                "label",
            )
        ],
        AppSettings(),
    ).segments[0]

    assert segment.voice == "ja-JP-NanamiNeural"
    assert segment.voice_provider is None


def check_slot_on_own_voice_provider_keeps_an_edge_voice_for_fallback():
    segment = resolve(
        [
            v2_segment(
                1,
                "le phare",
                "fr-FR",
                "content",
            )
        ],
        AppSettings.from_dict(
            {
                "role_voices": {
                    "fr": {
                        "content": {
                            "provider": "pocket",
                            "voice": "",
                        },
                    },
                },
            }
        ),
    ).segments[0]

    assert segment.voice_provider == "pocket"
    assert segment.voice == CA41[("fr", "content")]


def check_chain_puts_the_slot_provider_first():
    settings = AppSettings()

    pocket = RecordingEdge(
        "pocket"
    )

    edge = RecordingEdge()

    registry.set_override_chain(
        [
            pocket,
            edge,
        ]
    )

    try:
        segments = resolve(
            FOUR_VOICES,
            settings,
        ).segments

        assert _chain_for_segment(
            segments[0],
            settings,
        ) == [
            edge,
            pocket,
        ]

        # Not enabled: the chain as configured, with a warning.
        registry.set_override_chain(
            [
                pocket,
            ]
        )

        assert _chain_for_segment(
            segments[0],
            settings,
        ) == [
            pocket,
        ]

    finally:
        registry.set_override_chain(
            None
        )


def check_label_on_edge_while_content_stays_on_the_primary():
    def action():
        pocket = RecordingEdge(
            "pocket"
        )

        pocket._own_voice = True

        edge = RecordingEdge()

        registry.set_override_chain(
            [
                pocket,
                edge,
            ]
        )

        settings = AppSettings.from_dict(
            {
                "provider_chain": [
                    "pocket",
                    "edge",
                ],
                "role_voices": {
                    "fr": {
                        "content": {
                            "provider": "pocket",
                            "voice": "",
                        },
                    },
                },
            }
        )

        process_structured_job(
            create_rce_speech_plan_job(
                v2_note(
                    [
                        FOUR_VOICES[0],
                    ],
                    [
                        FOUR_VOICES[1],
                    ],
                )
            ),
            settings,
        )

        assert [
            call[0]
            for call in pocket.calls
        ] == [
            "le phare",
        ]

        assert [
            (
                call[0],
                call[2].voice,
            )
            for call in edge.calls
        ] == [
            (
                "familier",
                CA41[("fr", "label")],
            ),
        ]

    with_directories(
        action
    )


def check_content_falls_back_through_the_chain_with_an_edge_voice():
    def action():
        pocket = RecordingEdge(
            "pocket"
        )

        pocket._own_voice = True
        pocket.healthy = False

        edge = RecordingEdge()

        registry.set_override_chain(
            [
                pocket,
                edge,
            ]
        )

        process_structured_job(
            create_rce_speech_plan_job(
                v2_note(
                    [
                        FOUR_VOICES[0],
                    ],
                    [],
                )
            ),
            AppSettings.from_dict(
                {
                    "provider_chain": [
                        "pocket",
                        "edge",
                    ],
                    "role_voices": {
                        "fr": {
                            "content": {
                                "provider": "pocket",
                                "voice": "",
                            },
                        },
                    },
                }
            ),
        )

        assert [
            call[2].voice
            for call in edge.calls
        ] == [
            CA41[("fr", "content")],
        ]

    with_directories(
        action
    )


def check_identity_gains_role_and_voice_and_splits_the_cache():
    def action():
        edge = RecordingEdge()

        registry.set_override_chain(
            [
                edge,
            ]
        )

        same_text = [
            v2_segment(
                1,
                "le phare",
                "fr-FR",
                "content",
                role="gloss",
            ),
            v2_segment(
                2,
                "le phare",
                "fr-FR",
                "content",
                role="translation",
            ),
            v2_segment(
                3,
                "le phare",
                "fr-FR",
                "label",
                role="cue",
            ),
            v2_segment(
                4,
                "le phare",
                "fr-FR",
                "content",
                role="gloss",
                pauseAfterMilliseconds=700,
            ),
        ]

        result = process_structured_job(
            create_rce_speech_plan_job(
                v2_note(
                    same_text,
                    [],
                )
            ),
            AppSettings(),
        )

        # Role and voice role both split the key; the pause never does.
        assert len(
            edge.calls
        ) == 3

        assert result[
            "statistics"
        ] == {
            "generated": 3,
            "cached": 1,
            "skipped": 0,
        }

    with_directories(
        action
    )


def check_changed_voice_regenerates_only_that_role():
    def action():
        edge = RecordingEdge()

        registry.set_override_chain(
            [
                edge,
            ]
        )

        job = create_rce_speech_plan_job(
            v2_note(
                FOUR_VOICES[:2],
                FOUR_VOICES[2:],
            )
        )

        first = process_structured_job(
            job,
            AppSettings(),
        )

        assert first[
            "statistics"
        ][
            "generated"
        ] == 4

        unchanged = process_structured_job(
            job,
            AppSettings(),
        )

        assert unchanged[
            "statistics"
        ][
            "generated"
        ] == 0

        assert unchanged[
            "front"
        ] == first[
            "front"
        ]

        edge.calls.clear()

        changed = process_structured_job(
            job,
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

        # French label only: one segment regenerated, three from the cache.
        assert changed[
            "statistics"
        ] == {
            "generated": 1,
            "cached": 3,
            "skipped": 0,
        }

        assert [
            (
                call[0],
                call[2].voice,
            )
            for call in edge.calls
        ] == [
            (
                "familier",
                "fr-FR-HenriNeural",
            ),
        ]

        # The front track (which has that label) is republished; the back is
        # the same track.
        assert changed[
            "front"
        ] != first[
            "front"
        ]

        assert changed[
            "back"
        ] == first[
            "back"
        ]

    with_directories(
        action
    )


def check_default_chain_is_edge_with_the_others_kept_but_off():
    settings = AppSettings()

    assert settings.provider_chain == [
        "edge",
    ]

    # CA-38 (2): nothing removed; their settings are still there and work.
    assert set(
        settings.providers
    ) == {
        "pocket",
        "fish",
        "edge",
    }

    assert settings.get_provider_settings(
        "pocket"
    )[
        "models"
    ][
        "fr"
    ] == "french"

    assert settings.get_provider_settings(
        "fish"
    )[
        "model"
    ] == "s2.1-pro"

    chain_on_again = AppSettings.from_dict(
        {
            "provider_chain": [
                "pocket",
                "edge",
            ],
        }
    )

    assert chain_on_again.provider_chain == [
        "pocket",
        "edge",
    ]

    with (
        Path(__file__).resolve().parent.parent
        / "addon"
        / "config.json"
    ).open(
        encoding="utf-8",
    ) as config_file:
        config = json.load(
            config_file
        )

    assert config[
        "provider_chain"
    ] == [
        "edge",
    ]

    assert set(
        config[
            "providers"
        ]
    ) == {
        "pocket",
        "fish",
        "edge",
    }

    # If config.json carried the marker, Anki's overlay would hide old configs.
    assert "settings_version" not in config


def check_saved_old_default_chain_migrates_to_edge():
    # Alec's meta.json as it stands: the old default, saved by the dialog.
    with TemporaryDirectory() as directory:
        addon_dir = Path(
            directory
        )

        (addon_dir / "config.json").write_text(
            (
                Path(__file__).resolve().parent.parent
                / "addon"
                / "config.json"
            ).read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )

        meta_text = json.dumps(
            {
                "config": {
                    "voices": {
                        "fr": "fr-FR-DeniseNeural",
                    },
                    "provider_chain": [
                        "pocket",
                        "fish",
                        "edge",
                    ],
                    "providers": {
                        "fish": {
                            "reference_ids": {
                                "fr": "kept-id",
                            },
                        },
                    },
                },
            }
        )

        (addon_dir / "meta.json").write_text(
            meta_text,
            encoding="utf-8",
        )

        settings = SettingsManager.load_addon_config(
            addon_dir
        )

        assert settings.provider_chain == [
            "edge",
        ]

        assert settings.get_provider_settings(
            "fish"
        )[
            "reference_ids"
        ][
            "fr"
        ] == "kept-id"

        # Migration happens on load: the file is not written.
        assert (
            (addon_dir / "meta.json").read_text(
                encoding="utf-8"
            )
            == meta_text
        )


def check_chain_chosen_after_the_change_is_respected():
    # The dialog's Save writes settings_version, so choosing the old order
    # again sticks; any other saved order was always a choice.
    assert AppSettings.from_dict(
        {
            "settings_version": 2,
            "provider_chain": [
                "pocket",
                "fish",
                "edge",
            ],
        }
    ).provider_chain == [
        "pocket",
        "fish",
        "edge",
    ]

    assert AppSettings.from_dict(
        {
            "provider_chain": [
                "pocket",
                "edge",
            ],
        }
    ).provider_chain == [
        "pocket",
        "edge",
    ]

    # And it survives a round trip through asdict.
    chosen = AppSettings.from_dict(
        {
            "settings_version": 2,
            "provider_chain": [
                "pocket",
                "fish",
                "edge",
            ],
        }
    )

    assert AppSettings.from_dict(
        json.loads(
            json.dumps(
                asdict(
                    chosen
                )
            )
        )
    ).provider_chain == [
        "pocket",
        "fish",
        "edge",
    ]


def check_role_voice_choices_work_offline():
    choices = role_voice_choices(
        [],
    )

    assert [
        voice
        for _label, voice in choices
    ] == [
        CA41[("fr", "content")],
        CA41[("fr", "label")],
        CA41[("en", "content")],
        CA41[("en", "label")],
    ]

    kept = role_voice_choices(
        [],
        "fr-FR-HenriNeural",
    )

    assert kept[-1][1] == "fr-FR-HenriNeural"
    assert len(kept) == 5


def check_role_voice_choices_list_the_whole_catalogue():
    catalogue = [
        {
            "ShortName": "ja-JP-NanamiNeural",
            "Locale": "ja-JP",
            "Gender": "Female",
        },
        {
            "ShortName": "fr-FR-RemyMultilingualNeural",
            "Locale": "fr-FR",
            "Gender": "Male",
        },
        {
            "ShortName": "de-DE-SeraphinaMultilingualNeural",
            "Locale": "de-DE",
            "Gender": "Female",
        },
    ]

    choices = role_voice_choices(
        catalogue,
    )

    voices = [
        voice
        for _label, voice in choices
    ]

    # Defaults first, multilingual before the rest, no duplicates.
    assert voices[:4] == list(
        CA41.values()
    )

    assert voices[4:] == [
        "fr-FR-RemyMultilingualNeural",
        "ja-JP-NanamiNeural",
    ]

    # A default the catalogue knows gets its readable label.
    assert (
        "SeraphinaMultilingual - Female (de-DE)",
        "de-DE-SeraphinaMultilingualNeural",
    ) in choices


PROFILE_CATALOGUE = [
    {
        "ShortName": "ja-JP-NanamiNeural",
        "Locale": "ja-JP",
        "Gender": "Female",
    },
    {
        "ShortName": "en-US-JennyNeural",
        "Locale": "en-US",
        "Gender": "Female",
    },
    {
        "ShortName": "en-GB-SoniaNeural",
        "Locale": "en-GB",
        "Gender": "Female",
    },
    {
        "ShortName": "de-DE-SeraphinaMultilingualNeural",
        "Locale": "de-DE",
        "Gender": "Female",
    },
    {
        "ShortName": "en-US-AndrewNeural",
        "Locale": "en-US",
        "Gender": "Male",
    },
]


def check_profile_picker_offers_every_voice_own_language_first():
    voices = [
        voice
        for _label, voice in profile_voice_choices(
            PROFILE_CATALOGUE,
            "en",
        )
    ]

    # The language's own voices in the order the picker always used.
    assert voices[:3] == [
        "en-GB-SoniaNeural",
        "en-US-AndrewNeural",
        "en-US-JennyNeural",
    ]

    # Then the rest, so Seraphina can speak English; no voice twice.
    assert "de-DE-SeraphinaMultilingualNeural" in voices[3:]
    assert "ja-JP-NanamiNeural" in voices[3:]
    assert len(voices) == len(set(voices))


def check_profile_picker_works_offline_and_keeps_the_current_voice():
    voices = [
        voice
        for _label, voice in profile_voice_choices(
            [],
            "en",
            "en-US-JennyNeural",
        )
    ]

    assert "en-US-JennyNeural" in voices
    assert "de-DE-SeraphinaMultilingualNeural" in voices


def check_profile_voice_from_another_locale_resolves_for_v1():
    # A German-locale voice on the English profile: the language stays English.
    plan = parse_speech_plan(
        json.dumps(
            {
                "schemaVersion": 1,
                "side": "back",
                "segments": [
                    {
                        key: value
                        for key, value in FOUR_VOICES[2].items()
                        if key
                        not in (
                            "role",
                            "voiceRole",
                        )
                    }
                    | {
                        "sequence": 1,
                    }
                ],
            }
        ),
        "back",
    )

    segment = resolve_speech_plan(
        plan,
        AppSettings.from_dict(
            {
                "voices": {
                    "en": "de-DE-SeraphinaMultilingualNeural",
                },
            }
        ),
    ).segments[0]

    assert segment.voice == "de-DE-SeraphinaMultilingualNeural"
    assert segment.resolved_profile_language == "en"
    assert segment.voice_role is None


def run():
    checks = [
        check_defaults_are_ca41,
        check_config_json_ships_the_defaults,
        check_legacy_config_migrates_without_touching_legacy_keys,
        check_partial_role_voices_merge_slot_by_slot,
        check_malformed_role_voices_are_errors,
        check_round_trip_through_asdict,
        check_settings_json_shape_keeps_loading,
        check_addon_overlay_without_role_voices_uses_defaults,
        check_roles_resolve_to_the_four_voices,
        check_v1_segments_keep_the_speech_profile_voice,
        check_language_without_slot_keeps_its_profile_voice,
        check_slot_on_own_voice_provider_keeps_an_edge_voice_for_fallback,
        check_chain_puts_the_slot_provider_first,
        check_label_on_edge_while_content_stays_on_the_primary,
        check_content_falls_back_through_the_chain_with_an_edge_voice,
        check_identity_gains_role_and_voice_and_splits_the_cache,
        check_changed_voice_regenerates_only_that_role,
        check_default_chain_is_edge_with_the_others_kept_but_off,
        check_saved_old_default_chain_migrates_to_edge,
        check_chain_chosen_after_the_change_is_respected,
        check_role_voice_choices_work_offline,
        check_role_voice_choices_list_the_whole_catalogue,
        check_profile_picker_offers_every_voice_own_language_first,
        check_profile_picker_works_offline_and_keeps_the_current_voice,
        check_profile_voice_from_another_locale_resolves_for_v1,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
