"""
Speech-text preparation: what a provider is actually asked to say.

Dictionary text carries notation no engine reads aloud (a slash between
alternatives, arrows, equals signs, currency and unit abbreviations, ordinal
suffixes, bracketed labels). prepare_for_speech() turns it into plain words
and pauses just before synthesis, for every provider, on both the generic and
the structured path. The cache key is computed from the original text plus
SPEECH_TEXT_VERSION, never from the prepared text, so the plan text stays the
authority. Bump SPEECH_TEXT_VERSION whenever a rule here changes what is
spoken.

Rules and rulings: docs/DESIGN-providers.md, "Speech text preparation".
"""

from __future__ import annotations

import re
import unicodedata


SPEECH_TEXT_VERSION = "3"

# Alternatives are only rewritten in these languages (CA-21 points 2 and 3).
ALTERNATIVE_WORDS = {
    "en": "or",
    "fr": "ou",
}

# Symbols spoken as a word between two pauses (CA-29). Other languages keep
# the old behaviour: "=" is a pause, "+" is left alone.
PLUS_WORDS = {
    "en": "plus",
    "fr": "plus",
}

EQUALS_WORDS = {
    "en": "equals",
    "fr": "égale",
}

TIMES_WORDS = {
    "en": "times",
    "fr": "fois",
}

# A segment this short, with no sentence in it, is a gloss list (CA-21).
GLOSS_MAXIMUM_WORDS = 12

# Characters that count as ordinary punctuation for the unusual-character log.
ORDINARY_PUNCTUATION = frozenset(
    ".,;:!?'’‘\"“”«»()-–—…"
    "、。「」『』！？（）：；，．・"
)

_BRACKETED = re.compile(
    r"\[([^\[\]]*)\]|\{([^{}]*)\}"
)

_ARROW = re.compile(
    r"\s*→\s*"
)

_EQUALS = re.compile(
    r"\s*=\s*"
)

# A spaced or unspaced plus between two words or numbers; "C++" and "B+" stay.
_PLUS_BETWEEN = re.compile(
    r"(?<=\w) \+ (?=\w)|(?<=\w)\+(?=\w)"
)

_PLUS_SIGN = re.compile(
    r"(?<![\w+])\+(?=\d)"
)

_TIMES = re.compile(
    r"(?<=\d)\s*[×x]\s*(?=\d)|\s*×\s*"
)

_SLASH = re.compile(
    r"(?<=\S)\s*/\s*(?=\S)"
)

_LEFT_TOKEN = re.compile(
    r"[\w'’]*$"
)

_RIGHT_TOKEN = re.compile(
    r"^[\w'’]*"
)

_LEFT_CHUNK = re.compile(
    r"\S*$"
)

_RIGHT_CHUNK = re.compile(
    r"^\S*"
)

_SENTENCE_END = re.compile(
    r"[.!?…。！？]+[\"'”’»)\]}]*(?:\s|$)"
)

# Token pairs around a slash that are not alternatives.
_NOT_ALTERNATIVES = {
    ("km", "h"),
}

# A number as written in each language: French groups thousands with a space
# and uses a decimal comma; English groups with commas and uses a point.
_NUMBER = {
    "fr": r"\d{1,3}(?:[   ]\d{3})+(?:,\d+)?|\d+(?:[,.]\d+)?",
    "en": r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?",
}

