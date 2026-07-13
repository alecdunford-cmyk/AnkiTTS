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
        "voice_mode": "front",
    },
    "back": {
        "text": "Back",
        "audio": "Back Audio",
        "voice_mode": "auto",
    },
}


@dataclass
class AppSettings:
    """User-configurable AnkiTTS settings."""

    front_language: str = "fr"

    voices: dict[str, str] = field(
        default_factory=lambda: DEFAULT_VOICES.copy()
    )

    field_mapping: dict[str, dict[str, str]] = field(
        default_factory=lambda: deepcopy(
            DEFAULT_FIELD_MAPPING
        )
    )

    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"

    @property
    def front_text_field(self) -> str:
        return self.field_mapping["front"]["text"]

    @front_text_field.setter
    def front_text_field(
        self,
        value: str,
    ) -> None:
        self.field_mapping["front"]["text"] = value

    @property
    def back_text_field(self) -> str:
        return self.field_mapping["back"]["text"]

    @back_text_field.setter
    def back_text_field(
        self,
        value: str,
    ) -> None:
        self.field_mapping["back"]["text"] = value

    @property
    def front_audio_field(self) -> str:
        return self.field_mapping["front"]["audio"]

    @front_audio_field.setter
    def front_audio_field(
        self,
        value: str,
    ) -> None:
        self.field_mapping["front"]["audio"] = value

    @property
    def back_audio_field(self) -> str:
        return self.field_mapping["back"]["audio"]

    @back_audio_field.setter
    def back_audio_field(
        self,
        value: str,
    ) -> None:
        self.field_mapping["back"]["audio"] = value

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

            voice_mode = mapping_definition.get(
                "voice_mode"
            )

            if voice_mode not in (
                "front",
                "auto",
            ):
                raise ValueError(
                    f'field_mapping["{mapping_name}"]'
                    '["voice_mode"] must be either '
                    '"front" or "auto".'
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
                default_mapping,
            ) in DEFAULT_FIELD_MAPPING.items():
                mapping_definition = (
                    settings.field_mapping.get(
                        mapping_name
                    )
                )

                if isinstance(
                    mapping_definition,
                    dict,
                ):
                    mapping_definition.setdefault(
                        "voice_mode",
                        default_mapping[
                            "voice_mode"
                        ],
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