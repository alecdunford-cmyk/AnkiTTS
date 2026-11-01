from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Capabilities:
    """What one provider can do; see docs/DESIGN-providers.md section 11."""

    languages: frozenset[str] | None
    native_rate: bool
    volume: bool
    pitch: bool
    local: bool
    max_parallel: int

    def supports_language(
        self,
        language: str,
    ) -> bool:
        return (
            self.languages is None
            or language in self.languages
        )


@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    detail: str


class ProviderError(RuntimeError):
    """A provider could not synthesize one request."""


class ProviderUnavailable(ProviderError):
    """A provider is not configured or cannot be reached."""


class NoAudioProduced(ProviderError):
    """A provider answered but returned no playable audio."""


class Provider(ABC):
    """
    One speech synthesis engine.

    synthesize() writes a nonempty MP3 at output_path or raises
    ProviderError and leaves nothing behind. profile is a
    settings.SpeechProfile whose rate is an Edge-format percentage that
    already includes any structured speakingRate multiplier.
    """

    provider_id: str = ""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.config = dict(
            config or {}
        )

    @abstractmethod
    def identity(
        self,
        language: str,
    ) -> dict[str, str]:
        """Return provider, provider_model, provider_version and voice ids."""

    @abstractmethod
    def capabilities(self) -> Capabilities:
        """Describe languages and supported speech parameters."""

    @abstractmethod
    def voices(
        self,
        language: str,
    ) -> list[str]:
        """Return the voices this provider can use for a language."""

    @abstractmethod
    def health(
        self,
        language: str | None = None,
    ) -> HealthStatus:
        """Cheap readiness check; never makes a paid call."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        language: str,
        profile: Any,
        output_path: Path,
    ) -> None:
        """Write one MP3 file or raise ProviderError."""

    def cache_fields(
        self,
        language: str,
        profile: Any,
    ) -> dict[str, str | None]:
        """
        Return the profile values that change this provider's audio.

        Ignored parameters are None so they do not split the cache.
        """

        capabilities = self.capabilities()

        return {
            "voice": (
                profile.voice
                if not self.uses_own_voice()
                else None
            ),
            "rate": profile.rate,
            "volume": (
                profile.volume
                if capabilities.volume
                else None
            ),
            "pitch": (
                profile.pitch
                if capabilities.pitch
                else None
            ),
        }

    def uses_own_voice(self) -> bool:
        """True when the voice comes from provider config, not the profile."""

        return False

    def close(self) -> None:
        """Release processes or connections."""