# (English one, English many, French one, French many, may stand without a
# number). Single-letter and ambiguous symbols need a number in front.
_UNITS = {
    "mm": ("millimeter", "millimeters", "millimètre", "millimètres", True),
    "cm": ("centimeter", "centimeters", "centimètre", "centimètres", True),
    "dm": ("decimeter", "decimeters", "décimètre", "décimètres", False),
    "m": ("meter", "meters", "mètre", "mètres", False),
    "km": ("kilometer", "kilometers", "kilomètre", "kilomètres", True),
    "mg": ("milligram", "milligrams", "milligramme", "milligrammes", True),
    "g": ("gram", "grams", "gramme", "grammes", False),
    "kg": ("kilogram", "kilograms", "kilogramme", "kilogrammes", True),
    "ml": ("milliliter", "milliliters", "millilitre", "millilitres", True),
    "cl": ("centiliter", "centiliters", "centilitre", "centilitres", True),
    "dl": ("deciliter", "deciliters", "décilitre", "décilitres", True),
    "l": ("liter", "liters", "litre", "litres", False),
    "L": ("liter", "liters", "litre", "litres", False),
    "ms": ("millisecond", "milliseconds", "milliseconde", "millisecondes", False),
    "s": ("second", "seconds", "seconde", "secondes", False),
    "min": ("minute", "minutes", "minute", "minutes", False),
    "h": ("hour", "hours", "heure", "heures", False),
    "ha": ("hectare", "hectares", "hectare", "hectares", False),
    "W": ("watt", "watts", "watt", "watts", False),
    "kW": ("kilowatt", "kilowatts", "kilowatt", "kilowatts", True),
    "kWh": ("kilowatt-hour", "kilowatt-hours", "kilowattheure", "kilowattheures", True),
    "V": ("volt", "volts", "volt", "volts", False),
    "Hz": ("hertz", "hertz", "hertz", "hertz", True),
    "kHz": ("kilohertz", "kilohertz", "kilohertz", "kilohertz", True),
    "MHz": ("megahertz", "megahertz", "mégahertz", "mégahertz", True),
    "km/h": (
        "kilometer per hour",
        "kilometers per hour",
        "kilomètre par heure",
        "kilomètres par heure",
        True,
    ),
    "m/s": (
        "meter per second",
        "meters per second",
        "mètre par seconde",
        "mètres par seconde",
        False,
    ),
}

# Lengths squared or cubed: "m²", and "6 m 2" after a number (CA-30).
_POWER_UNITS = {
    "mm": ("millimeter", "millimètre"),
    "cm": ("centimeter", "centimètre"),
    "dm": ("decimeter", "décimètre"),
    "m": ("meter", "mètre"),
    "km": ("kilometer", "kilomètre"),
}

_CURRENCIES = {
    "€": ("euro", "euros", "euro", "euros"),
    "$": ("dollar", "dollars", "dollar", "dollars"),
    "£": ("pound", "pounds", "livre sterling", "livres sterling"),
    "¥": ("yen", "yen", "yen", "yens"),
}

_PER_WORDS = {
    "en": "per",
    "fr": "par",
}

_FRENCH_ORDINAL_SUFFIXES = (
    r"ième|ieme|ème|eme|ère|er|re|ᵉʳ|ʳᵉ|ᵉ|è|e"
)

_FRENCH_ORDINAL_NOUNS = (
    "siècle|siècles|millénaire|millénaires|arrondissement|dynastie|"
    "république|empire"
)

_ROMAN_VALUES = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
}

_LETTER_NAMES = {
    "en": {
        "b": "bee", "c": "see", "d": "dee", "e": "ee", "f": "eff",
        "g": "gee", "h": "aitch", "j": "jay", "k": "kay", "l": "el",
        "m": "em", "n": "en", "o": "oh", "p": "pee", "q": "cue",
        "r": "are", "s": "ess", "t": "tee", "u": "you", "v": "vee",
        "w": "double you", "x": "ex", "y": "why", "z": "zee",
    },
    "fr": {
        "b": "bé", "c": "cé", "d": "dé", "e": "eu", "f": "effe",
        "g": "gé", "h": "ache", "i": "i", "j": "ji", "k": "ka",
        "l": "elle", "m": "emme", "n": "enne", "p": "pé", "q": "ku",
        "r": "erre", "s": "esse", "t": "té", "u": "u", "v": "vé",
        "w": "double vé", "x": "ixe", "z": "zède",
    },
}

# Lone letters that are words in that language, never spelled out.
_LETTER_WORDS = {
    "en": frozenset("ai"),
    "fr": frozenset("ayo"),
}

