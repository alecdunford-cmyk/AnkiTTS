from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any


DEFAULT_VOICES = {
    "fr": "fr-FR-DeniseNeural",
    "en": "en-US-JennyNeural",
    "ja": "ja-JP-NanamiNeural",
}

DEFAULT_FIELD_MAPPING = {
    "front": {
        "text": "Front",
        "audio": "Front Audio",
        "speech_profile": "front",
    },
    "back": {
        "text": "Back",
        "audio": "Back Audio",
        "speech_profile": "auto",
    },
}

PROVIDER_IDS = (
    "pocket",
    "fish",
    "edge",
)

DEFAULT_PROVIDER_CHAIN = [
    "pocket",
    "fish",
    "edge",
]

REFERENCE_CLIP_DIRECTORY = (
    r"D:\RCE-Project-Archive\Milestones\Card-Audio\reference"
)

DEFAULT_PROVIDER_SETTINGS = {
    "pocket": {
        "engine_python": (
            r"C:\AnkiTTS-engine-env\Scripts\python.exe"
        ),
        "models": {
            "fr": "french",
            "en": "english",
        },
        "reference_clips": {
            "fr": (
                REFERENCE_CLIP_DIRECTORY
                + r"\alec-fr-lively-15s.wav"
            ),
            "en": (
                REFERENCE_CLIP_DIRECTORY
                + r"\alec-en-lively-15s.wav"
            ),
        },
        "start_timeout_seconds": 180,
        "request_timeout_seconds": 300,
        "idle_shutdown_seconds": 300,
    },
    "fish": {
        "model": "s2.1-pro",
        "reference_ids": {
            "fr": "",
            "en": "",
        },
        "timeout_seconds": 60,
    },
    "edge": {},
}


# Ruling CA-41 (Alec, 2026-11-06): who speaks what in a schema-version-2 plan.
# The language is the segment's, not the voice's locale: a multilingual voice
# from another locale speaks the segment's language. A slot's voice is an Edge
# voice; Pocket and Fish take their voice from their own provider settings, so
# a slot on either of them leaves the voice empty.
VOICE_ROLES = (
    "content",
    "label",
)

DEFAULT_ROLE_VOICES = {
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
            "voice": "de-DE-SeraphinaMultilingualNeural",
        },
        "label": {
            "provider": "edge",
            "voice": "en-US-AndrewNeural",
        },
    },
}


def merge_role_voices(
    loaded: Any,
) -> dict[str, dict[str, dict[str, str]]]:
    """
    Overlay loaded role voices on the CA-41 defaults, slot by slot.

    A config written before role voices existed loads with the defaults; a
    malformed one is an error, as a malformed speech profile is.
    """

    merged = deepcopy(
        DEFAULT_ROLE_VOICES
    )

    if loaded is None:
        return merged

    if not isinstance(
        loaded,
        dict,
    ):
        raise ValueError(
            "role_voices must be a dictionary."
        )

    for (
        language,
        slots,
    ) in loaded.items():
        if not isinstance(
            slots,
            dict,
        ):
            raise ValueError(
                f'role_voices["{language}"] must be a dictionary.'
            )

        for (
            voice_role,
            slot,
        ) in slots.items():
            if voice_role not in VOICE_ROLES:
                raise ValueError(
                    f'role_voices["{language}"] has an unknown voice '
                    f'role "{voice_role}"; use content or label.'
                )

            if not isinstance(
                slot,
                dict,
            ):
                raise ValueError(
                    f'role_voices["{language}"]["{voice_role}"] must '
                    "be a dictionary."
                )

            merged.setdefault(
                str(
                    language
                ),
                {},
            )[
                voice_role
            ] = {
                "provider": slot.get(
                    "provider",
                    "edge",
                ),
                "voice": slot.get(
                    "voice",
                    "",
                ),
            }

    return merged


