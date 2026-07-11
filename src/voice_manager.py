from __future__ import annotations

import asyncio
from typing import Any

import edge_tts


class VoiceManager:
    """Retrieves, filters, and formats Edge TTS voices."""

    def __init__(self):
        self._voices: list[dict[str, Any]] | None = None

    def refresh(self) -> list[dict[str, Any]]:
        """Download and cache the current Edge TTS voice list."""

        self._voices = asyncio.run(
            edge_tts.list_voices()
        )

        return self._voices

    def get_all_voices(self) -> list[dict[str, Any]]:
        """Return the cached voice list, downloading it when necessary."""

        if self._voices is None:
            return self.refresh()

        return self._voices

    def get_voices(self, language_code: str) -> list[dict[str, Any]]:
        """
        Return voices whose locales begin with the requested language code.

        Examples:
            fr -> fr-FR, fr-CA, fr-BE, fr-CH
            en -> en-US, en-GB, en-AU
            ja -> ja-JP
        """

        locale_prefix = f"{language_code.lower()}-"

        matching_voices = [
            voice
            for voice in self.get_all_voices()
            if voice.get("Locale", "").lower().startswith(
                locale_prefix
            )
        ]

        return sorted(
            matching_voices,
            key=lambda voice: (
                voice.get("Locale", ""),
                voice.get("ShortName", ""),
            ),
        )

    @staticmethod
    def get_display_name(voice: dict[str, Any]) -> str:
        """Create a concise, readable label for a voice."""

        short_name = voice.get(
            "ShortName",
            "Unknown voice",
        )

        locale = voice.get(
            "Locale",
            "Unknown locale",
        )

        gender = voice.get(
            "Gender",
            "Unknown",
        )

        voice_name = short_name.rsplit(
            "-",
            maxsplit=1,
        )[-1]

        if voice_name.endswith("Neural"):
            voice_name = voice_name.removesuffix(
                "Neural"
            )

        return f"{voice_name} - {gender} ({locale})"