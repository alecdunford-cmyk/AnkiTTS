"""In-process fake providers for the regression tests (no network, no engine)."""

from __future__ import annotations

from pathlib import Path

import generator
from providers.base import (
    Capabilities,
    HealthStatus,
    NoAudioProduced,
    Provider,
    ProviderError,
)
from providers.audio import LOUDNESS_VERSION
from speech_text import SPEECH_TEXT_VERSION


def forbidden_create_audio(
    **_kwargs,
):
    raise AssertionError(
        "A test reached real synthesis."
    )


class HookProvider(Provider):
    """
    Adapter for tests written against the old module-level hooks.

    Tests assign HOOK.create_audio (text, voice, output_file, rate,
    volume, pitch -> bool) and HOOK.get_edge_provider_identity exactly as
    they used to assign structured_audio.create_audio and
    structured_audio.get_edge_provider_identity.
    """

    provider_id = "test-hook"

    def __init__(self):
        super().__init__()
        self.create_audio = forbidden_create_audio
        self.get_edge_provider_identity = (
            generator.get_edge_provider_identity
        )

    def identity(
        self,
        language,
    ):
        return dict(
            self.get_edge_provider_identity(),
            speech_text_version=SPEECH_TEXT_VERSION,
            loudness_version=LOUDNESS_VERSION,
        )

    def capabilities(self):
        return Capabilities(
            languages=None,
            native_rate=True,
            volume=True,
            pitch=True,
            local=True,
            max_parallel=3,
        )

    def voices(
        self,
        language,
    ):
        return []

    def health(
        self,
        language=None,
    ):
        return HealthStatus(
            True,
            "test",
        )

    def synthesize(
        self,
        text,
        language,
        profile,
        output_path,
    ):
        created = self.create_audio(
            text=text,
            voice=profile.voice,
            output_file=str(
                output_path
            ),
            rate=profile.rate,
            volume=profile.volume,
            pitch=profile.pitch,
        )

        if not created:
            raise NoAudioProduced(
                "test hook returned no audio"
            )


class FakeProvider(Provider):
    """A configurable provider that records its calls."""

    def __init__(
        self,
        provider_id,
        identity=None,
        languages=None,
        healthy=True,
        fail_with=None,
        native_rate=False,
        volume=False,
        pitch=False,
        own_voice=True,
    ):
        super().__init__()
        self.provider_id = provider_id
        self._identity = identity or {
            "provider": f"{provider_id}-engine",
            "provider_model": "model-1",
            "provider_version": "1.0",
            "speech_text_version": SPEECH_TEXT_VERSION,
            "loudness_version": LOUDNESS_VERSION,
        }
        self._languages = (
            None
            if languages is None
            else frozenset(
                languages
            )
        )
        self.healthy = healthy
        self.fail_with = fail_with
        self._native_rate = native_rate
        self._volume = volume
        self._pitch = pitch
        self._own_voice = own_voice
        self.calls = []
        self.health_checks = 0
        self.closed = False

    def identity(
        self,
        language,
    ):
        return dict(
            self._identity,
            language_voice=f"{self.provider_id}:{language}",
        )

    def capabilities(self):
        return Capabilities(
            languages=self._languages,
            native_rate=self._native_rate,
            volume=self._volume,
            pitch=self._pitch,
            local=True,
            max_parallel=1,
        )

    def uses_own_voice(self):
        return self._own_voice

    def voices(
        self,
        language,
    ):
        return [
            f"{self.provider_id}:{language}"
        ]

    def health(
        self,
        language=None,
    ):
        self.health_checks += 1

        return HealthStatus(
            self.healthy,
            "ok" if self.healthy else "deliberately unhealthy",
        )

    def synthesize(
        self,
        text,
        language,
        profile,
        output_path,
    ):
        self.calls.append(
            (
                text,
                language,
                profile,
            )
        )

        if self.fail_with is not None:
            Path(
                output_path
            ).write_bytes(
                b"partial"
            )

            raise self.fail_with

        Path(
            output_path
        ).write_bytes(
            f"{self.provider_id}:{text}".encode(
                "utf-8"
            )
        )

    def close(self):
        self.closed = True


__all__ = [
    "FakeProvider",
    "HookProvider",
    "NoAudioProduced",
    "ProviderError",
]
