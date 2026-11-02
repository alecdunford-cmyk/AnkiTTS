from __future__ import annotations

import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

from ankitts_log import get_logger
from providers.audio import (
    LOUDNESS_VERSION,
    encode_mp3,
    tempo_from_rate,
)
from providers.base import (
    Capabilities,
    HealthStatus,
    NoAudioProduced,
    Provider,
    ProviderError,
    ProviderUnavailable,
)
from providers.secrets import read_user_environment
from speech_text import SPEECH_TEXT_VERSION


FISH_PROVIDER_ID = "fish-audio"
FISH_API_VERSION = "v1"
FISH_TTS_URL = "https://api.fish.audio/v1/tts"
FISH_KEY_VARIABLE = "FISH_API_KEY"
FAILURE_COOLDOWN_SECONDS = 60

logger = get_logger(
    "providers.fish"
)


def _default_opener(
    request,
    timeout,
):
    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        return response.read()


class FishProvider(Provider):
    """Fish Audio TTS API with a cloned voice model per language (paid)."""

    provider_id = "fish"

    def __init__(
        self,
        config=None,
        opener=None,
        key_reader=read_user_environment,
    ):
        super().__init__(
            config
        )

        self.model = str(
            self.config.get(
                "model",
                "s2.1-pro",
            )
        )
        self.reference_ids = {
            language: str(
                reference_id
            )
            for language, reference_id in self.config.get(
                "reference_ids",
                {},
            ).items()
            if reference_id
        }
        self.timeout = float(
            self.config.get(
                "timeout_seconds",
                60,
            )
        )
        self._opener = opener or _default_opener
        self._key_reader = key_reader
        self._down_until = 0.0
        self._down_reason = ""
        self._lock = threading.Lock()

    def capabilities(self):
        return Capabilities(
            languages=frozenset(
                self.reference_ids
            ),
            native_rate=False,
            volume=False,
            pitch=False,
            local=False,
            max_parallel=3,
        )

    def uses_own_voice(self):
        return True

    def identity(
        self,
        language,
    ):
        reference_id = self.reference_ids.get(
            language
        )

        if not reference_id:
            raise ProviderUnavailable(
                f"No Fish voice id is configured for {language}."
            )

        return {
            "provider": FISH_PROVIDER_ID,
            "provider_model": self.model,
            "provider_version": FISH_API_VERSION,
            "reference_id": reference_id,
            "speech_text_version": SPEECH_TEXT_VERSION,
            "loudness_version": LOUDNESS_VERSION,
        }

    def voices(
        self,
        language,
    ):
        reference_id = self.reference_ids.get(
            language
        )

        return [reference_id] if reference_id else []

    def health(
        self,
        language=None,
    ):
        if time.monotonic() < self._down_until:
            return HealthStatus(
                False,
                f"recent failure ({self._down_reason})",
            )

        if not self._key_reader(
            FISH_KEY_VARIABLE
        ):
            return HealthStatus(
                False,
                f"{FISH_KEY_VARIABLE} is not set",
            )

        if (
            language is not None
            and language not in self.reference_ids
        ):
            return HealthStatus(
                False,
                f"no Fish voice id for {language}",
            )

        return HealthStatus(
            True,
            "configured",
        )

    def build_request(
        self,
        text,
        language,
    ):
        key = self._key_reader(
            FISH_KEY_VARIABLE
        )

        if not key:
            raise ProviderUnavailable(
                f"{FISH_KEY_VARIABLE} is not set."
            )

        body = json.dumps(
            {
                "text": text,
                "reference_id": self.identity(
                    language
                )[
                    "reference_id"
                ],
                "format": "mp3",
            },
            ensure_ascii=False,
        ).encode(
            "utf-8"
        )

        return urllib.request.Request(
            FISH_TTS_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "model": self.model,
            },
        )

    def _mark_down(
        self,
        reason,
    ):
        with self._lock:
            self._down_until = (
                time.monotonic()
                + FAILURE_COOLDOWN_SECONDS
            )
            self._down_reason = reason

    def synthesize(
        self,
        text,
        language,
        profile,
        output_path,
    ):
        request = self.build_request(
            text,
            language,
        )

        tempo = tempo_from_rate(
            profile.rate
        )

        started = time.perf_counter()

        try:
            audio = self._opener(
                request,
                self.timeout,
            )

        except urllib.error.HTTPError as error:
            detail = error.read()[:200].decode(
                "utf-8",
                errors="replace",
            )

            if error.code in (
                401,
                402,
                403,
                429,
            ):
                self._mark_down(
                    f"HTTP {error.code}"
                )

            raise ProviderError(
                f"Fish returned HTTP {error.code}: {detail}"
            ) from error

        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as error:
            self._mark_down(
                type(
                    error
                ).__name__
            )

            raise ProviderUnavailable(
                f"Fish could not be reached: {error}"
            ) from error

        if not audio:
            raise NoAudioProduced(
                "Fish returned an empty response."
            )

        output_path = Path(
            output_path
        )

        raw_path = output_path.with_name(
            f".{output_path.name}.fish.mp3"
        )

        try:
            raw_path.write_bytes(
                audio
            )

            # Always through encode_mp3: it normalises the loudness.
            encode_mp3(
                raw_path,
                output_path,
                tempo,
            )

        except Exception as error:
            if output_path.exists():
                output_path.unlink()

            raise ProviderError(
                f"Writing Fish audio failed: {error}"
            ) from error

        finally:
            if raw_path.exists():
                raw_path.unlink()

        logger.info(
            "Fish %s %s: %d UTF-8 bytes, %d audio bytes in %.2f s",
            self.model,
            language,
            len(
                text.encode(
                    "utf-8"
                )
            ),
            len(
                audio
            ),
            time.perf_counter()
            - started,
        )