_ENUMERATOR = re.compile(
    r"(?:(?<![\w'’\-./@#+\\])\(|(?<![\w'’\-./@#+\\(]))([A-Za-z])\)(?!\w)"
)

# Letter names for the words the lone-letter rule skips.
_ENUMERATOR_NAMES = {
    "en": {
        "a": "ay",
        "i": "eye",
    },
    "fr": {
        "a": "a",
        "o": "o",
        "y": "i grec",
    },
}

_SINGLE_LETTER = re.compile(
    r"(?<![\w'’\-./@#+\\])(?<!\w\()([A-Za-z])(?![\w'’\-/@#+\\]|\.\w|\.\s*[\da-z])"
)

_FRENCH_UNITS = (
    "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept",
    "huit", "neuf", "dix", "onze", "douze", "treize", "quatorze",
    "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf",
)

_FRENCH_TENS = {
    2: "vingt",
    3: "trente",
    4: "quarante",
    5: "cinquante",
    6: "soixante",
}

_FRENCH_MAXIMUM = 10**12

# Units that must be written with a space after the number to count.
_SPACE_REQUIRED = frozenset({"s", "ms"})


def base_language(
    language,
):
    """'en-US' and 'EN_us' both give 'en'."""

    if not language:
        return ""

    return re.split(
        r"[-_]",
        str(
            language
        ).strip().lower(),
    )[0]


def _french_below_hundred(
    number,
    final,
):
    if number < 20:
        return _FRENCH_UNITS[
            number
        ]

    tens, unit = divmod(
        number,
        10,
    )

    if tens == 7:
        if unit == 1:
            return "soixante et onze"

        return "soixante-" + _FRENCH_UNITS[
            10 + unit
        ]

    if tens == 8:
        if unit == 0:
            return "quatre-vingts" if final else "quatre-vingt"

        return "quatre-vingt-" + _FRENCH_UNITS[
            unit
        ]

    if tens == 9:
        return "quatre-vingt-" + _FRENCH_UNITS[
            10 + unit
        ]

    base = _FRENCH_TENS[
        tens
    ]

    if unit == 0:
        return base

    if unit == 1:
        return base + " et un"

    return base + "-" + _FRENCH_UNITS[
        unit
    ]


def _french_below_thousand(
    number,
    final,
):
    hundreds, rest = divmod(
        number,
        100,
    )

    if not hundreds:
        return _french_below_hundred(
            number,
            final,
        )

    words = (
        "cent"
        if hundreds == 1
        else _FRENCH_UNITS[hundreds] + " cent"
    )

    if rest == 0:
        return words + (
            "s"
            if hundreds > 1 and final
            else ""
        )

    return words + " " + _french_below_hundred(
        rest,
        final,
    )


def french_cardinal(
    number,
):
    """A whole number in French words (masculine: "un", never "une")."""

    if number == 0:
        return "zéro"

    parts = []

    for scale, one, many in (
        (10**9, "milliard", "milliards"),
        (10**6, "million", "millions"),
    ):
        count, number = divmod(
            number,
            scale,
        )

        if count:
            parts.append(
                _french_below_thousand(
                    count,
                    True,
                )
                + " "
                + (one if count == 1 else many)
            )

    thousands, number = divmod(
        number,
        1000,
    )

    if thousands:
        parts.append(
            "mille"
            if thousands == 1
            else _french_below_thousand(
                thousands,
                False,
            )
            + " mille"
        )

    if number:
        parts.append(
            _french_below_thousand(
                number,
                True,
            )
        )

    return " ".join(
        parts
    )


