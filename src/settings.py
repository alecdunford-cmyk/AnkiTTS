from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_VOICES = {
    "fr": "fr-FR-DeniseNeural",
    "en": "en-US-JennyNeural",
    "ja": "ja-JP-NanamiNeural",
}


@dataclass
class AppSettings:
    """User-configurable AnkiTTS settings."""

    front_language: str = "fr"

    voices: dict[str, str] = field(
        default_factory=lambda: DEFAULT_VOICES.copy()
    )

    front_text_field: str = "Front"
    back_text_field: str = "Back"
    front_audio_field: str = "Front Audio"
    back_audio_field: str = "Back Audio"

    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"

    def validate(self) -> None:
        """Raise ValueError when a setting has an invalid structure."""

        if (
            not isinstance(self.front_language, str)
            or not self.front_language.strip()
        ):
            raise ValueError(
                "front_language must be a non-empty string."
            )

        if not isinstance(self.voices, dict):
            raise ValueError(
                "voices must be a dictionary."
            )

        for language, voice in self.voices.items():
            if (
                not isinstance(language, str)
                or not isinstance(voice, str)
            ):
                raise ValueError(
                    "Every voice entry must contain string keys and values."
                )

        field_settings = (
            "front_text_field",
            "back_text_field",
            "front_audio_field",
            "back_audio_field",
        )

        for attribute_name in field_settings:
            value = getattr(
                self,
                attribute_name,
            )

            if (
                not isinstance(value, str)
                or not value.strip()
            ):
                raise ValueError(
                    f"{attribute_name} must be a non-empty string."
                )

        mapped_fields = [
            self.front_text_field.strip(),
            self.back_text_field.strip(),
            self.front_audio_field.strip(),
            self.back_audio_field.strip(),
        ]

        if len(set(mapped_fields)) != len(mapped_fields):
            raise ValueError(
                "Each mapped text and audio field must have a unique name."
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

            if not isinstance(value, str):
                raise ValueError(
                    f"{attribute_name} must be a string."
                )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> AppSettings:
        """Create settings while safely ignoring unknown keys."""

        settings = cls()

        if isinstance(
            data.get("front_language"),
            str,
        ):
            settings.front_language = data[
                "front_language"
            ]

        if isinstance(
            data.get("voices"),
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

        field_settings = (
            "front_text_field",
            "back_text_field",
            "front_audio_field",
            "back_audio_field",
        )

        for attribute_name in field_settings:
            value = data.get(
                attribute_name
            )

            if isinstance(
                value,
                str,
            ):
                setattr(
                    settings,
                    attribute_name,
                    value.strip(),
                )

        if isinstance(
            data.get("rate"),
            str,
        ):
            settings.rate = data["rate"]

        if isinstance(
            data.get("volume"),
            str,
        ):
            settings.volume = data["volume"]

        if isinstance(
            data.get("pitch"),
            str,
        ):
            settings.pitch = data["pitch"]

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
                    "The settings file must contain a JSON object."
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
                asdict(settings),
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