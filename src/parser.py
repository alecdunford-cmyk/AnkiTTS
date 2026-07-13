import re

from detector import detect_language


PARENTHETICAL_PATTERN = re.compile(
    r"(\([^)]*\))"
)

SENTENCE_BOUNDARY_PATTERN = re.compile(
    r"""
    (?<=[.!?。！？])
    \s+
    |
    (?<=[。！？])
    """,
    flags=re.VERBOSE,
)


def split_sentences(
    text,
):
    """
    Split one text section into independently detectable chunks.

    Sentence-ending punctuation is retained so that pause handling
    can still distinguish complete sentences.
    """

    sentences = re.split(
        SENTENCE_BOUNDARY_PATTERN,
        text,
    )

    results = []

    for sentence in sentences:
        sentence = sentence.strip()

        if not sentence:
            continue

        for part in sentence.split(
            ";"
        ):
            part = part.strip()
            part = part.lstrip(
                ", "
            )

            if part:
                results.append(
                    part
                )

    return results


def split_segments(
    text,
):
    """
    Split text into sentence-level segments while preserving
    whether text originally appeared inside parentheses.
    """

    sections = re.split(
        PARENTHETICAL_PATTERN,
        text,
    )

    results = []

    for section in sections:
        section = section.strip()

        if not section:
            continue

        is_parenthetical = (
            section.startswith(
                "("
            )
            and section.endswith(
                ")"
            )
        )

        if is_parenthetical:
            section = section[
                1:-1
            ].strip()

        for sentence in split_sentences(
            section
        ):
            results.append(
                {
                    "text": sentence,
                    "parenthetical": is_parenthetical,
                }
            )

    return results


def parse_text(
    text,
):
    segments = split_segments(
        text
    )

    chunks = []

    for segment in segments:
        segment_text = segment[
            "text"
        ]

        language = detect_language(
            segment_text
        )

        chunks.append(
            {
                "language": language,
                "text": segment_text,
                "parenthetical": segment[
                    "parenthetical"
                ],
            }
        )

    return chunks