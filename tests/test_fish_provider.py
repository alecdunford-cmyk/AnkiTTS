from __future__ import annotations

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import urllib.error

from providers.base import NoAudioProduced, ProviderError, ProviderUnavailable
from providers.fish import FishProvider
from settings import SpeechProfile
from speech_text import SPEECH_TEXT_VERSION


CONFIG = {
    "model": "s2.1-pro",
    "reference_ids": {"fr": "fr-voice", "en": ""},
    "timeout_seconds": 7,
}

PROFILE = SpeechProfile("fr", "fr-FR-DeniseNeural", "+0%", "+10%", "+3Hz")


def keys(value):
    return lambda name: value if name == "FISH_API_KEY" else None


def check_identity_capabilities_and_health():
    provider = FishProvider(CONFIG, key_reader=keys("secret"))

    assert provider.capabilities().languages == frozenset({"fr"})
    assert provider.identity("fr") == {
        "provider": "fish-audio",
        "provider_model": "s2.1-pro",
        "provider_version": "v1",
        "reference_id": "fr-voice",
        "speech_text_version": SPEECH_TEXT_VERSION,
    }
    assert provider.cache_fields("fr", PROFILE) == {
        "voice": None,
        "rate": "+0%",
        "volume": None,
        "pitch": None,
    }
    assert provider.health("fr").ok
    assert not provider.health("en").ok

    without_key = FishProvider(CONFIG, key_reader=keys(None))
    health = without_key.health("fr")
    assert not health.ok and "FISH_API_KEY" in health.detail

    try:
        provider.identity("en")
    except ProviderUnavailable:
        pass
    else:
        raise AssertionError("A missing voice id was accepted.")


def check_request_is_built_without_leaking_the_key():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return b"ID3-fake-mp3"

    provider = FishProvider(CONFIG, opener=opener, key_reader=keys("secret-key"))

    with TemporaryDirectory() as directory:
        output = Path(directory) / "out.mp3"
        provider.synthesize("Le phare brille.", "fr", PROFILE, output)

        request = captured["request"]
        body = json.loads(request.data.decode("utf-8"))

        assert request.full_url == "https://api.fish.audio/v1/tts"
        assert request.get_method() == "POST"
        assert request.get_header("Model") == "s2.1-pro"
        assert request.get_header("Authorization") == "Bearer secret-key"
        assert body == {
            "text": "Le phare brille.",
            "reference_id": "fr-voice",
            "format": "mp3",
        }
        assert captured["timeout"] == 7
        assert output.read_bytes() == b"ID3-fake-mp3"
        assert sorted(path.name for path in Path(directory).iterdir()) == ["out.mp3"]


def check_http_errors_and_cooldown():
    def unauthorized(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"message":"bad key"}')
        )

    provider = FishProvider(CONFIG, opener=unauthorized, key_reader=keys("secret-key"))

    with TemporaryDirectory() as directory:
        output = Path(directory) / "out.mp3"

        try:
            provider.synthesize("bonjour", "fr", PROFILE, output)
        except ProviderError as error:
            assert "HTTP 401" in str(error)
            assert "secret-key" not in str(error)
        else:
            raise AssertionError("An HTTP error was hidden.")

        assert not output.exists()
        assert not provider.health("fr").ok

    def bad_request(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 400, "Bad", {}, io.BytesIO(b"text too long"))

    provider = FishProvider(CONFIG, opener=bad_request, key_reader=keys("k"))

    try:
        provider.synthesize("bonjour", "fr", PROFILE, Path("unused.mp3"))
    except ProviderError:
        pass

    assert provider.health("fr").ok


def check_network_failure_and_empty_audio():
    def offline(request, timeout):
        raise urllib.error.URLError("no route")

    provider = FishProvider(CONFIG, opener=offline, key_reader=keys("k"))

    try:
        provider.synthesize("bonjour", "fr", PROFILE, Path("unused.mp3"))
    except ProviderUnavailable:
        pass
    else:
        raise AssertionError("A network failure was hidden.")

    assert not provider.health("fr").ok

    empty = FishProvider(CONFIG, opener=lambda request, timeout: b"", key_reader=keys("k"))

    try:
        empty.synthesize("bonjour", "fr", PROFILE, Path("unused.mp3"))
    except NoAudioProduced:
        pass
    else:
        raise AssertionError("Empty audio was accepted.")


def run():
    checks = [
        check_identity_capabilities_and_health,
        check_request_is_built_without_leaking_the_key,
        check_http_errors_and_cooldown,
        check_network_failure_and_empty_audio,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
