"""
Speech-text preparation: what a provider is actually asked to say.

Dictionary text carries notation no engine reads aloud (a slash between
alternatives, arrows, equals signs, bracketed labels). prepare_for_speech()
turns it into plain words and pauses just before synthesis, for every
provider, on both the generic and the structured path. The cache key is
computed from the original text plus SPEECH_TEXT_VERSION, never from the
prepared text, so the plan text stays the authority. Bump
SPEECH_TEXT_VERSION whenever a rule here changes what is spoken.

Rules and rulings: docs/DESIGN-providers.md, "Speech text preparation".
"""

from __future__ import annotations

import re
import unicodedata


SPEECH_TEXT_VERSION = "1"

# Alternatives are only rewritten in these languages (CA-21 points 2 and 3).
ALTERNATIVE_WORDS = {
    "en": "or",
    "fr": "ou",
}

# A segment this short, with no sentence in it, is a gloss list (CA-21).
GLOSS_MAXIMUM_WORDS = 12

# Characters that count as ordinary punctuation for the unusual-character log.
ORDINARY_PUNCTUATION = frozenset(
    ".,;:!?'’‘\"“”«»()-–—…"
    "、。「」『』！？（）：；，．・"
)

_LABELS = re.compile(
    r"\[[^\[\]]*\]|\{[^{}]*\}"
)

_ARROW_OR_EQUALS = re.compile(
    r"\s*[→=]\s*"
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
        r"^[\s,]+",
        "",
        text,
    ).strip()


def prepare_for_speech(
    text,
    language,
):
    """
    Return the text a provider should synthesize for one segment.

    1. A slash between word alternatives ("il/elle", "sb / sth") becomes
       ", or " (English) or ", ou " (French): comma before, none after.
       Other languages are left alone.
    2. In a sentence-less segment of at most 12 words (a gloss list), a bare
       " or " / " ou " gets a comma before it unless it already has one.
       Example sentences (terminal punctuation) and longer text are left alone.
    3. "→" and "=" become a short pause (comma), "≈" is dropped, and bracketed
       "[...]" and "{...}" labels are dropped. Parentheses are kept.

    Doubled punctuation left by these rewrites is collapsed. The engine adds
    its own final full stop (docs/audio-tail-diagnosis-20261101.md), so none
    is added here. Text that no rule touches is returned unchanged.
    """

    if not text:
        return text

    prepared = _LABELS.sub(
        " ",
        text,
    )

    prepared = prepared.replace(
        "≈",
        " ",
    )

    prepared = _ARROW_OR_EQUALS.sub(
        ", ",
        prepared,
    )

    word = ALTERNATIVE_WORDS.get(
        base_language(
            language
        )
    )

    if word:
        prepared = re.sub(
            r"\b(and|et)\s*/\s*(or|ou)\b",
            r"\1 \2",
            prepared,
        )

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