# One row per preset; the speech plan names a row and AnkiTTS resolves it. The
# numbers are the design note's starting point, tuned by ear later (CA-37 (5)).
DEFAULT_TEMPO_PROFILE = "default"

DEFAULT_TEMPO_PROFILES = {
    DEFAULT_TEMPO_PROFILE: {
        "rate": 1.0,
        "pauseFactor": 0.35,
        "minPauseMs": 250,
        "maxPauseMs": 1200,
        "boundaryPauseMs": 700,
    },
    "deep-entry-study": {
        "rate": 1.0,
        "pauseFactor": 0.35,
        "minPauseMs": 250,
        "maxPauseMs": 1200,
        "boundaryPauseMs": 900,
    },
    "deep-recall": {
        "rate": 0.95,
        "pauseFactor": 0.45,
        "minPauseMs": 300,
        "maxPauseMs": 1500,
        "boundaryPauseMs": 900,
    },
    "sense-map": {
        "rate": 1.0,
        "pauseFactor": 0.3,
        "minPauseMs": 200,
        "maxPauseMs": 1000,
        "boundaryPauseMs": 600,
    },
    "translation-group": {
        "rate": 1.0,
        "pauseFactor": 0.3,
        "minPauseMs": 200,
        "maxPauseMs": 1000,
        "boundaryPauseMs": 600,
    },
    "example": {
        "rate": 1.0,
        "pauseFactor": 0.3,
        "minPauseMs": 200,
        "maxPauseMs": 1000,
        "boundaryPauseMs": 600,
    },
    "sentence": {
        "rate": 1.0,
        "pauseFactor": 0.3,
        "minPauseMs": 200,
        "maxPauseMs": 1000,
        "boundaryPauseMs": 600,
    },
}


@dataclass(frozen=True)
class TempoProfile:
    """One resolved row of the tempo table."""

    rate: Decimal
    pause_factor: Decimal
    min_pause_ms: int
    max_pause_ms: int
    boundary_pause_ms: int


def merge_tempo_profiles(
    loaded: Any,
) -> dict[str, dict[str, Any]]:
    """
    Overlay loaded tempo profiles on the defaults, field by field.

    A new name takes any field it leaves out from the "default" row.
    """

    merged = deepcopy(
        DEFAULT_TEMPO_PROFILES
    )

    if loaded is None:
        return merged

    if not isinstance(
        loaded,
        dict,
    ):
        raise ValueError(
            "tempo_profiles must be a dictionary."
        )

    for (
        name,
        fields,
    ) in loaded.items():
        if not isinstance(
            fields,
            dict,
        ):
            raise ValueError(
                f'tempo_profiles["{name}"] must be a dictionary.'
            )

        merged.setdefault(
            str(
                name
            ),
            dict(
                DEFAULT_TEMPO_PROFILES[
                    DEFAULT_TEMPO_PROFILE
                ]
            ),
        ).update(
            fields
        )

    return merged


def merge_provider_settings(
    loaded: Any,
) -> dict[str, dict[str, Any]]:
    """
    Overlay loaded provider settings on the defaults.

    Missing providers, fields and per-language entries keep their
    defaults, so configs written before providers existed migrate on load.
    """

    merged = deepcopy(
        DEFAULT_PROVIDER_SETTINGS
    )

    if not isinstance(
        loaded,
        dict,
    ):
        return merged

    for (
        provider_id,
        provider_settings,
    ) in loaded.items():
        if (
            provider_id not in merged
            or not isinstance(
                provider_settings,
                dict,
            )
        ):
            continue

        for (
            key,
            value,
        ) in provider_settings.items():
            default_value = merged[
                provider_id
            ].get(
                key
            )

            if (
                isinstance(
                    default_value,
                    dict,
                )
                and isinstance(
                    value,
                    dict,
                )
            ):
                default_value.update(
                    {
                        str(language): value[language]
                        for language in value
                    }
                )
            else:
                merged[
                    provider_id
                ][key] = deepcopy(
                    value
                )

    return merged


