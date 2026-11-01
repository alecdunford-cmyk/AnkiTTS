from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

import cache
import card_processor
import generator
import structured_audio
from generator import SynthesisFailed, create_audio
from providers import registry
from providers.audio import encode_mp3, tempo_from_rate
from providers.base import NoAudioProduced, ProviderError
from providers.edge import EdgeProvider
from rce_contract import create_rce_speech_plan_job
from settings import (
    DEFAULT_PROVIDER_CHAIN,
    AppSettings,
    SpeechProfile,
)
from speech_text import SPEECH_TEXT_VERSION
from tests.provider_fakes import FakeProvider
from tests.test_structured_audio import (
    create_note,
    create_segment,
)


PROFILE = SpeechProfile(
    language="fr",
    voice="fr-FR-DeniseNeural",
    rate="+0%",
    volume="+0%",
    pitch="+0Hz",
)


def generic_cache_path(
    root,
    text="bonjour",
):
    def cache_path_for(
        identity,
        fields,
    ):
        original = cache.CACHE_DIR

        try:
            cache.CACHE_DIR = root

            return cache.get_audio_path(
                text=text,
                language="fr",
                provider_identity=identity,
                **fields,
            )

        finally:
            cache.CACHE_DIR = original

    return cache_path_for


def check_first_healthy_provider_wins():
    with TemporaryDirectory() as directory:
        first = FakeProvider("first")
        second = FakeProvider("second")

        result = create_audio(
            "bonjour",
            "fr",
            PROFILE,
            generic_cache_path(Path(directory)),
            chain=[first, second],
        )

        assert result.provider_id == "first"
        assert result.generated is True
        assert result.identity["provider"] == "first-engine"
        assert len(first.calls) == 1
        assert second.calls == []
        assert result.path.read_bytes() == b"first:bonjour"


def check_unhealthy_provider_falls_through():
    with TemporaryDirectory() as directory:
        first = FakeProvider("first", healthy=False)
        second = FakeProvider("second")

        result = create_audio(
            "bonjour",
            "fr",
            PROFILE,
            generic_cache_path(Path(directory)),
            chain=[first, second],
        )

        assert result.provider_id == "second"
        assert first.calls == []
        assert result.identity["provider"] == "second-engine"


def check_failing_provider_falls_through_and_cleans_up():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        first = FakeProvider(
            "first",
            fail_with=ProviderError("engine crashed"),
        )
        second = FakeProvider("second")

        result = create_audio(
            "bonjour",
            "fr",
            PROFILE,
            generic_cache_path(root),
            chain=[first, second],
        )

        assert result.provider_id == "second"
        assert len(first.calls) == 1
        assert [path.name for path in root.iterdir()] == [
            result.path.name
        ]


def check_unsupported_language_is_skipped():
    with TemporaryDirectory() as directory:
        pocket_like = FakeProvider("first", languages={"fr", "en"})
        edge_like = FakeProvider("second")

        result = create_audio(
            "こんにちは",
            "ja",
            PROFILE,
            generic_cache_path(Path(directory), "こんにちは"),
            chain=[pocket_like, edge_like],
        )

        assert result.provider_id == "second"
        assert pocket_like.health_checks == 0


def check_every_failure_is_reported():
    with TemporaryDirectory() as directory:
        try:
            create_audio(
                "bonjour",
                "fr",
                PROFILE,
                generic_cache_path(Path(directory)),
                chain=[
                    FakeProvider("first", healthy=False),
                    FakeProvider(
                        "second",
                        fail_with=NoAudioProduced("empty"),
                    ),
                ],
            )

        except SynthesisFailed as error:
            assert "first: deliberately unhealthy" in str(error)
            assert "second: empty" in str(error)
            assert error.no_audio_only is True

        else:
            raise AssertionError("A failing chain succeeded.")

        try:
            create_audio(
                "bonjour",
                "fr",
                PROFILE,
                generic_cache_path(Path(directory)),
                chain=[
                    FakeProvider(
                        "first",
                        fail_with=ProviderError("403"),
                    ),
                ],
            )

        except SynthesisFailed as error:
            assert error.no_audio_only is False

        else:
            raise AssertionError("A failing chain succeeded.")