def french_ordinal(
    number,
    feminine=False,
):
    """21 gives "vingt et unième"; 1 gives "premier" ("première")."""

    if number == 1:
        return "première" if feminine else "premier"

    words = french_cardinal(
        number
    )

    if words.endswith(
        ("vingts", "cents")
    ):
        words = words[:-1]

    if words.endswith(
        "cinq"
    ):
        return words + "uième"

    if words.endswith(
        "neuf"
    ):
        return words[:-1] + "vième"

    if words.endswith(
        "e"
    ):
        return words[:-1] + "ième"

    if words.endswith(
        "millions"
    ) or words.endswith(
        "milliards"
    ):
        return words[:-1] + "ième"

    return words + "ième"


def _split_number(
    token,
    language,
):
    """(integer text, fraction text or None) from a written number."""

    if language == "fr":
        token = re.sub(
            r"[   ]",
            "",
            token,
        )

        integer, _, fraction = re.sub(
            r"\.",
            ",",
            token,
        ).partition(
            ","
        )

    else:
        integer, _, fraction = token.replace(
            ",",
            "",
        ).partition(
            "."
        )

    return integer, (fraction or None)


def _is_plural(
    token,
    language,
):
    """English: anything but 1. French: 2 and above."""

    integer, fraction = _split_number(
        token,
        language,
    )

    value = float(
        integer + ("." + fraction if fraction else "")
    )

    if language == "fr":
        return value >= 2

    return value != 1


def _french_number_words(
    token,
):
    integer, fraction = _split_number(
        token,
        "fr",
    )

    if len(
        integer
    ) > 1 and integer.startswith(
        "0"
    ):
        return None

    if int(
        integer
    ) >= _FRENCH_MAXIMUM:
        return None

    words = french_cardinal(
        int(
            integer
        )
    )

    if fraction:
        stripped = fraction.lstrip(
            "0"
        )

        words += " virgule " + " ".join(
            ["zéro"] * (len(fraction) - len(stripped))
            + (
                [french_cardinal(int(stripped))]
                if stripped
                else []
            )
        )

    return words


def _spell_french_numbers(
    text,
):
    def replace(
        match,
    ):
        words = _french_number_words(
            match.group(
                0
            )
        )

        return match.group(
            0
        ) if words is None else words

    return re.sub(
        rf"(?<!\w)(?:{_NUMBER['fr']})(?!\w)",
        replace,
        text,
    )


def _roman_value(
    text,
):
    total = 0

    for index, letter in enumerate(
        text
    ):
        value = _ROMAN_VALUES[
            letter
        ]

        if (
            index + 1 < len(text)
            and _ROMAN_VALUES[text[index + 1]] > value
        ):
            total -= value
        else:
            total += value

    return total


def _spell_french_ordinals(
    text,
):
    def digits(
        match,
    ):
        suffix = match.group(
            "suffix"
        )

        number = int(
            match.group(
                "number"
            )
        )

        if number >= _FRENCH_MAXIMUM:
            return match.group(
                0
            )

        if number == 1:
            return french_ordinal(
                1,
                feminine=suffix in (
                    "re",
                    "ère",
                    "ʳᵉ",
                ),
            )

        return french_ordinal(
            number
        )

    text = re.sub(
        rf"(?<![\w.,])(?P<number>\d+)\s?(?P<suffix>{_FRENCH_ORDINAL_SUFFIXES})(?!\w)",
        digits,
        text,
    )

    def roman(
        match,
    ):
        number = _roman_value(
            match.group(
                "roman"
            )
        )

        return french_ordinal(
            number,
            feminine=False,
        ) + " "

    # A numeral is only trusted before a noun that takes one ("XXe siècle"):
    # "Vie" and "Cie" are words, not the 6th and the 101st.
    return re.sub(
        rf"(?<!\w)(?P<roman>[IVXLC]+)\s?(?:{_FRENCH_ORDINAL_SUFFIXES})\s+"
        rf"(?=(?i:{_FRENCH_ORDINAL_NOUNS})(?!\w))",
        roman,
        text,
    )


def _unit_phrase(
    entry,
    plural,
    language,
):
    if language == "fr":
        return entry[3] if plural else entry[2]

    return entry[1] if plural else entry[0]


