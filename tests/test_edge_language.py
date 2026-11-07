"""
Language to the engine for Edge (CA-55, CA-56): the carrier sentence.

No test here reaches the Edge service. Audio is generated tones, event lists
are written by hand, and every spoken text is invented.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from pydub import AudioSegment
from pydub.generators import Sine

import cache
import generator
from providers import edge as edge_module
from providers.audio import LOUDNESS_VERSION
from providers.edge import (
    EDGE_CARRIERS,
    EDGE_CARRIER_LEAD_SECONDS,
    EDGE_CARRIER_MAX_WORDS,
    EDGE_LANGUAGE_VERSION,
    EdgeProvider,
    carrier_for,
    create_audio_with_carrier,
    cut_leading_audio,
    primary_subtag,
    target_start_seconds,
)
from settings import SpeechProfile
from speech_text import SPEECH_TEXT_VERSION


MULTILINGUAL = "fr-FR-VivienneMultilingualNeural"
MONOLINGUAL = "fr-FR-DeniseNeural"
FR = EDGE_CARRIERS["fr"]
EN = EDGE_CARRIERS["en"]


def tone(milliseconds, peak_dbfs, frequency=440):
    return Sine(frequency).to_audio_segment(
        duration=milliseconds,
        volume=peak_dbfs,
    ).set_frame_rate(24000)


def events_for(carrier, target_words, target_start_seconds_value):
    """Word events as edge-tts returns them: the carrier's words, then the text's."""

    events = []

    for index, word in enumerate(edge_module.spoken_words(carrier)):
        events.append(
            {
                "type": "WordBoundary",
                "offset": int((0.05 + 0.2 * index) * 10_000_000),
                "duration": 1_500_000,
                "text": word.strip(":"),
            }
        )

    for index, word in enumerate(target_words):
        events.append(
            {
                "type": "WordBoundary",
                "offset": int(
                    (target_start_seconds_value + 0.3 * index) * 10_000_000
                ),
                "duration": 2_500_000,
                "text": word,
            }
        )

    return events


class Patched:
    """Replace module attributes for a block and put them back."""

    def __init__(self, module, **replacements):
        self.module = module
        self.replacements = replacements
        self.originals = {}

    def __enter__(self):
        for name, value in self.replacements.items():
            self.originals[name] = getattr(self.module, name)
            setattr(self.module, name, value)

    def __exit__(self, *_exc):
        for name, value in self.originals.items():
            setattr(self.module, name, value)


def fake_two_second_generator(events, calls):
    """A generate_audio_with_events whose first second is loud, second quiet."""

    async def fake(text, voice, output_file, rate="+0%", volume="+0%", pitch="+0Hz"):
        calls.append((text, voice, rate, volume, pitch))
        clip = tone(1000, -6) + tone(1000, -30, 880)
        clip.export(output_file, format="mp3")

        return events

    return fake


def check_carrier_is_for_short_text_on_a_multilingual_voice():
    assert carrier_for("splendide", "fr", MULTILINGUAL) == FR
    assert carrier_for("splendid", "en", MULTILINGUAL) == EN
    assert carrier_for("voir aussi", "fr-FR", MULTILINGUAL) == FR
    assert carrier_for("see also", "en_US", MULTILINGUAL) == EN
    assert carrier_for("a b c d", "fr", MULTILINGUAL) == FR
    assert EDGE_CARRIER_MAX_WORDS == 4
    assert carrier_for("a b c d e", "fr", MULTILINGUAL) is None
    assert carrier_for("Un mot, puis encore un mot, et fin.", "fr", MULTILINGUAL) is None

    # No letter or digit is nothing to say; a dash is not a word.
    assert carrier_for("", "fr", MULTILINGUAL) is None
    assert carrier_for(" ... ", "fr", MULTILINGUAL) is None
    assert carrier_for("mot — mot", "fr", MULTILINGUAL) == FR

    # A monolingual voice reads its own language whatever the text is.
    assert carrier_for("splendide", "fr", MONOLINGUAL) is None
    assert carrier_for("splendide", "fr", "") is None

    # Japanese has no carrier; an unknown or missing language gets none.
    assert carrier_for("語", "ja", "ja-JP-NanamiNeural") is None
    assert carrier_for("splendide", None, MULTILINGUAL) is None
    assert carrier_for("splendide", "xx", MULTILINGUAL) is None

    assert primary_subtag("fr-FR") == "fr"
    assert primary_subtag("EN_us") == "en"
    assert primary_subtag(None) == ""


def check_target_start_is_read_from_the_word_offsets():
    events = events_for(FR, ["important"], 1.7)

    assert abs(target_start_seconds(events, FR) - 1.7) < 1e-9

    events = events_for(EN, ["Voir", "aussi"], 3.16)

    assert abs(target_start_seconds(events, EN) - 3.16) < 1e-9


def check_target_start_refuses_events_that_do_not_fit():
    # Nothing after the carrier (the text produced no word).
    assert target_start_seconds(events_for(FR, [], 0), FR) is None

    # The carrier's last word is not where it should be.
    wrong = events_for(FR, ["important"], 1.7)
    wrong[4]["text"] = "autre"

    assert target_start_seconds(wrong, FR) is None

    # Offsets that do not advance.
    flat = events_for(FR, ["important"], 0.1)

    assert target_start_seconds(flat, FR) is None
    assert target_start_seconds([], FR) is None


def check_the_cut_removes_the_start_and_is_lossless_pcm():
    with TemporaryDirectory() as directory:
        source = Path(directory) / "source.mp3"
        output = Path(directory) / "cut.mp3"

        (tone(1000, -6) + tone(1000, -30, 880)).export(
            str(source),
            format="mp3",
        )

        cut_leading_audio(source, output, 1.0)

        assert output.read_bytes()[:4] == b"RIFF"

        clip = AudioSegment.from_file(str(output))

        assert abs(len(clip) - 1000) < 80
        assert clip.max_dBFS < -25

        try:
            cut_leading_audio(source, output, 30.0)

        except OSError:
            pass

        else:
            raise AssertionError("A cut past the end produced a file.")


def check_carrier_audio_is_cut_at_the_first_word():
    calls = []
    events = events_for(FR, ["important"], 1.0)

    with Patched(
        edge_module,
        generate_audio_with_events=fake_two_second_generator(events, calls),
    ):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "out.mp3"

            created = create_audio_with_carrier(
                text="important",
                voice=MULTILINGUAL,
                output_file=str(output),
                carrier=FR,
                rate="+10%",
                volume="+5%",
                pitch="+2Hz",
            )

            assert created is True
            assert calls == [
                (f"{FR} important", MULTILINGUAL, "+10%", "+5%", "+2Hz")
            ]

            clip = AudioSegment.from_file(str(output))
            expected = 1000 + EDGE_CARRIER_LEAD_SECONDS * 1000

            # The loud first second (the carrier) is gone.
            assert clip.max_dBFS < -25
            assert abs(len(clip) - (2000 - (1000 - EDGE_CARRIER_LEAD_SECONDS * 1000))) < 80
            assert abs(len(clip) - expected) < 80

            assert [p.name for p in Path(directory).iterdir()] == ["out.mp3"]


def check_unmatched_events_fall_back_to_plain_generation():
    plain_calls = []

    def plain(text, voice, output_file, rate="+0%", volume="+0%", pitch="+0Hz"):
        plain_calls.append((text, voice, output_file))
        tone(500, -20).export(output_file, format="mp3")

        return True

    # The service returned no word after the carrier.
    events = events_for(FR, [], 0)

    with Patched(
        edge_module,
        generate_audio_with_events=fake_two_second_generator(events, []),
        create_audio=plain,
    ):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "out.mp3"

            created = create_audio_with_carrier(
                text="important",
                voice=MULTILINGUAL,
                output_file=str(output),
                carrier=FR,
            )

            assert created is True
            assert [call[0] for call in plain_calls] == ["important"]
            assert abs(len(AudioSegment.from_file(str(output))) - 500) < 80
            assert [p.name for p in Path(directory).iterdir()] == ["out.mp3"]


def check_a_failed_cut_falls_back_and_leaves_no_partial_file():
    plain_calls = []

    def plain(text, voice, output_file, rate="+0%", volume="+0%", pitch="+0Hz"):
        plain_calls.append(text)
        tone(500, -20).export(output_file, format="mp3")

        return True

    def broken_cut(source_path, output_path, start_seconds):
        Path(output_path).write_bytes(b"half a file")

        raise OSError("ffmpeg produced nothing")

    events = events_for(FR, ["important"], 1.0)

    with Patched(
        edge_module,
        generate_audio_with_events=fake_two_second_generator(events, []),
        create_audio=plain,
        cut_leading_audio=broken_cut,
    ):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "out.mp3"

            assert create_audio_with_carrier(
                text="important",
                voice=MULTILINGUAL,
                output_file=str(output),
                carrier=FR,
            ) is True

            assert plain_calls == ["important"]
            assert output.read_bytes()[:3] != b"hal"
            assert [p.name for p in Path(directory).iterdir()] == ["out.mp3"]


def check_no_audio_is_retried_then_reported_with_no_file():
    attempts = []
    delays = []

    async def no_audio(text, voice, output_file, **_rest):
        attempts.append(text)
        Path(output_file).write_bytes(b"partial")

        raise edge_module.NoAudioReceived("No audio received.")

    with Patched(
        edge_module,
        generate_audio_with_events=no_audio,
    ):
        original_sleep = edge_module.time.sleep
        edge_module.time.sleep = delays.append

        try:
            with TemporaryDirectory() as directory:
                output = Path(directory) / "out.mp3"

                created = create_audio_with_carrier(
                    text="important",
                    voice=MULTILINGUAL,
                    output_file=str(output),
                    carrier=FR,
                )

                assert created is False
                assert len(attempts) == edge_module.EDGE_NO_AUDIO_MAX_ATTEMPTS
                assert delays == list(edge_module.EDGE_NO_AUDIO_RETRY_DELAYS)
                assert list(Path(directory).iterdir()) == []

        finally:
            edge_module.time.sleep = original_sleep


def check_provider_sends_a_carrier_only_where_it_applies():
    carrier_calls = []
    plain_calls = []

    def carrier_audio(text, voice, output_file, carrier, **rest):
        carrier_calls.append((text, voice, carrier, rest))
        tone(600, -20).export(output_file, format="mp3")

        return True

    def plain_audio(text, voice, output_file, **rest):
        plain_calls.append((text, voice))
        tone(600, -20).export(output_file, format="mp3")

        return True

    def run(text, language, voice):
        with TemporaryDirectory() as directory:
            EdgeProvider().synthesize(
                text,
                language,
                SpeechProfile(language, voice, "+10%", "+0%", "+0Hz"),
                Path(directory) / "out.mp3",
            )

    with Patched(
        edge_module,
        create_audio_with_carrier=carrier_audio,
        create_audio=plain_audio,
    ):
        run("important", "fr", MULTILINGUAL)
        run("splendid", "en", "de-DE-SeraphinaMultilingualNeural")
        run("important", "fr", MONOLINGUAL)
        run("Ceci est une phrase assez longue pour etre reconnue.", "fr", MULTILINGUAL)
        run("hello", "ja", "ja-JP-NanamiNeural")

    assert [(c[0], c[1], c[2]) for c in carrier_calls] == [
        ("important", MULTILINGUAL, FR),
        ("splendid", "de-DE-SeraphinaMultilingualNeural", EN),
    ]
    assert carrier_calls[0][3] == {
        "rate": "+10%",
        "volume": "+0%",
        "pitch": "+0Hz",
    }
    assert [c[0] for c in plain_calls] == [
        "important",
        "Ceci est une phrase assez longue pour etre reconnue.",
        "hello",
    ]


def check_provider_normalises_the_cut_audio_into_an_mp3():
    events = events_for(FR, ["important"], 1.0)

    with Patched(
        edge_module,
        generate_audio_with_events=fake_two_second_generator(events, []),
    ):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "out.mp3"

            EdgeProvider().synthesize(
                "important",
                "fr",
                SpeechProfile("fr", MULTILINGUAL),
                output,
            )

            data = output.read_bytes()

            assert data[:4] != b"RIFF"
            assert data[:3] == b"ID3" or data[0] == 0xFF

            clip = AudioSegment.from_file(str(output))

            assert 900 < len(clip) < 1200
            assert [p.name for p in Path(directory).iterdir()] == ["out.mp3"]


def check_edge_identity_carries_the_language_version_and_moves_the_key():
    identity = EdgeProvider().identity("fr")

    assert EDGE_LANGUAGE_VERSION == "1"
    assert identity == dict(
        generator.get_edge_provider_identity(),
        speech_text_version=SPEECH_TEXT_VERSION,
        loudness_version=LOUDNESS_VERSION,
        edge_language_version="1",
    )

    # The shared base identity that pins version 1 key shapes is untouched.
    assert "edge_language_version" not in generator.get_edge_provider_identity()

    older = dict(identity)
    del older["edge_language_version"]

    def path(fields):
        return cache.get_audio_path(
            text="important",
            language="fr",
            voice=MULTILINGUAL,
            provider_identity=fields,
        )

    assert path(identity) != path(older)
    assert path(identity) != path(dict(identity, edge_language_version="2"))
    assert path(identity) == path(dict(identity))

    def structured(fields):
        extra = dict(fields)

        return cache.get_structured_audio_path(
            provider=extra.pop("provider"),
            provider_model=extra.pop("provider_model"),
            provider_version=extra.pop("provider_version"),
            text="important",
            language="fr",
            profile_key="fr",
            voice=MULTILINGUAL,
            **extra,
        )

    assert structured(identity) != structured(older)


def run():
    checks = [
        check_carrier_is_for_short_text_on_a_multilingual_voice,
        check_target_start_is_read_from_the_word_offsets,
        check_target_start_refuses_events_that_do_not_fit,
        check_the_cut_removes_the_start_and_is_lossless_pcm,
        check_carrier_audio_is_cut_at_the_first_word,
        check_unmatched_events_fall_back_to_plain_generation,
        check_a_failed_cut_falls_back_and_leaves_no_partial_file,
        check_no_audio_is_retried_then_reported_with_no_file,
        check_provider_sends_a_carrier_only_where_it_applies,
        check_provider_normalises_the_cut_audio_into_an_mp3,
        check_edge_identity_carries_the_language_version_and_moves_the_key,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