def check_cache_precedence_follows_chain():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        cache_path_for = generic_cache_path(root)
        primary = FakeProvider("primary", healthy=False)
        fallback = FakeProvider("fallback")

        stand_in = create_audio(
            "bonjour", "fr", PROFILE, cache_path_for, chain=[primary, fallback]
        )
        assert stand_in.provider_id == "fallback"

        again = create_audio(
            "bonjour", "fr", PROFILE, cache_path_for, chain=[primary, fallback]
        )
        assert again.provider_id == "fallback"
        assert again.generated is False
        assert len(fallback.calls) == 1

        primary.healthy = True

        recovered = create_audio(
            "bonjour", "fr", PROFILE, cache_path_for, chain=[primary, fallback]
        )
        assert recovered.provider_id == "primary"
        assert recovered.generated is True
        assert recovered.path != stand_in.path

        cached = create_audio(
            "bonjour", "fr", PROFILE, cache_path_for, chain=[primary, fallback]
        )
        assert cached.provider_id == "primary"
        assert cached.generated is False
        assert len(primary.calls) == 1


def check_generic_cache_key_includes_identity():
    edge_identity = generator.get_edge_provider_identity()

    base = cache.get_audio_path(
        text="faire",
        language="fr",
        voice="fr-FR-DeniseNeural",
        provider_identity=edge_identity,
    )

    assert base != cache.get_audio_path(
        text="faire",
        language="fr",
        voice="fr-FR-DeniseNeural",
    )

    for key, value in (
        ("provider", "pocket-tts"),
        ("provider_model", "other"),
        ("provider_version", "0"),
    ):
        changed = dict(edge_identity, **{key: value})

        assert base != cache.get_audio_path(
            text="faire",
            language="fr",
            voice="fr-FR-DeniseNeural",
            provider_identity=changed,
        )

    assert base != cache.get_audio_path(
        text="faire",
        language="fr",
        voice="fr-FR-DeniseNeural",
        provider_identity=dict(edge_identity, reference_sha256="ab"),
    )