def _expand_units(
    text,
    language,
):
    number = _NUMBER[
        language
    ]

    per = _PER_WORDS[
        language
    ]

    def currency(
        match,
    ):
        entry = _CURRENCIES[
            match.group(
                "symbol"
            )
        ]

        token = match.group(
            "number"
        )

        phrase = _unit_phrase(
            entry,
            _is_plural(
                token,
                language,
            ),
            language,
        )

        spoken = f"{token} {phrase}"

        if match.group(
            "per"
        ):
            spoken += f" {per} {match.group('per')}"

        return spoken

    symbols = "".join(
        _CURRENCIES
    )

    pattern = (
        rf"(?P<symbol>[{symbols}])\s?(?P<number>{number})(?!\w)"
        rf"(?:\s?/\s?(?P<per>[^\W\d_]+))?"
    )

    text = re.sub(
        pattern,
        currency,
        text,
    )

    pattern = (
        rf"(?<![\w.,])(?P<number>{number})\s?(?P<symbol>[{symbols}])"
        rf"(?:\s?/\s?(?P<per>[^\W\d_]+))?"
    )

    text = re.sub(
        pattern,
        currency,
        text,
    )

    def bare_currency(
        match,
    ):
        entry = _CURRENCIES[
            match.group(
                0
            )
        ]

        return _unit_phrase(
            entry,
            True,
            language,
        )

    text = re.sub(
        rf"[{symbols}]",
        bare_currency,
        text,
    )

    text = re.sub(
        rf"(?<![\w.,])(?P<number>{number})\s?%",
        lambda match: f"{match.group('number')} "
        + ("percent" if language == "en" else "pour cent"),
        text,
    )

    text = re.sub(
        r"\s?%",
        " percent" if language == "en" else " pour cent",
        text,
    )

    def degrees(
        match,
    ):
        scale = match.group(
            "scale"
        )

        token = match.group(
            "number"
        )

        plural = (
            True
            if token is None
            else _is_plural(
                token,
                language,
            )
        )

        if language == "fr":
            word = "degrés" if plural else "degré"
        else:
            word = "degrees" if plural else "degree"

        scale_name = {
            "C": "Celsius",
            "F": "Fahrenheit",
        }.get(
            scale or "",
            "",
        )

        spoken = f"{word} {scale_name}".strip()

        return (
            f"{token} {spoken}"
            if token is not None
            else spoken
        )

    text = re.sub(
        rf"(?:(?<![\w.,])(?P<number>{number})\s?)?°\s?(?P<scale>[CF])?(?!\w)",
        degrees,
        text,
    )

    def power(
        match,
    ):
        names = _POWER_UNITS[
            match.group(
                "unit"
            )
        ]

        exponent = match.group(
            "exponent"
        )

        token = match.groupdict().get(
            "number"
        )

        plural = (
            True
            if token is None
            else _is_plural(
                token,
                language,
            )
        )

        if language == "fr":
            word = names[1] + ("s" if plural else "")

            word += (
                (" carrés" if plural else " carré")
                if exponent in "²2"
                else (" cubes" if plural else " cube")
            )

        else:
            word = names[0] + ("s" if plural else "")

            word = (
                ("square " if exponent in "²2" else "cubic ")
                + word
            )

        return (
            f"{token} {word}"
            if token is not None
            else word
        )

    text = re.sub(
        rf"(?<![\w.,])(?P<number>{number})\s?(?P<unit>km|cm|mm|dm|m)\s?(?P<exponent>[²³23])(?![\w²³])",
        power,
        text,
    )

    text = re.sub(
        r"(?<![\w.,])(?P<unit>km|cm|mm|dm|m)(?P<exponent>[²³])",
        power,
        text,
    )

    symbols = "|".join(
        sorted(
            (
                re.escape(
                    symbol
                )
                for symbol in _UNITS
            ),
            key=len,
            reverse=True,
        )
    )

    def unit(
        match,
    ):
        name = match.group(
            "unit"
        )

        entry = _UNITS[
            name
        ]

        token = match.groupdict().get(
            "number"
        )

        if token is None:
            if not entry[4]:
                return match.group(
                    0
                )

            return _unit_phrase(
                entry,
                True,
                language,
            )

        separator = match.group(
            "separator"
        )

        # "the 1990s" is a decade, not 1990 seconds.
        if name in _SPACE_REQUIRED and not separator.isspace():
            return match.group(
                0
            )

        # "a 3-km walk" is singular in English, whatever the number.
        if separator == "-" and language == "en":
            return f"{token}-" + _unit_phrase(
                entry,
                False,
                language,
            )

        return f"{token} " + _unit_phrase(
            entry,
            _is_plural(
                token,
                language,
            ),
            language,
        )

    # A slash may follow a unit when a number comes next ("3-km/3-hour"),
    # but "km/h" and "m/s" are matched whole before this point.
    text = re.sub(
        rf"(?<![\w.,])(?P<number>{number})(?P<separator>[\s-]?)(?P<unit>{symbols})(?![\w²³]|/[^\W\d])",
        unit,
        text,
    )

    return re.sub(
        rf"(?<![\w/])(?P<unit>{symbols})(?![\w/²³])",
        unit,
        text,
    )


