from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from ankitts_log import get_logger, text_preview
from providers import registry
from providers.base import NoAudioProduced
from providers.edge import (
    EDGE_PROVIDER_ID,
    EDGE_PROVIDER_MODEL,
    get_edge_provider_identity,
)


__all__ = [
    "EDGE_PROVIDER_ID",
    "EDGE_PROVIDER_MODEL",
    "SynthesisFailed",
    "SynthesisResult",
    "create_audio",
    "get_edge_provider_identity",
]

logger = get_logger(
    "generator"
)


@dataclass(frozen=True)
class SynthesisResult:
    """Where one segment's audio is and which provider made it."""

    path: Path
    identity: dict
    provider_id: str
    generated: bool


class SynthesisFailed(RuntimeError):
    """Every provider in the chain declined or failed one segment."""

    def __init__(
        self,
        attempts,
    ):
        self.attempts = list(
            attempts
        )

        reasons = "; ".join(
            f"{provider_id}: {reason}"
            for provider_id, reason, _error in self.attempts
        ) or "no provider is configured"

        super().__init__(
            reasons
        )

    @property
    def no_audio_only(self):
        """
        True when no provider raised a real error.

        Providers that were skipped (unsupported language, unhealthy) are
        ignored; at least one must have answered with no audio. This keeps
        the generic path's old behaviour: Edge's no-audio skips a chunk,
        other errors stay visible.
        """

        synthesis_errors = [
            error
            for _provider_id, _reason, error in self.attempts
            if error is not None
        ]

        return bool(
            synthesis_errors
        ) and all(
            isinstance(
                error,
                NoAudioProduced,
            )
            for error in synthesis_errors
        )


def _is_nonempty_file(
    path,
):
    return (
        path.exists()
        and path.is_file()
        and path.stat().st_size > 0
    )


def create_audio(
    text,
    language,
    profile,
    cache_path_for,
    settings=None,
    chain=None,
):
    """
    Produce one segment's audio through the provider chain.

    For each provider in order: skip it if it cannot serve the language;
    use its cached file if present; otherwise synthesize if it is healthy.
    The first success wins, and its identity is part of the cache key.
    cache_path_for(identity, fields) returns the cache path for one
    provider's identity and the profile fields it uses.
    """

    if chain is None:
        chain = registry.resolve_chain(
            settings
        )

    attempts = []

    for provider in chain:
        provider_id = provider.provider_id

        if not provider.capabilities().supports_language(
            language
        ):
            attempts.append(
                (
                    provider_id,
                    f'language "{language}" is not supported',
                    None,
                )
            )

            continue

        try:
            identity = provider.identity(
                language
            )

            audio_path = Path(
                cache_path_for(
                    identity,
                    provider.cache_fields(
                        language,
                        profile,
                    ),
                )
            )

        except Exception as error:
            attempts.append(
                (
                    provider_id,
                    f"identity failed: {error}",
                    None,
                )
            )

            continue

        if _is_nonempty_file(
            audio_path
        ):
            return SynthesisResult(
                path=audio_path,
                identity=identity,
                provider_id=provider_id,
                generated=False,
            )

        health = provider.health(
            language
        )

        if not health.ok:
            logger.info(
                "Skipping %s for %s: %s",
                provider_id,
                language,
                health.detail,
            )

            attempts.append(
                (
                    provider_id,
                    health.detail,
                    None,
                )
            )

            continue

        if audio_path.exists():
            audio_path.unlink()

        started = time.perf_counter()

        try:
            provider.synthesize(
                text,
                language,
                profile,
                audio_path,
            )

        except Exception as error:
            if audio_path.exists():
                audio_path.unlink()

            logger.warning(
                "%s failed for %s %r: %s: %s",
                provider_id,
                language,
                text_preview(
                    text
                ),
                type(
                    error
                ).__name__,
                error,
            )

            attempts.append(
                (
                    provider_id,
                    str(
                        error
                    ),
                    error,
                )
            )

            continue

        if not _is_nonempty_file(
            audio_path
        ):
            if audio_path.exists():
                audio_path.unlink()

            error = NoAudioProduced(
                "the provider wrote no audio"
            )

            attempts.append(
                (
                    provider_id,
                    str(
                        error
                    ),
                    error,
                )
            )

            continue

        if attempts:
            logger.info(
                "%s produced %s audio after: %s",
                provider_id,
                language,
                "; ".join(
                    f"{failed_id}: {reason}"
                    for failed_id, reason, _error in attempts
                ),
            )

        logger.info(
            "%s synthesized %s %r in %.2f s",
            provider_id,
            language,
            text_preview(
                text
            ),
            time.perf_counter()
            - started,
        )

        return SynthesisResult(
            path=audio_path,
            identity=identity,
            provider_id=provider_id,
            generated=True,
        )

    raise SynthesisFailed(
        attempts
    )