@dataclass(frozen=True)
class SpeechProfile:
    """Resolved TTS settings for one language."""

    language: str
    voice: str
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"

@dataclass
class AppSettings:
    """User-configurable AnkiTTS settings."""

    front_language: str = "fr"

    voices: dict[str, str] = field(
        default_factory=lambda: DEFAULT_VOICES.copy()
    )

    speech_profiles: dict[str, SpeechProfile] = field(
        default_factory=dict
    )

    field_mapping: dict[str, dict[str, str]] = field(
        default_factory=lambda: deepcopy(
            DEFAULT_FIELD_MAPPING
        )
    )

    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"

    provider_chain: list[str] = field(
        default_factory=lambda: list(
            DEFAULT_PROVIDER_CHAIN
        )
    )

    providers: dict[str, dict[str, Any]] = field(
        default_factory=lambda: deepcopy(
            DEFAULT_PROVIDER_SETTINGS
        )
    )

    role_voices: dict[str, dict[str, dict[str, str]]] = field(
        default_factory=lambda: deepcopy(
            DEFAULT_ROLE_VOICES
        )
    )

    tempo_profiles: dict[str, dict[str, Any]] = field(
        default_factory=lambda: deepcopy(
            DEFAULT_TEMPO_PROFILES
        )
    )

    def get_tempo_profile(
        self,
        name: str,
    ) -> TempoProfile:
        """Resolve a plan's tempo profile; an unknown name is "default"."""

        row = merge_tempo_profiles(
            self.tempo_profiles
        )

        fields = row.get(
            name,
            row[
                DEFAULT_TEMPO_PROFILE
            ],
        )

        return TempoProfile(
            rate=Decimal(
                str(
                    fields[
                        "rate"
                    ]
                )
            ),
            pause_factor=Decimal(
                str(
                    fields[
                        "pauseFactor"
                    ]
                )
            ),
            min_pause_ms=fields[
                "minPauseMs"
            ],
            max_pause_ms=fields[
                "maxPauseMs"
            ],
            boundary_pause_ms=fields[
                "boundaryPauseMs"
            ],
        )

    def get_role_voice(
        self,
        language: str,
        voice_role: str,
    ) -> dict[str, str] | None:
        """Return one language's slot for a voice role, if it has one."""

        return self.role_voices.get(
            language,
            {},
        ).get(
            voice_role
        )

    def get_provider_settings(
        self,
        provider_id: str,
    ) -> dict[str, Any]:
        """Return one provider's settings merged over its defaults."""

        return deepcopy(
            merge_provider_settings(
                self.providers
            ).get(
                provider_id,
                {},
            )
        )

    def get_speech_profile(
        self,
        language: str,
    ) -> SpeechProfile | None:
        """Resolve the speech profile for one language."""

        speech_profile = self.speech_profiles.get(
            language
        )

        if speech_profile is not None:
            return speech_profile

        voice = self.voices.get(
            language
        )

        if voice is None:
            return None

        return SpeechProfile(
            language=language,
            voice=voice,
            rate=self.rate,
            volume=self.volume,
            pitch=self.pitch,
        )

    def validate(self) -> None:
        """Raise ValueError when a setting has an invalid structure."""

        if (
            not isinstance(
                self.front_language,
                str,
            )
            or not self.front_language.strip()
        ):
            raise ValueError(
                "front_language must be a non-empty string."
            )

        self.front_language = (
            self.front_language.strip()
        )

        if not isinstance(
            self.voices,
            dict,
        ):
            raise ValueError(
                "voices must be a dictionary."
            )

        for language, voice in self.voices.items():
            if (
                not isinstance(
                    language,
                    str,
                )
                or not isinstance(
                    voice,
                    str,
                )
            ):
                raise ValueError(
                    "Every voice entry must contain "
                    "string keys and values."
                )

        if not isinstance(
            self.field_mapping,
            dict,
        ):
            raise ValueError(
                "field_mapping must be a dictionary."
            )

        if not self.field_mapping:
            raise ValueError(
                "field_mapping must contain at least one "
                "configured field mapping."
            )

        mapped_field_names = []

        for (
            mapping_name,
            mapping_definition,
        ) in self.field_mapping.items():
            if (
                not isinstance(
                    mapping_name,
                    str,
                )
                or not mapping_name.strip()
            ):
                raise ValueError(
                    "Every field_mapping key must be "
                    "a non-empty string."
                )

            if not isinstance(
                mapping_definition,
                dict,
            ):
                raise ValueError(
                    f'field_mapping["{mapping_name}"] must '
                    "be a dictionary."
                )

            for role in (
                "text",
                "audio",
            ):
                mapped_field_name = (
                    mapping_definition.get(
                        role
                    )
                )

                if (
                    not isinstance(
                        mapped_field_name,
                        str,
                    )
                    or not mapped_field_name.strip()
                ):
                    raise ValueError(
                        f'field_mapping["{mapping_name}"]'
                        f'["{role}"] must be a non-empty string.'
                    )

                mapping_definition[role] = (
                    mapped_field_name.strip()
                )

                mapped_field_names.append(
                    mapping_definition[role]
                )

            speech_profile = mapping_definition.get(
                "speech_profile"
            )

            if speech_profile not in (
                "auto",
                "front",
                "fr",
                "en",
                "ja",
            ):
                raise ValueError(
                    f'field_mapping["{mapping_name}"]'
                    '["speech_profile"] must be one of '
                    '"auto", "front", "fr", "en", or "ja".'
                )

        if (
            len(
                set(
                    mapped_field_names
                )
            )
            != len(
                mapped_field_names
            )
        ):
            raise ValueError(
                "Each mapped text and audio field "
                "must have a unique name."
            )

        for attribute_name in (
            "rate",
            "volume",
            "pitch",
        ):
            value = getattr(
                self,
                attribute_name,
            )

            if not isinstance(
                value,
                str,
            ):
                raise ValueError(
                    f"{attribute_name} must be a string."
                )

        if (
            not isinstance(
                self.provider_chain,
                list,
            )
            or not self.provider_chain
        ):
            raise ValueError(
                "provider_chain must be a non-empty list."
            )

        for provider_id in self.provider_chain:
            if provider_id not in PROVIDER_IDS:
                raise ValueError(
                    f'Unknown provider "{provider_id}" in '
                    "provider_chain; use pocket, fish or edge."
                )

        if len(
            set(
                self.provider_chain
            )
        ) != len(
            self.provider_chain
        ):
            raise ValueError(
                "provider_chain must not repeat a provider."
            )

        if not isinstance(
            self.providers,
            dict,
        ) or not all(
            isinstance(
                provider_settings,
                dict,
            )
            for provider_settings in self.providers.values()
        ):
            raise ValueError(
                "providers must map provider ids to dictionaries."
            )

        self._validate_role_voices()
        self._validate_tempo_profiles()

        if not isinstance(
            self.speech_profiles,
            dict,
        ):
            raise ValueError(
                "speech_profiles must be a dictionary."
            )

        for (
            language,
            speech_profile,
        ) in self.speech_profiles.items():
            if (
                not isinstance(
                    language,
                    str,
                )
                or not language.strip()
            ):
                raise ValueError(
                    "Every speech profile language must "
                    "be a non-empty string."
                )

            if not isinstance(
                speech_profile,
                SpeechProfile,
            ):
                raise ValueError(
                    f'speech_profiles["{language}"] must '
                    "be a SpeechProfile."
                )

            if (
                speech_profile.language
                != language
            ):
                raise ValueError(
                    f'speech_profiles["{language}"] has '
                    "a mismatched language."
                )

            for attribute_name in (
                "voice",
                "rate",
                "volume",
                "pitch",
            ):
                value = getattr(
                    speech_profile,
                    attribute_name,
                )

                if (
                    not isinstance(
                        value,
                        str,
                    )
                    or not value.strip()
                ):
                    raise ValueError(
                        f'speech_profiles["{language}"].'
                        f"{attribute_name} must be a "
                        "non-empty string."
                    )

    def _validate_role_voices(self) -> None:
        if not isinstance(
            self.role_voices,
            dict,
        ):
            raise ValueError(
                "role_voices must be a dictionary."
            )

        for (
            language,
            slots,
        ) in self.role_voices.items():
            if not isinstance(
                slots,
                dict,
            ):
                raise ValueError(
                    f'role_voices["{language}"] must be a dictionary.'
                )

            for (
                voice_role,
                slot,
            ) in slots.items():
                path = f'role_voices["{language}"]["{voice_role}"]'

                if voice_role not in VOICE_ROLES:
                    raise ValueError(
                        f"{path}: use content or label."
                    )

                provider_id = slot.get(
                    "provider"
                )

                voice = slot.get(
                    "voice"
                )

                if provider_id not in PROVIDER_IDS:
                    raise ValueError(
                        f"{path} has an unknown provider "
                        f'"{provider_id}"; use pocket, fish or edge.'
                    )

                if not isinstance(
                    voice,
                    str,
                ):
                    raise ValueError(
                        f"{path} needs a voice string."
                    )

                if (
                    provider_id == "edge"
                    and not voice.strip()
                ):
                    raise ValueError(
                        f"{path} is on Edge and needs a voice."
                    )

    def _validate_tempo_profiles(self) -> None:
        if not isinstance(
            self.tempo_profiles,
            dict,
        ):
            raise ValueError(
                "tempo_profiles must be a dictionary."
            )

        for (
            name,
            fields,
        ) in self.tempo_profiles.items():
            path = f'tempo_profiles["{name}"]'

            if (
                not isinstance(
                    name,
                    str,
                )
                or not name.strip()
            ):
                raise ValueError(
                    "Every tempo profile needs a name."
                )

            if not isinstance(
                fields,
                dict,
            ):
                raise ValueError(
                    f"{path} must be a dictionary."
                )

            unknown = set(
                fields
            ) - set(
                DEFAULT_TEMPO_PROFILES[
                    DEFAULT_TEMPO_PROFILE
                ]
            )

            if unknown:
                raise ValueError(
                    f"{path} has unknown field(s): "
                    f"{', '.join(sorted(str(item) for item in unknown))}."
                )

            for field_name in (
                "rate",
                "pauseFactor",
            ):
                value = fields.get(
                    field_name
                )

                if (
                    isinstance(
                        value,
                        bool,
                    )
                    or not isinstance(
                        value,
                        (
                            int,
                            float,
                        ),
                    )
                    or not value > 0
                ):
                    raise ValueError(
                        f"{path}.{field_name} must be a positive number."
                    )

            for field_name in (
                "minPauseMs",
                "maxPauseMs",
                "boundaryPauseMs",
            ):
                value = fields.get(
                    field_name
                )

                if (
                    isinstance(
                        value,
                        bool,
                    )
                    or not isinstance(
                        value,
                        int,
                    )
                    or value < 0
                ):
                    raise ValueError(
                        f"{path}.{field_name} must be a whole number "
                        "of milliseconds, zero or more."
                    )

            if fields[
                "minPauseMs"
            ] > fields[
                "maxPauseMs"
            ]:
                raise ValueError(
                    f"{path}: minPauseMs cannot exceed maxPauseMs."
                )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> AppSettings:
        """
        Create settings while safely ignoring unknown keys.

        Both the nested field_mapping structure and the
        four legacy field-name keys remain supported.
        """

        settings = cls()

        if isinstance(
            data.get(
                "front_language"
            ),
            str,
        ):
            settings.front_language = data[
                "front_language"
            ]

        if isinstance(
            data.get(
                "voices"
            ),
            dict,
        ):
            settings.voices.update(
                {
                    str(language): str(voice)
                    for language, voice in data[
                        "voices"
                    ].items()
                }
            )

        if "field_mapping" in data:
            loaded_field_mapping = data[
                "field_mapping"
            ]

            if not isinstance(
                loaded_field_mapping,
                dict,
            ):
                raise ValueError(
                    "field_mapping must be a dictionary."
                )

            settings.field_mapping = deepcopy(
                loaded_field_mapping
            )

            for (
                mapping_name,
                mapping_definition,
            ) in settings.field_mapping.items():
                if not isinstance(
                    mapping_definition,
                    dict,
                ):
                    continue

                legacy_voice_mode = (
                    mapping_definition.pop(
                        "voice_mode",
                        None,
                    )
                )

                mapping_definition.setdefault(
                    "speech_profile",
                    (
                        legacy_voice_mode
                        if legacy_voice_mode is not None
                        else "auto"
                    ),
                )

        else:
            legacy_field_settings = {
                "front_text_field": (
                    "front",
                    "text",
                ),
                "back_text_field": (
                    "back",
                    "text",
                ),
                "front_audio_field": (
                    "front",
                    "audio",
                ),
                "back_audio_field": (
                    "back",
                    "audio",
                ),
            }

            for (
                setting_name,
                mapping_location,
            ) in legacy_field_settings.items():
                value = data.get(
                    setting_name
                )

                if isinstance(
                    value,
                    str,
                ):
                    (
                        mapping_name,
                        role,
                    ) = mapping_location

                    settings.field_mapping[
                        mapping_name
                    ][role] = value.strip()

        if isinstance(
            data.get(
                "rate"
            ),
            str,
        ):
            settings.rate = data[
                "rate"
            ]

        if isinstance(
            data.get(
                "volume"
            ),
            str,
        ):
            settings.volume = data[
                "volume"
            ]

        if isinstance(
            data.get(
                "pitch"
            ),
            str,
        ):
            settings.pitch = data[
                "pitch"
            ]

        loaded_chain = data.get(
            "provider_chain"
        )

        if isinstance(
            loaded_chain,
            list,
        ):
            chain = []

            for provider_id in loaded_chain:
                if (
                    provider_id in PROVIDER_IDS
                    and provider_id not in chain
                ):
                    chain.append(
                        provider_id
                    )
                else:
                    print(
                        "Ignoring provider_chain entry: "
                        f"{provider_id!r}"
                    )

            settings.provider_chain = chain or [
                "edge"
            ]

        settings.providers = merge_provider_settings(
            data.get(
                "providers"
            )
        )

        settings.role_voices = merge_role_voices(
            data.get(
                "role_voices"
            )
        )

        settings.tempo_profiles = merge_tempo_profiles(
            data.get(
                "tempo_profiles"
            )
        )

        loaded_speech_profiles = data.get(
            "speech_profiles"
        )

        if loaded_speech_profiles is not None:
            if not isinstance(
                loaded_speech_profiles,
                dict,
            ):
                raise ValueError(
                    "speech_profiles must be a dictionary."
                )

            for (
                language,
                profile_data,
            ) in loaded_speech_profiles.items():
                if (
                    not isinstance(
                        language,
                        str,
                    )
                    or not isinstance(
                        profile_data,
                        dict,
                    )
                ):
                    raise ValueError(
                        "Every speech profile must use "
                        "a string language key and a "
                        "dictionary value."
                    )

                fallback_voice = settings.voices.get(
                    language
                )

                voice = profile_data.get(
                    "voice",
                    fallback_voice,
                )

                if voice is None:
                    raise ValueError(
                        f'No voice is configured for speech '
                        f'profile "{language}".'
                    )

                speech_profile = SpeechProfile(
                    language=language,
                    voice=str(
                        voice
                    ),
                    rate=str(
                        profile_data.get(
                            "rate",
                            settings.rate,
                        )
                    ),
                    volume=str(
                        profile_data.get(
                            "volume",
                            settings.volume,
                        )
                    ),
                    pitch=str(
                        profile_data.get(
                            "pitch",
                            settings.pitch,
                        )
                    ),
                )

                settings.speech_profiles[
                    language
                ] = speech_profile

                settings.voices[
                    language
                ] = speech_profile.voice

        else:
            for (
                language,
                voice,
            ) in settings.voices.items():
                settings.speech_profiles[
                    language
                ] = SpeechProfile(
                    language=language,
                    voice=voice,
                    rate=settings.rate,
                    volume=settings.volume,
                    pitch=settings.pitch,
                )

        settings.validate()

        return settings


