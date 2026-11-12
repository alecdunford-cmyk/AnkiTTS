"""
CA-90 (3) / review batch 4, item B: a sign in a segment's text reaches the voice.

Two boundaries are watched, and no speech service is called:

- the text the generator hands to a provider's synthesize() (a fake provider
  records it), after the speech-text rule (speech_text_version);
- the text the Edge provider hands to edge_tts.Communicate, on the plain route
  and on the carrier route (edge_tts is replaced by a fake that records it).

A sign reaches the voice when it arrives as the identical character, or as the
word for it in the segment's language standing as a word of its own (the rule
has spoken %, the currency signs, the degree sign, +, = and x as words since
CA-29 and rules 6 and 7, because the engines did not say them). Every string
here is invented for these tests.
"""

from __future__ import annotations

import re
from pathlib import Path
from tempfile import TemporaryDirectory

from pydub.generators import Sine

import generator
from providers import edge as edge_module
from providers.edge import (
    EDGE_CARRIERS,
    EdgeProvider,
)
from settings import SpeechProfile
from speech_text import (
    SPEECH_TEXT_VERSION,
    prepare_for_speech,
)
from tests.provider_fakes import FakeProvider


# The signs CA-90 (3) and the managing chat's item B name.
SIGNS = (
    "%",
    "€",
    "$",
    "£",
    "¥",
    "°",
    "&",
    "+",
    "=",
    "×",
    "÷",
    "§",
    "@",
    "#",
    "‰",
    "²",
    "³",
)

# The words the rule speaks a sign as, by language (CA-29, rules 6 and 7).
WORDS = {
    "%": {
        "en": ("percent",),
        "fr": ("pour cent",),
    },
    "€": {
        "en": ("euro", "euros"),
        "fr": ("euro", "euros"),
    },
    "$": {
        "en": ("dollar", "dollars"),
        "fr": ("dollar", "dollars"),
    },
    "£": {
        "en": ("pound", "pounds"),
        "fr": ("livre sterling", "livres sterling"),
    },
    "¥": {
        "en": ("yen",),
        "fr": ("yen", "yens"),
    },
    "°": {
        "en": ("degree", "degrees"),
        "fr": ("degré", "degrés"),
    },
    "+": {
        "en": ("plus",),
        "fr": ("plus",),
    },
    "=": {
        "en": ("equals",),
        "fr": ("égale",),
    },
    "×": {
        "en": ("times",),
        "fr": ("fois",),
    },
}

# The signs that have no word: they must arrive as the identical character.
SIGNS_WITHOUT_A_WORD = tuple(
    sign
    for sign in SIGNS
    if sign not in WORDS
)

LANGUAGES = {
    "en": {
        "language": "en-US",
        "word": "word",
        "number": ("50",),
        "contexts": (
            ("a number before", "It costs 50{s} today"),
            ("a number after", "It costs {s}50 today"),
            ("a number, spaced", "It costs 50 {s} today"),
            ("a word before", "the word{s} here"),
            ("a word after", "the {s}word here"),
            ("a word, spaced", "the word {s} here"),
        ),
    },
    "fr": {
        "language": "fr-FR",
        "word": "mot",
        # French numerals are spelled by the rule, except next to a sign it
        # leaves alone in some places (a superscript): either reaches the voice.
        "number": ("cinquante", "50"),
        "contexts": (
            ("a number before", "Il coûte 50{s} aujourd'hui"),
            ("a number after", "Il coûte {s}50 aujourd'hui"),
            ("a number, spaced", "Il coûte 50 {s} aujourd'hui"),
            ("a word before", "le mot{s} ici"),
            ("a word after", "le {s}mot ici"),
            ("a word, spaced", "le mot {s} ici"),
        ),
    },
}


def standing(
    word,
    text,
):
    """True when word is in text as a word of its own (no letter or decimal
    digit directly on either side; a sign such as a superscript is not a
    letter or a digit here, though Python's \\w counts it)."""

    def glue(
        character,
    ):
        return character.isalpha() or character.isdecimal()

    for match in re.finditer(
        re.escape(
            word
        ),
        text,
    ):
        before = text[
            match.start() - 1 : match.start()
        ]

        after = text[
            match.end() : match.end() + 1
        ]

        if not (
            before
            and glue(
                before
            )
        ) and not (
            after
            and glue(
                after
            )
        ):
            return True

    return False


def reaches(
    sign,
    spoken,
    base,
):
    if sign in spoken:
        return True

    return any(
        standing(
            word,
            spoken,
        )
        for word in WORDS.get(
            sign,
            {},
        ).get(
            base,
            (),
        )
    )