def _spell_letters(
    text,
    language,
):
    names = _LETTER_NAMES[
        language
    ]

    skipped = _LETTER_WORDS[
        language
    ]

    # "a)" and "(b)" number a section: always spoken, even the letters that
    # are words elsewhere, so a listener hears where a new section starts.
    enumerator_names = {
        **names,
        **_ENUMERATOR_NAMES[
            language
        ],
    }

    text = _ENUMERATOR.sub(
        lambda match: enumerator_names.get(
            match.group(
                1
            ).lower(),
            match.group(
                1
            ),
        )
        + ",",
        text,
    )

    def replace(
        match,
    ):
        letter = match.group(
            1
        ).lower()

        if letter in skipped:
            return match.group(
                0
            )

        return names.get(
            letter,
            match.group(
                0
            ),
        )

    return _SINGLE_LETTER.sub(
        replace,
        text,
    )


def _is_alternative_slash(
    match,
):
    text = match.string
    before = text[
        match.start() - 1
    ]
    after = text[
        match.end()
    ]

    if before.isdigit() and after.isdigit():
        return False

    if not (
        before.isalnum()
        or before in "'’)"
    ):
        return False

    if not (
        after.isalnum()
        or after in "("
    ):
        return False

    chunk = _LEFT_CHUNK.search(
        text[: match.start()]
    ).group(
        0
    ) + _RIGHT_CHUNK.match(
        text[match.end() :]
    ).group(
        0
    )

    if "://" in chunk:
        return False

    left = _LEFT_TOKEN.search(
        text[: match.start()]
    ).group(
        0
    )

    right = _RIGHT_TOKEN.match(
        text[match.end() :]
    ).group(
        0
    )

    if (
        len(left) == 1
        and len(right) == 1
        and left.isalpha()
        and right.isalpha()
    ):
        return False

    return (
        left.lower(),
        right.lower(),
    ) not in _NOT_ALTERNATIVES


def _rewrite_slashes(
    text,
    word,
):
    def replace(
        match,
    ):
        if not _is_alternative_slash(
            match
        ):
            return match.group(
                0
            )

        return f", {word} "

    return _SLASH.sub(
        replace,
        text,
    )


def _has_sentence(
    text,
):
    return bool(
        _SENTENCE_END.search(
            text.rstrip()
        )
    )


def _is_gloss(
    text,
):
    return (
        not _has_sentence(
            text
        )
        and len(
            text.split()
        )
        <= GLOSS_MAXIMUM_WORDS
    )


def _tidy(
    text,
):
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    text = re.sub(
        r"\s+,",
        ",",
        text,
    )

    text = re.sub(
        r"([,;:])(?:\s*,)+",
        r"\1",
        text,
    )

    text = re.sub(
        r",\s*([.!?])(?!\.)",
        r"\1",
        text,
    )

    return re.sub(
        r"^[\s,]+|[\s,]+$",
        "",
        text,
    )


