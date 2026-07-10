import re

from detector import detect_language


def split_segments(text):
    """
    Split text while preserving parenthetical groups.
    """

    segments = re.split(
        r'(\([^)]*\))',
        text
    )

    results = []

    for segment in segments:
        segment = segment.strip()

        if not segment:
            continue

        # Remove parentheses but keep the contents
        is_parenthetical = False
        
        if segment.startswith("(") and segment.endswith(")"):
            segment = segment[1:-1].strip()
            is_parenthetical = True

        # Further split long segments at semicolons
        parts = segment.split(";")

        for part in parts:
            part = part.strip()

            # Remove punctuation accidentally left at the beginning
            part = part.lstrip(", ")

            if part:
                results.append(part)

    return results


def parse_text(text):
    segments = split_segments(text)

    chunks = []

    for segment in segments:
        is_parenthetical = False

        if segment.startswith("(") and segment.endswith(")"):
            segment = segment [1:-1].strip()
            is_parenthetical = True

        language = detect_language(segment)

        chunks.append(
            {
                "language": language,
                "text": segment,
                "parenthetical": is_parenthetical
            }
        )

    return chunks