def spoken_by_the_generator(
    text,
    language,
):
    """The text a provider's synthesize() is asked for, through the chain."""

    provider = FakeProvider(
        "edge"
    )

    with TemporaryDirectory() as directory:
        generator.create_audio(
            text,
            language,
            SpeechProfile(
                language,
                "a-voice",
            ),
            lambda identity, fields: Path(
                directory
            )
            / "segment.mp3",
            chain=[
                provider,
            ],
        )

    assert len(
        provider.calls
    ) == 1

    return provider.calls[0][0]


def check_every_sign_reaches_the_provider_in_english_and_french():
    failures = []

    for base, setup in LANGUAGES.items():
        for sign in SIGNS:
            for context, template in setup["contexts"]:
                text = template.format(
                    s=sign
                )

                spoken = spoken_by_the_generator(
                    text,
                    setup["language"],
                )

                # The provider is asked for exactly what the rule prepares.
                assert spoken == prepare_for_speech(
                    text,
                    setup["language"],
                )

                problems = []

                if not reaches(
                    sign,
                    spoken,
                    base,
                ):
                    problems.append(
                        "the sign is gone"
                    )

                # The neighbour is still a word of its own: nothing is glued
                # to the sign's word.
                if "word" in context and not standing(
                    setup["word"],
                    spoken,
                ):
                    problems.append(
                        "the word is glued"
                    )

                if "number" in context and not any(
                    standing(
                        number,
                        spoken,
                    )
                    for number in setup["number"]
                ):
                    problems.append(
                        "the number is glued"
                    )

                if problems:
                    failures.append(
                        f"{base} {sign} beside {context}: "
                        + ", ".join(
                            problems
                        )
                        + f" ({spoken!r})"
                    )

    assert not failures, "\n".join(
        failures
    )


def check_a_sign_with_no_word_arrives_as_the_identical_character():
    # The managing chat's strict test (identical characters at the boundary)
    # for the signs the rule has no word for.
    for base, setup in LANGUAGES.items():
        for sign in SIGNS_WITHOUT_A_WORD:
            for context, template in setup["contexts"]:
                text = template.format(
                    s=sign
                )

                spoken = spoken_by_the_generator(
                    text,
                    setup["language"],
                )

                assert spoken.count(
                    sign
                ) == text.count(
                    sign
                ), (base, sign, context, spoken)


def check_a_sign_touching_a_letter_is_never_glued_into_a_word():
    # The defects the rule had (speech_text_version 4): the sign's word was
    # glued to the letter beside it, or the letter was spelled.
    for text, language, expected in (
        ("le n° 5", "fr", "le n° cinq"),
        ("N°5", "fr", "N°cinq"),
        ("5 M€", "fr", "cinq M€"),
        ("10 k€", "fr", "dix k€"),
        ("the word€ here", "en", "the word€ here"),
        ("le mot£ ici", "fr", "le mot£ ici"),
        ("the word° here", "en", "the word° here"),
        ("It costs %50 today", "en", "It costs percent 50 today"),
        ("Il coûte %50 aujourd'hui", "fr", "Il coûte pour cent cinquante aujourd'hui"),
        ("la R&D", "fr", "la R&D"),
        ("AT&T", "en", "AT&T"),
    ):
        assert prepare_for_speech(
            text,
            language,
        ) == expected, (text, prepare_for_speech(text, language))


def check_what_was_spoken_as_a_word_still_is():
    # Unchanged by this batch: the readings Alec asked for on 2026-11-01.
    for text, language, expected in (
        ("50 %", "fr", "cinquante pour cent"),
        ("50%", "en", "50 percent"),
        ("It costs €20", "en", "It costs 20 euros"),
        ("Ça coûte 20 €", "fr", "Ça coûte vingt euros"),
        ("en €", "fr", "en euros"),
        ("(€)", "fr", "(euros)"),
        ("à 20°", "fr", "à vingt degrés"),
        ("20 °C", "fr", "vingt degrés Celsius"),
        ("5 + 3 = 8", "fr", "cinq, plus, trois, égale, huit"),
        ("10 × 2", "fr", "dix fois deux"),
        ("5 m²", "fr", "cinq mètres carrés"),
        ("5 m³", "en", "5 cubic meters"),
        ("+33", "fr", "plus trente-trois"),
        ("rock & roll", "en", "rock & roll"),
        ("10 ÷ 2", "en", "10 ÷ 2"),
        ("5‰", "en", "5‰"),
        ("user@site", "en", "user@site"),
        ("Tel. #3", "en", "Tel. #3"),
        ("x²", "en", "x²"),
    ):
        assert prepare_for_speech(
            text,
            language,
        ) == expected, (text, prepare_for_speech(text, language))


