import hashlib
import unicodedata


MAX_READABLE_LENGTH = 40

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def is_filename_character(character):
    """
    Return whether a Unicode character is suitable for the
    readable portion of a filename.

    Letters, numbers, and combining marks from every writing
    system are retained.
    """

    category = unicodedata.category(
        character
    )

    return category[0] in {
        "L",
        "N",
        "M",
    }


def create_readable_filename_part(
    text,
):
    """
    Create a Unicode-safe, human-readable filename component.
    """

    normalized_text = unicodedata.normalize(
        "NFC",
        text,
    )

    characters = []
    separator_pending = False

    for character in normalized_text:
        if is_filename_character(
            character
        ):
            if (
                separator_pending
                and characters
                and characters[-1] != "_"
            ):
                characters.append(
                    "_"
                )

            characters.append(
                character
            )

            separator_pending = False

        else:
            separator_pending = True

    cleaned = "".join(
        characters
    ).strip(
        "_ ."
    )

    cleaned = cleaned[
        :MAX_READABLE_LENGTH
    ].rstrip(
        "_ ."
    )

    if (
        not cleaned
        or cleaned.upper() in WINDOWS_RESERVED_NAMES
    ):
        return "audio"

    return cleaned


def create_filename(
    text,
):
    """
    Create a stable, Unicode-safe filename from card text.

    The readable portion preserves letters and numbers from any
    language. A deterministic hash prevents collisions.
    """

    readable_part = (
        create_readable_filename_part(
            text
        )
    )

    short_hash = hashlib.sha256(
        text.encode(
            "utf-8"
        )
    ).hexdigest()[:8]

    return (
        f"{readable_part}_{short_hash}.mp3"
    )