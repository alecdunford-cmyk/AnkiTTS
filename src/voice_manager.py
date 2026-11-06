from __future__ import annotations

import asyncio
from typing import Any

import edge_tts

from settings import DEFAULT_ROLE_VOICES


def role_voice_choices(
    catalogue: list[dict[str, Any]],
    current_voice: str = "",
) -> list[tuple[str, str]]:
    """
    Return (label, voice) rows for one role-voice slot's picker.

    A slot may hold any Edge voice, whatever its locale (CA-41 has a German
    multilingual voice speaking English). The four CA-41 defaults always come
    first, so they can be chosen with no network; then multilingual voices,
    which suit a language not their own; then the rest of the live catalogue.
    The slot's current voice is kept even if the catalogue no longer lists it.
    """

    by_name = {
        voice.get(
            "ShortName",
            "",
        ): voice
        for voice in catalogue
    }

    def label(
        name,
    ):
        voice = by_name.get(
            name
        )

        return (
            VoiceManager.get_display_name(
                voice
            )
            if voice is not None
            else name
        )

    default_names = [
        slot[
            "voice"
        ]
        for slots in DEFAULT_ROLE_VOICES.values()
        for slot in slots.values()
    ]

    catalogue_names = sorted(
        (
            name
            for name in by_name
            if name
        ),
        key=lambda name: (
            "Multilingual" not in name,
            by_name[
                name
            ].get(
                "Locale",
                "",
            ),
            name,
        ),
    )

    choices = []
    seen = set()

    for name in (
        *default_names,
        *catalogue_names,
        current_voice,
    ):
        if (
            not name
            or name in seen
        ):
            continue

        seen.add(
            name
        )

        choices.append(
            (
                label(
                    name
                ),
                name,
            )
        )

    return choices


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