class FakeEdgeTts:
    """Stands in for the edge_tts package: records the text, sends a tone."""

    def __init__(
        self,
    ):
        self.texts = []
        recorded = self.texts

        clip = Sine(
            440
        ).to_audio_segment(
            duration=300,
            volume=-20,
        )

        class Communicate:
            def __init__(
                self,
                text,
                voice,
                **_rest,
            ):
                recorded.append(
                    text
                )

            async def save(
                self,
                output_file,
            ):
                clip.export(
                    output_file,
                    format="mp3",
                )

            async def stream(
                self,
            ):
                # Audio and no word events: the carrier cannot be matched, so
                # the provider falls back to the plain route (a second call).
                with TemporaryDirectory() as directory:
                    path = Path(
                        directory
                    ) / "clip.mp3"

                    clip.export(
                        str(
                            path
                        ),
                        format="mp3",
                    )

                    data = path.read_bytes()

                yield {
                    "type": "audio",
                    "data": data,
                }

        self.Communicate = Communicate


def check_every_sign_reaches_edge_tts_on_the_plain_and_the_carrier_route():
    fake = FakeEdgeTts()

    original_tts = edge_module.edge_tts
    original_normalise = edge_module.normalise_mp3_in_place

    edge_module.edge_tts = fake
    # The audio after the boundary is not what this check is about.
    edge_module.normalise_mp3_in_place = lambda path: None

    try:
        for base, setup in LANGUAGES.items():
            language = setup["language"]

            for sign in SIGNS:
                for _context, template in setup["contexts"]:
                    prepared = prepare_for_speech(
                        template.format(
                            s=sign
                        ),
                        language,
                    )

                    # A monolingual voice: the plain route.
                    fake.texts.clear()

                    with TemporaryDirectory() as directory:
                        EdgeProvider().synthesize(
                            prepared,
                            language,
                            SpeechProfile(
                                language,
                                f"{language}-PlainNeural",
                            ),
                            Path(
                                directory
                            )
                            / "out.mp3",
                        )

                    assert fake.texts == [
                        prepared,
                    ], (sign, fake.texts)

                    assert reaches(
                        sign,
                        fake.texts[0],
                        base,
                    ), (sign, fake.texts)

                # A multilingual voice and a short text: the carrier route,
                # then the plain route it falls back to (the fake sends no
                # word events). The text after the carrier is untouched.
                for template in (
                    "{s}50",
                    "50{s}",
                    "{s}",
                ):
                    short = prepare_for_speech(
                        template.format(
                            s=sign
                        ),
                        language,
                    )

                    fake.texts.clear()

                    with TemporaryDirectory() as directory:
                        EdgeProvider().synthesize(
                            short,
                            language,
                            SpeechProfile(
                                language,
                                f"{language}-SomeoneMultilingualNeural",
                            ),
                            Path(
                                directory
                            )
                            / "out.mp3",
                        )

                    expected = (
                        [
                            f"{EDGE_CARRIERS[base]} {short}",
                            short,
                        ]
                        if edge_module.carrier_for(
                            short,
                            language,
                            "SomeoneMultilingualNeural",
                        )
                        else [
                            short,
                        ]
                    )

                    assert fake.texts == expected, (sign, fake.texts)

                    assert all(
                        reaches(
                            sign,
                            text,
                            base,
                        )
                        for text in fake.texts
                    ), (sign, fake.texts)

    finally:
        edge_module.edge_tts = original_tts
        edge_module.normalise_mp3_in_place = original_normalise


def check_the_speech_text_version_moved_and_feeds_every_identity():
    # The rule changed what is spoken (the glued signs), so every segment's
    # audio refills once: the version is in every provider's identity, which
    # feeds the generic key, the structured key and the track name (CA-27).
    assert SPEECH_TEXT_VERSION == "5"

    assert EdgeProvider().identity(
        "fr"
    )[
        "speech_text_version"
    ] == "5"


def run():
    checks = [
        check_every_sign_reaches_the_provider_in_english_and_french,
        check_a_sign_with_no_word_arrives_as_the_identical_character,
        check_a_sign_touching_a_letter_is_never_glued_into_a_word,
        check_what_was_spoken_as_a_word_still_is,
        check_every_sign_reaches_edge_tts_on_the_plain_and_the_carrier_route,
        check_the_speech_text_version_moved_and_feeds_every_identity,
    ]

    for check in checks:
        print(
            f"    {check.__name__}...",
            end=" ",
        )

        check()

        print("✓")
