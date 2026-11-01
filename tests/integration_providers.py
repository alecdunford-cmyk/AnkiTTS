"""
End-to-end provider checks through the add-on's own generator.create_audio.

Not part of run_tests.py: they need the Pocket engine venv, the network or a
paid key. Run from the repository root:

    python tests/integration_providers.py pocket     # stage E
    python tests/integration_providers.py fish       # stage F (needs FISH_API_KEY)
    python tests/integration_providers.py fallback   # stage G
    python tests/integration_providers.py all

Settings are the live add-on settings (addon/config.json + meta.json),
modified only in memory. Audio goes to a temporary cache folder that is
deleted afterwards. Sentences are invented for this test.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import time


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault(
    "ANKITTS_LOG_DIR",
    tempfile.mkdtemp(prefix="ankitts-integration-log-"),
)

import cache  # noqa: E402
from generator import create_audio  # noqa: E402
from providers import registry  # noqa: E402
from providers.secrets import read_user_environment  # noqa: E402
from settings import SettingsManager  # noqa: E402


SENTENCES = {
    "fr": "Le vieux phare repeint en jaune guide les barques vers le port.",
    "en": "A paper lantern drifted past the bakery window at dawn.",
}

FISH_VOICES_FILE = Path(
    r"C:\Users\alecd\pf-scratch\tts-bakeoff\round1b\fish-voices-lively.json"
)


def ffprobe_seconds(path):
    from pydub import AudioSegment

    return len(AudioSegment.from_file(str(path))) / 1000.0


def settings_with_chain(chain, **provider_overrides):
    settings = SettingsManager.load_addon_config()
    settings.provider_chain = list(chain)
    settings.providers = deepcopy(settings.providers)

    for provider_id, overrides in provider_overrides.items():
        settings.providers[provider_id].update(overrides)

    settings.validate()

    return settings


def synthesize(settings, language, cache_dir):
    profile = settings.get_speech_profile(language)
    text = SENTENCES[language]
    keys = {}

    def cache_path_for(identity, fields):
        original = cache.CACHE_DIR

        try:
            cache.CACHE_DIR = cache_dir
            path = cache.get_audio_path(
                text=text,
                language=language,
                provider_identity=identity,
                **fields,
            )

        finally:
            cache.CACHE_DIR = original

        keys[path] = dict(identity, **fields)

        return path

    started = time.perf_counter()
    result = create_audio(
        text,
        language,
        profile,
        cache_path_for,
        settings=settings,
    )
    wall = time.perf_counter() - started

    assert result.path.is_file() and result.path.stat().st_size > 0
    assert result.path.parent == cache_dir
    assert keys[result.path]["provider"] == result.identity["provider"]

    original = cache.CACHE_DIR

    try:
        cache.CACHE_DIR = cache_dir
        recomputed = cache.get_audio_path(
            text=text,
            language=language,
            provider_identity=result.identity,
            **{
                key: keys[result.path][key]
                for key in ("voice", "rate", "volume", "pitch")
            },
        )

    finally:
        cache.CACHE_DIR = original

    assert recomputed == result.path, "the cache key does not match the producer"

    seconds = ffprobe_seconds(result.path)

    return result, wall, seconds, text


def report(label, language, result, wall, seconds, text, extra=""):
    identity = ", ".join(
        f"{key}={value if key != 'reference_sha256' else value[:12] + '...'}"
        for key, value in sorted(result.identity.items())
    )

    print(
        f"{label} {language}: provider={result.provider_id} "
        f"generated={result.generated} chars={len(text)} "
        f"bytes={len(text.encode('utf-8'))} file={result.path.stat().st_size} B "
        f"audio={seconds:.2f} s wall={wall:.2f} s RTF={wall / seconds:.2f}{extra}"
    )
    print(f"    identity: {identity}")
    print(f"    cache file: {result.path.name}")


def run_pocket():
    settings = settings_with_chain(["pocket"])

    with tempfile.TemporaryDirectory() as directory:
        cache_dir = Path(directory)
        pocket = registry.get_provider("pocket", settings)

        for language in ("fr", "en"):
            result, wall, seconds, text = synthesize(settings, language, cache_dir)
            assert result.provider_id == "pocket"
            assert result.identity["provider"] == "pocket-tts"
            assert result.generated
            timing = pocket.last_timing or {}
            report(
                "POCKET",
                language,
                result,
                wall,
                seconds,
                text,
                f" (worker: load {timing.get('load_seconds')} s, voice "
                f"{timing.get('voice_seconds')} s, synth "
                f"{timing.get('synth_seconds')} s, worker audio "
                f"{timing.get('audio_seconds')} s)",
            )

        again, wall, _seconds, _text = synthesize(settings, "fr", cache_dir)
        assert again.generated is False and again.provider_id == "pocket"
        print(f"POCKET fr again: served from cache in {wall:.3f} s")

    registry.close_all()


def run_fish():
    if not read_user_environment("FISH_API_KEY"):
        print("FISH: SKIPPED (FISH_API_KEY is not set)")
        return

    voices = json.loads(FISH_VOICES_FILE.read_text(encoding="utf-8"))
    settings = settings_with_chain(
        ["fish"],
        fish={"reference_ids": {"fr": voices["fr"], "en": voices["en"]}},
    )

    for language, text in SENTENCES.items():
        size = len(text.encode("utf-8"))
        print(f"FISH {language}: {len(text)} characters, {size} UTF-8 bytes (< 500: {size < 500})")
        assert size < 500

    with tempfile.TemporaryDirectory() as directory:
        cache_dir = Path(directory)

        for language in ("fr", "en"):
            result, wall, seconds, text = synthesize(settings, language, cache_dir)
            assert result.provider_id == "fish"
            assert result.identity["provider"] == "fish-audio"
            assert result.identity["reference_id"] == voices[language]
            report("FISH", language, result, wall, seconds, text)

    registry.close_all()


def run_fallback():
    settings = settings_with_chain(
        ["pocket", "fish", "edge"],
        pocket={"engine_python": r"C:\does-not-exist\Scripts\python.exe"},
    )

    if FISH_VOICES_FILE.exists() and read_user_environment("FISH_API_KEY"):
        voices = json.loads(FISH_VOICES_FILE.read_text(encoding="utf-8"))
        settings.providers["fish"]["reference_ids"] = {
            "fr": voices["fr"],
            "en": voices["en"],
        }

    with tempfile.TemporaryDirectory() as directory:
        result, wall, seconds, text = synthesize(settings, "fr", Path(directory))
        assert result.provider_id in ("fish", "edge"), result.provider_id
        assert result.identity["provider"] in ("fish-audio", "edge-tts")
        report("FALLBACK", "fr", result, wall, seconds, text)

    registry.close_all()


def main(argv):
    which = argv[1] if len(argv) > 1 else "all"
    stages = {
        "pocket": [run_pocket],
        "fish": [run_fish],
        "fallback": [run_fallback],
        "all": [run_pocket, run_fish, run_fallback],
    }[which]

    for stage in stages:
        stage()

    print(f"integration ({which}): OK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