def check_structured_edge_key_shape_is_unchanged():
    arguments = {
        "provider": "edge-tts",
        "provider_model": "edge-neural-voices",
        "provider_version": "7.3.1",
        "text": "faire",
        "language": "fr-FR",
        "profile_key": "fr",
        "voice": "fr-FR-DeniseNeural",
        "rate": "+0%",
        "volume": "+0%",
        "pitch": "+0Hz",
    }

    expected = hashlib.sha256(
        json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    assert cache.get_structured_audio_path(**arguments).name == (
        f"{expected}.mp3"
    )

    assert cache.get_structured_audio_path(
        **arguments,
        reference_sha256="a236",
    ).name != f"{expected}.mp3"


def check_ignored_parameters_leave_the_key():
    clone = FakeProvider("clone")
    edge = EdgeProvider()

    loud = SpeechProfile("fr", "fr-FR-DeniseNeural", "+0%", "+20%", "+5Hz")

    assert clone.cache_fields("fr", loud) == {
        "voice": None,
        "rate": "+0%",
        "volume": None,
        "pitch": None,
    }

    assert edge.cache_fields("fr", loud) == {
        "voice": "fr-FR-DeniseNeural",
        "rate": "+0%",
        "volume": "+20%",
        "pitch": "+5Hz",
    }


def check_settings_migrate_and_validate():
    legacy = AppSettings.from_dict(
        {
            "front_language": "fr",
            "voices": {"fr": "fr-FR-DeniseNeural"},
            "front_text_field": "Expression",
        }
    )

    assert legacy.provider_chain == DEFAULT_PROVIDER_CHAIN
    assert legacy.field_mapping["front"]["text"] == "Expression"
    assert legacy.get_provider_settings("pocket")["models"] == {
        "fr": "french",
        "en": "english",
    }

    partial = AppSettings.from_dict(
        {
            "provider_chain": ["edge", "nonsense", "edge", "fish"],
            "providers": {
                "pocket": {"reference_clips": {"fr": "C:/clips/fr.wav"}},
                "fish": {"reference_ids": {"en": "abc"}},
                "elevenlabs": {"key": "x"},
            },
        }
    )

    assert partial.provider_chain == ["edge", "fish"]
    pocket = partial.get_provider_settings("pocket")
    assert pocket["reference_clips"]["fr"] == "C:/clips/fr.wav"
    assert pocket["reference_clips"]["en"].endswith("alec-en-lively-15s.wav")
    assert partial.get_provider_settings("fish")["reference_ids"] == {
        "fr": "",
        "en": "abc",
    }
    assert "elevenlabs" not in partial.providers

    assert AppSettings.from_dict({"provider_chain": []}).provider_chain == [
        "edge"
    ]

    for bad_chain in (["bogus"], [], ["edge", "edge"]):
        settings = AppSettings()
        settings.provider_chain = bad_chain

        try:
            settings.validate()

        except ValueError:
            continue

        raise AssertionError(f"Invalid chain accepted: {bad_chain}")

    from dataclasses import asdict

    round_trip = AppSettings.from_dict(
        json.loads(json.dumps(asdict(partial)))
    )

    assert round_trip.provider_chain == partial.provider_chain
    assert round_trip.providers == partial.providers


def check_registry_resolves_and_reuses_providers():
    settings = AppSettings()
    settings.provider_chain = ["edge"]

    registry.close_all()

    try:
        chain = registry.resolve_chain(settings)
        assert [provider.provider_id for provider in chain] == ["edge"]
        assert registry.resolve_chain(settings)[0] is chain[0]

        settings.providers["edge"] = {"note": "changed"}
        changed = registry.resolve_chain(settings)[0]
        assert changed is not chain[0]

        override = FakeProvider("override")
        registry.set_override_chain([override])
        assert registry.resolve_chain(settings) == [override]

    finally:
        registry.set_override_chain(None)
        registry.close_all()

    assert set(registry.known_provider_ids()) == {"pocket", "fish", "edge"}


def check_generic_path_records_provider_and_skips_no_audio():
    original_cache_dir = cache.CACHE_DIR
    original_output_dir = card_processor.OUTPUT_DIR
    original_stitch = card_processor.stitch_audio

    try:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache.CACHE_DIR = root / "cache"
            cache.CACHE_DIR.mkdir()
            card_processor.OUTPUT_DIR = root
            card_processor.stitch_audio = (
                lambda segments, output: Path(output).write_bytes(b"card")
            )

            primary = FakeProvider("primary", healthy=False)
            fallback = FakeProvider("fallback")
            registry.set_override_chain([primary, fallback])

            chunks = [
                {"text": "bonjour", "language": "fr", "parenthetical": False}
            ]

            filename, statistics = card_processor.process_chunks(
                chunks, "card.mp3", AppSettings()
            )

            assert filename == "card.mp3"
            assert statistics == {"generated": 1, "cached": 0, "skipped": 0}

            [cached_file] = list(cache.CACHE_DIR.iterdir())
            expected = cache.get_audio_path(
                text="bonjour",
                language="fr",
                provider_identity=fallback.identity("fr"),
                **fallback.cache_fields("fr", AppSettings().get_speech_profile("fr")),
            )
            assert cached_file == expected

            registry.set_override_chain(
                [FakeProvider("silent", fail_with=NoAudioProduced("none"))]
            )

            filename, statistics = card_processor.process_chunks(
                [{"text": "rien", "language": "fr", "parenthetical": False}],
                "empty.mp3",
                AppSettings(),
            )

            assert filename is None
            assert statistics["skipped"] == 1

            registry.set_override_chain(
                [FakeProvider("broken", fail_with=ProviderError("403"))]
            )

            try:
                card_processor.process_chunks(
                    [{"text": "rien", "language": "fr", "parenthetical": False}],
                    "broken.mp3",
                    AppSettings(),
                )

            except SynthesisFailed:
                pass

            else:
                raise AssertionError("A provider error was hidden.")

    finally:
        registry.set_override_chain(None)
        cache.CACHE_DIR = original_cache_dir
        card_processor.OUTPUT_DIR = original_output_dir
        card_processor.stitch_audio = original_stitch


def check_structured_track_mixes_providers():
    original_cache_dir = cache.CACHE_DIR
    original_output_dir = structured_audio.OUTPUT_DIR
    original_stitch = structured_audio.stitch_structured_audio

    try:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache.CACHE_DIR = root / "cache"
            cache.CACHE_DIR.mkdir()
            structured_audio.OUTPUT_DIR = root / "output"
            structured_audio.OUTPUT_DIR.mkdir()
            structured_audio.stitch_structured_audio = (
                lambda segments, output: Path(output).write_bytes(b"track")
            )

            clone = FakeProvider("clone", languages={"fr", "en"})
            edge_like = FakeProvider("edgelike")
            registry.set_override_chain([clone, edge_like])

            job = create_rce_speech_plan_job(
                create_note(
                    front_segments=[
                        create_segment(
                            "front", sequence=1, segmentId="a", text="un"
                        ),
                        create_segment(
                            "front",
                            sequence=2,
                            segmentId="b",
                            text="ichi",
                            language="ja-JP",
                        ),
                    ],
                    back_segments=[],
                )
            )

            result = structured_audio.process_structured_job(
                job, AppSettings()
            )

            assert result["statistics"]["generated"] == 2
            assert [call[0] for call in clone.calls] == ["un"]
            assert [call[0] for call in edge_like.calls] == ["ichi"]
            assert (structured_audio.OUTPUT_DIR / result["front"]).exists()

            track = structured_audio.resolve_speech_plan(
                job["speech_plans"]["front"], AppSettings()
            )

            assert result["front"] == (
                structured_audio.create_structured_track_filename(
                    job["rce_card_id"],
                    track,
                    [clone.identity("fr"), edge_like.identity("ja")],
                )
            )

            assert result["front"] != (
                structured_audio.create_structured_track_filename(
                    job["rce_card_id"], track, clone.identity("fr")
                )
            )

    finally:
        registry.set_override_chain(None)
        cache.CACHE_DIR = original_cache_dir
        structured_audio.OUTPUT_DIR = original_output_dir
        structured_audio.stitch_structured_audio = original_stitch


def check_tempo_bounds():
    assert tempo_from_rate("+0%") == Decimal("1")
    assert tempo_from_rate("+25%") == Decimal("1.25")
    assert tempo_from_rate("-20%") == Decimal("0.8")
    assert tempo_from_rate("+150%") == Decimal("2.0")
    assert tempo_from_rate("-75%") == Decimal("0.5")


def check_encode_applies_atempo():
    if shutil.which("ffmpeg") is None:
        print("(ffmpeg not on PATH; skipped)", end=" ")
        return

    from pydub import AudioSegment
    from pydub.generators import Sine

    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "tone.wav"
        Sine(440).to_audio_segment(duration=2000).export(
            str(source), format="wav"
        )

        plain = root / "plain.mp3"
        faster = root / "faster.mp3"
        encode_mp3(source, plain)
        encode_mp3(source, faster, Decimal("2.0"))

        plain_ms = len(AudioSegment.from_file(str(plain)))
        faster_ms = len(AudioSegment.from_file(str(faster)))

        assert 1900 <= plain_ms <= 2150, plain_ms
        assert 950 <= faster_ms <= 1100, faster_ms
        assert not list(root.glob("*.tmp"))


def check_providers_speak_prepared_text_and_cache_uses_original():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        provider = FakeProvider("first")
        cache_path_for = generic_cache_path(root, text="il/elle")

        result = create_audio(
            "il/elle",
            "fr",
            PROFILE,
            cache_path_for,
            chain=[provider],
        )

        assert provider.calls[0][0] == "il, ou elle"
        assert result.path.read_bytes() == b"first:il, ou elle"

        # The key comes from the original text plus the version in the
        # identity, not from what was spoken.
        fields = provider.cache_fields("fr", PROFILE)

        assert result.path == cache_path_for(result.identity, fields)
        assert result.path != generic_cache_path(root, text="il, ou elle")(
            result.identity,
            fields,
        )

        cached = create_audio(
            "il/elle",
            "fr",
            PROFILE,
            cache_path_for,
            chain=[provider],
        )

        assert cached.generated is False
        assert len(provider.calls) == 1


def check_text_without_speakable_content_falls_back_to_the_original():
    with TemporaryDirectory() as directory:
        provider = FakeProvider("first")

        create_audio(
            "[m]",
            "fr",
            PROFILE,
            generic_cache_path(Path(directory), text="[m]"),
            chain=[provider],
        )

        assert provider.calls[0][0] == "[m]"


def check_speech_text_version_is_in_every_identity():
    edge_identity = EdgeProvider().identity("fr")

    assert edge_identity["speech_text_version"] == SPEECH_TEXT_VERSION
    assert edge_identity == dict(
        generator.get_edge_provider_identity(),
        speech_text_version=SPEECH_TEXT_VERSION,
    )
    assert "speech_text_version" not in generator.get_edge_provider_identity()
    assert FakeProvider("x").identity("fr")["speech_text_version"] == (
        SPEECH_TEXT_VERSION
    )

    older = dict(edge_identity, speech_text_version="0")

    assert cache.get_audio_path(
        text="faire",
        language="fr",
        voice="fr-FR-DeniseNeural",
        provider_identity=edge_identity,
    ) != cache.get_audio_path(
        text="faire",
        language="fr",
        voice="fr-FR-DeniseNeural",
        provider_identity=older,
    )

    def structured(identity):
        extra = dict(identity)

        return cache.get_structured_audio_path(
            provider=extra.pop("provider"),
            provider_model=extra.pop("provider_model"),
            provider_version=extra.pop("provider_version"),
            text="faire",
            language="fr-FR",
            profile_key="fr",
            voice="fr-FR-DeniseNeural",
            **extra,
        )

    assert structured(edge_identity) != structured(older)
    assert structured(edge_identity) != structured(
        generator.get_edge_provider_identity()
    )


def check_unusual_characters_are_logged_without_the_text():
    import logging

    records = []

    class Collector(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    collector = Collector(level=logging.INFO)
    original_level = generator.logger.level
    generator.logger.addHandler(collector)
    generator.logger.setLevel(logging.INFO)

    try:
        with TemporaryDirectory() as directory:
            text = "jaune/bleu → [x] vert"

            create_audio(
                text,
                "fr",
                PROFILE,
                generic_cache_path(Path(directory), text=text),
                chain=[FakeProvider("first")],
            )

    finally:
        generator.logger.removeHandler(collector)
        generator.logger.setLevel(original_level)

    speech_records = [
        record for record in records if record.startswith("Speech text")
    ]

    assert any(
        "4 unusual character(s)" in record and "'/[]→'" in record
        for record in speech_records
    ), speech_records

    for record in speech_records:
        for word in ("jaune", "bleu", "vert"):
            assert word not in record, record


def run():
    checks = [
        check_providers_speak_prepared_text_and_cache_uses_original,
        check_text_without_speakable_content_falls_back_to_the_original,
        check_speech_text_version_is_in_every_identity,
        check_unusual_characters_are_logged_without_the_text,
        check_first_healthy_provider_wins,
        check_unhealthy_provider_falls_through,
        check_failing_provider_falls_through_and_cleans_up,
        check_unsupported_language_is_skipped,
        check_every_failure_is_reported,
        check_cache_precedence_follows_chain,
        check_generic_cache_key_includes_identity,
        check_structured_edge_key_shape_is_unchanged,
        check_ignored_parameters_leave_the_key,
        check_settings_migrate_and_validate,
        check_registry_resolves_and_reuses_providers,
        check_generic_path_records_provider_and_skips_no_audio,
        check_structured_track_mixes_providers,
        check_tempo_bounds,
        check_encode_applies_atempo,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