def read_addon_config(
    addon_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Return the live add-on configuration exactly as Anki builds it.

    Anki's getConfig overlays meta.json["config"] (what the settings
    dialog saved) on config.json (the shipped defaults), key by key at
    the top level. Development and integration runs use this to read
    the same settings the add-on uses inside Anki.
    """

    if addon_dir is None:
        addon_dir = (
            Path(__file__)
            .resolve()
            .parent
            .parent
            / "addon"
        )

    config: dict[str, Any] = {}

    for file_name, key in (
        (
            "config.json",
            None,
        ),
        (
            "meta.json",
            "config",
        ),
    ):
        path = (
            Path(
                addon_dir
            )
            / file_name
        )

        if not path.exists():
            continue

        with path.open(
            "r",
            encoding="utf-8",
        ) as config_file:
            data = json.load(
                config_file
            )

        if key is not None:
            data = data.get(
                key
            ) or {}

        if isinstance(
            data,
            dict,
        ):
            config.update(
                data
            )

    return config


class SettingsManager:
    """
    Loads and saves AnkiTTS settings as JSON.

    The live add-on does not use this class: it reads Anki's add-on
    config (see read_addon_config). The default settings.json at the
    repository root is a developer file.
    """

    def __init__(
        self,
        settings_path: Path | None = None,
    ) -> None:
        if settings_path is None:
            project_root = (
                Path(__file__)
                .resolve()
                .parent
                .parent
            )

            settings_path = (
                project_root
                / "settings.json"
            )

        self.settings_path = settings_path

    @staticmethod
    def load_addon_config(
        addon_dir: Path | None = None,
    ) -> AppSettings:
        """Load the settings the live add-on uses inside Anki."""

        return AppSettings.from_dict(
            read_addon_config(
                addon_dir
            )
        )

    def load(self) -> AppSettings:
        """Load settings, falling back to defaults when no file exists."""

        if not self.settings_path.exists():
            return AppSettings()

        try:
            with self.settings_path.open(
                "r",
                encoding="utf-8",
            ) as settings_file:
                data = json.load(
                    settings_file
                )

            if not isinstance(
                data,
                dict,
            ):
                raise ValueError(
                    "The settings file must contain "
                    "a JSON object."
                )

            return AppSettings.from_dict(
                data
            )

        except (
            OSError,
            json.JSONDecodeError,
            ValueError,
        ) as error:
            print(
                f"Could not load settings from "
                f"{self.settings_path}: {error}"
            )

            print(
                "Using default settings instead."
            )

            return AppSettings()

    def save(
        self,
        settings: AppSettings,
    ) -> None:
        """Validate and save settings."""

        settings.validate()

        self.settings_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = (
            self.settings_path.with_suffix(
                ".json.tmp"
            )
        )

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as settings_file:
            json.dump(
                asdict(
                    settings
                ),
                settings_file,
                ensure_ascii=False,
                indent=4,
            )

            settings_file.write(
                "\n"
            )

        temporary_path.replace(
            self.settings_path
        )