def prepare_for_speech(
    text,
    language,
):
    """
    Return the text a provider should synthesize for one segment.

    1. Bracketed "[...]" and "{...}" labels are spoken, read in the flow of the sentence;
       "≈" is dropped; "→" is a pause.
    2. "=" and "+" are spoken ("égale", "plus" / "equals", "plus") between
       two pauses in English and French; "×" and a spaced "x" between numbers
       are "fois" / "times".
    3. English and French only: currency signs, percent, degrees, unit
       abbreviations ("20 km", "m²", "km/h") and ordinal suffixes ("20e")
       become words; French numerals are spelled out; a lone letter is
       spelled by its name.
    4. A slash between word alternatives ("il/elle", "sb / sth") becomes
       ", or " (English) or ", ou " (French): comma before, none after.
    5. In a sentence-less segment of at most 12 words (a gloss list), a bare
       " or " / " ou " gets a comma before it unless it already has one.
       Example sentences (terminal punctuation) and longer text are left alone.

    Doubled punctuation left by these rewrites is collapsed. The engine adds
    its own final full stop (docs/audio-tail-diagnosis-20261101.md), so none
    is added here. Text that no rule touches is returned unchanged.
    """

    if not text:
        return text

    lang = base_language(
        language
    )

    supported = lang in ALTERNATIVE_WORDS

    # A label is read in the flow of the sentence, with no pause.
    prepared = _BRACKETED.sub(
        lambda match: " "
        + (match.group(1) or match.group(2) or "").strip()
        + " ",
        text,
    )

    prepared = prepared.replace(
        "≈",
        " ",
    )

    prepared = _ARROW.sub(
        ", ",
        prepared,
    )

    equals = EQUALS_WORDS.get(
        lang
    )

    prepared = _EQUALS.sub(
        f", {equals}, " if equals else ", ",
        prepared,
    )

    plus = PLUS_WORDS.get(
        lang
    )

    if plus:
        prepared = _PLUS_BETWEEN.sub(
            f", {plus}, ",
            prepared,
        )

        prepared = _PLUS_SIGN.sub(
            f"{plus} ",
            prepared,
        )

    times = TIMES_WORDS.get(
        lang
    )

    if times:
        prepared = _TIMES.sub(
            f" {times} ",
            prepared,
        )

    if supported:
        prepared = _expand_units(
            prepared,
            lang,
        )

        if lang == "fr":
            prepared = _spell_french_ordinals(
                prepared
            )

            prepared = _spell_french_numbers(
                prepared
            )

        prepared = re.sub(
            r"\b(and|et)\s*/\s*(or|ou)\b",
            r"\1 \2",
            prepared,
        )

        word = ALTERNATIVE_WORDS[
            lang
        ]

        prepared = _rewrite_slashes(
            prepared,
            word,
        )

        if _is_gloss(
            prepared
        ):
            prepared = re.sub(
                rf"(?<=[^\s,;:])(?<!\band)(?<!\bet)\s+{word}\s+",
                f", {word} ",
                prepared,
            )

        prepared = _spell_letters(
            prepared,
            lang,
        )

    if prepared == text:
        return text

    return _tidy(
        prepared
    )


def describe_unusual_characters(
    text,
):
    """
    Count the characters outside letters, digits, spaces and ordinary
    punctuation, and name them. Returns (count, sorted distinct characters).
    Characters only: this is what the logs carry, never the text.
    """

    unusual = [
        character
        for character in text
        if not (
            character.isalnum()
            or character.isspace()
            or unicodedata.category(
                character
            ).startswith(
                "M"
            )
            or character in ORDINARY_PUNCTUATION
        )
    ]

    return len(
        unusual
    ), "".join(
        sorted(
            set(
                unusual
            )
        )
    )
