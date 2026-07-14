from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
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


class SettingsManager:
    """Loads and saves AnkiTTS settings as JSON."""

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